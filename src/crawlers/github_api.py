"""GitHub Search API 爬虫 —— 自适应日期二分策略。

核心思想
--------
GitHub Search API 对任何一次查询最多返回 **1000 条**（10 页 × 100 条/页）。
star >= 1000 的仓库实际有 10 万+ 个，单次全量查询只能拿到一小部分。

解决方案：「语言 × 创建时间区间」二维切分
1. 对每种编程语言单独查询（语言之间没有交集）。
2. 给定一个创建时间区间 [start, end]，先探测 ``total_count``：
   - total_count <= 1000 → 直接翻页拿完，属于"叶节点"
   - total_count >  1000 → 把区间从中间劈开，左右递归（自适应二分）
3. 最终每个叶节点的结果数都 <= 1000，**理论上不遗漏任何一个仓库**。

为何不限制 star 的上限？
  若一个项目昨天 800 星、今天一夜爆火到 10 万星，
  它仍应被收录（昨天 < 1000、今天 >= 1000）。
  star 上限只会导致漏报。

参数调优
--------
- EARLIEST_DATE: 往前追溯到 2008（GitHub 创立年），覆盖全部历史项目
- PER_PAGE: 固定 100（Search API 最大值），减少请求次数
- MAX_RECURSION_DEPTH: 防止极端情况下无限递归（理论上 2008→今天 ≈ 6000 天，
  二分最多 13 层，远小于 64 的安全上限）
- REQUEST_INTERVAL: 礼貌间隔，避免触发次级速率限制（Secondary Rate Limit）
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import httpx
from rich.console import Console

from src.config import settings
from src.crawlers.languages import LANGUAGE_NONE_SENTINEL, LANGUAGES

console = Console()

_BASE_URL = "https://api.github.com"
_SEARCH_ENDPOINT = "/search/repositories"

# GitHub 创立时间，往前追溯的最早边界
_EARLIEST_DATE = date(2008, 1, 1)

_PER_PAGE = 100
_MAX_RECURSION_DEPTH = 64
_REQUEST_INTERVAL = 1.2  # 秒，PAT 模式下 Search API 约 30 次/分钟


# ── HTTP 工具 ──────────────────────────────────────────────────────────────

def _build_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _parse_repo(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_name": item["full_name"],
        "url": item["html_url"],
        "description": item.get("description") or "",
        "language": item.get("language"),
        "stars": item["stargazers_count"],
        "forks": item.get("forks_count", 0),
        "topics": item.get("topics", []),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "is_fork": item.get("fork", False),
        "is_archived": item.get("archived", False),
    }


def _wait_for_rate_limit(response: httpx.Response) -> None:
    """若剩余配额 <= 3，等到配额重置。"""
    remaining = int(response.headers.get("x-ratelimit-remaining", "999"))
    reset_ts = int(response.headers.get("x-ratelimit-reset", "0"))
    if remaining <= 3 and reset_ts:
        wait = max(reset_ts - int(time.time()), 0) + 5
        console.print(
            f"[yellow]⏳ 速率限制剩余 {remaining}，等待 {wait}s ...[/yellow]"
        )
        time.sleep(wait)


def _search_once(
    client: httpx.Client,
    query: str,
    page: int = 1,
) -> tuple[int, list[dict[str, Any]]]:
    """
    执行一次 Search API 请求。

    Returns
    -------
    (total_count, items)
        total_count: API 报告的总数（注意：> 1000 时也只能翻 10 页）
        items:       本页结果
    """
    params = {
        "q": query,
        "sort": "stars",
        "order": "asc",   # 升序，方便二分边界更精确
        "per_page": _PER_PAGE,
        "page": page,
    }
    time.sleep(_REQUEST_INTERVAL)

    try:
        resp = client.get(_SEARCH_ENDPOINT, params=params)
    except httpx.RequestError as exc:
        console.print(f"[red]网络错误: {exc}[/red]")
        return 0, []

    _wait_for_rate_limit(resp)

    if resp.status_code == 403:
        # 触发次级速率限制时 Retry-After header 会给出等待时间
        retry_after = int(resp.headers.get("retry-after", "60"))
        console.print(f"[yellow]⚠️  403 次级限速，等待 {retry_after}s ...[/yellow]")
        time.sleep(retry_after + 3)
        # 重试一次
        resp = client.get(_SEARCH_ENDPOINT, params=params)

    if resp.status_code != 200:
        console.print(f"[red]HTTP {resp.status_code}: {resp.text[:200]}[/red]")
        return 0, []

    data = resp.json()
    return data.get("total_count", 0), data.get("items", [])


# ── 自适应递归二分核心 ──────────────────────────────────────────────────────

def _fetch_slice(
    client: httpx.Client,
    query_base: str,          # 不含日期约束的基础查询，如 "stars:>=1000 language:Python"
    start: date,
    end: date,
    results: dict[str, dict[str, Any]],
    depth: int = 0,
    stats: dict[str, int] | None = None,
) -> None:
    """
    递归拉取 [start, end] 区间内满足 query_base 的所有仓库。

    - 若 total_count <= 1000：直接翻页拿完（叶节点）
    - 若 total_count >  1000：区间二分，递归处理左右两半
    - 若 start == end：单天也超 1000 条（极罕见，记警告但不再细分）
    """
    if stats is None:
        stats = {}

    indent = "  " * depth
    date_range = f"{start.isoformat()}..{end.isoformat()}"
    query = f"{query_base} created:{date_range}"

    # 先探 total_count
    total, first_items = _search_once(client, query, page=1)
    stats["requests"] = stats.get("requests", 0) + 1

    if total == 0:
        return

    if total <= _PER_PAGE and first_items:
        # 单页能拿完，直接存
        for item in first_items:
            repo = _parse_repo(item)
            results[repo["full_name"]] = repo
        return

    if total <= 1000:
        # 需要翻页，但不需要再分
        # 第 1 页已拿到，继续翻剩余页
        for item in first_items:
            repo = _parse_repo(item)
            results[repo["full_name"]] = repo

        total_pages = min((total + _PER_PAGE - 1) // _PER_PAGE, 10)
        for page in range(2, total_pages + 1):
            _, items = _search_once(client, query, page=page)
            stats["requests"] = stats.get("requests", 0) + 1
            for item in items:
                repo = _parse_repo(item)
                results[repo["full_name"]] = repo
            if len(items) < _PER_PAGE:
                break

        console.print(
            f"{indent}[green]✓[/green] {date_range}"
            f"  total={total}  fetched≈{min(total, 1000)}"
        )
        return

    # total > 1000 → 需要二分
    if start == end or depth >= _MAX_RECURSION_DEPTH:
        # 无法再细分（同一天超 1000 条），尽力拿前 1000 条并记警告
        console.print(
            f"{indent}[yellow]⚠️  {date_range} 仍有 {total} 条，"
            f"已达最小粒度，仅抓取前 1000 条[/yellow]"
        )
        for item in first_items:
            repo = _parse_repo(item)
            results[repo["full_name"]] = repo
        for page in range(2, 11):
            _, items = _search_once(client, query, page=page)
            stats["requests"] = stats.get("requests", 0) + 1
            for item in items:
                repo = _parse_repo(item)
                results[repo["full_name"]] = repo
            if len(items) < _PER_PAGE:
                break
        return

    # 区间二分
    mid = start + timedelta(days=(end - start).days // 2)
    console.print(
        f"{indent}[cyan]⤷ 二分 {date_range}  total={total:,}[/cyan]"
        f"  → [{start}..{mid}]  [{mid + timedelta(days=1)}..{end}]"
    )
    _fetch_slice(client, query_base, start, mid, results, depth + 1, stats)
    _fetch_slice(
        client, query_base,
        mid + timedelta(days=1), end,
        results, depth + 1, stats,
    )


# ── 公开接口 ───────────────────────────────────────────────────────────────

def fetch_all_repos_above_1k() -> dict[str, dict[str, Any]]:
    """
    抓取当前 GitHub 上 **全部** stars >= 1000 的仓库。

    策略：遍历主流编程语言（含"无语言"），对每种语言以
    「创建时间区间自适应二分」绕开 Search API 1000 条上限。

    Returns
    -------
    dict[full_name, repo_info]
    """
    results: dict[str, dict[str, Any]] = {}
    today = date.today()
    headers = _build_headers()
    global_stats: dict[str, int] = {"requests": 0}

    # 语言列表 + 无语言占位
    all_langs: list[str | None] = [*LANGUAGES, None]  # None 表示 language 未设置

    with httpx.Client(base_url=_BASE_URL, headers=headers, timeout=30) as client:
        for lang in all_langs:
            if lang is LANGUAGE_NONE_SENTINEL or lang is None:
                lang_label = "(no language)"
                lang_clause = "language:Unknown"  # GitHub 用此查 no-language
            else:
                lang_label = lang
                lang_clause = f"language:{lang}"

            query_base = f"stars:>=1000 {lang_clause}"
            console.rule(f"[bold blue]{lang_label}[/bold blue]")

            before = len(results)
            slice_stats: dict[str, int] = {"requests": 0}
            _fetch_slice(
                client,
                query_base,
                start=_EARLIEST_DATE,
                end=today,
                results=results,
                stats=slice_stats,
            )
            added = len(results) - before
            global_stats["requests"] += slice_stats.get("requests", 0)
            console.print(
                f"  [green]{lang_label}[/green] 新增 {added} 条，"
                f"累计 {len(results)} 条  "
                f"（本语言请求 {slice_stats.get('requests', 0)} 次）"
            )

    console.print(
        f"\n[bold green]✅ 全部语言扫描完毕：{len(results):,} 个 stars>=1000 仓库，"
        f"共发出 {global_stats['requests']} 次 API 请求[/bold green]"
    )
    return results
