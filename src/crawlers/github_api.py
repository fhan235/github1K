"""GitHub Search API 爬虫 —— 边界区快速扫描 + 全量冷启动。

=======================================================================
为什么旧方案（全量扫描 10 万+ 个 stars>=1000 仓库）很慢？
=======================================================================
- GitHub Search API 限速：认证后 30 次/分钟
- stars>=1000 的仓库约 10 万+，需上千次请求 → 30-60 分钟
- 但 99%+ 的仓库（star 几千/几万/几十万）根本不可能跌到 1000 以下再涨回来
- 每天真正跨越 1000 门槛的项目只有个位数到几十个

=======================================================================
新方案：边界区快速扫描
=======================================================================
核心思想：只扫"1000 附近"的仓库，不扫全量。

每日运行两步：

【Step A — 突破区扫描】 stars:1000..{UPPER_BOUND}
  覆盖"今天刚到 1000 ~ 今天最多涨到 UPPER_BOUND" 的仓库。
  UPPER_BOUND 默认 50000（GitHub 单日增长极少超过这个数）。
  扫完后与昨天快照做差分：
    - 昨天 <1000（或不存在） 且 今天 >=1000 → 突破项目 ✅
    - 昨天已 >=1000 → 跳过
  这一步结果数远小于全量（通常几千条），API 请求量大幅减少。

【Step B — 候选区扫描】 stars:{LOWER_BOUND}..999
  覆盖"离 1000 还差一点"的仓库，为明天做准备。
  LOWER_BOUND 默认 800（离 1000 差 200 以上的项目一天内冲过去的概率极低）。
  扫完后存入今天快照中，明天就能与之对比。

合并 A + B 的结果作为今日快照保存。

=======================================================================
首次冷启动（无昨日快照）
=======================================================================
首次运行时昨日快照不存在。此时 Step A 扫到的项目全都会被标记为
"is_new_to_snapshot"（无法区分昨天就有 1000 还是今天才达到），
这是预期行为——**第二天开始**差分结果就准确了。

用户可以选择 --cold-start 执行一次更大范围的全量扫描来建立更完整
的基线快照（但这次跑得慢，之后每天就快了）。

=======================================================================
速度估算
=======================================================================
- Step A  stars:1000..50000  约 5000-8000 个仓库
  语言切分后每个切片通常 <1000 条，大部分语言 1 次请求就够
  估计 50-100 次请求 → 2-4 分钟

- Step B  stars:800..999     约 1000-3000 个仓库
  大部分语言 1 次请求就够
  估计 30-60 次请求 → 1-2 分钟

合计：**3-6 分钟**（相比旧方案 30-60 分钟，提速 10 倍）

=======================================================================
Step C — 爆款补漏（stars > UPPER_BOUND）
=======================================================================
问题：一个项目（如 OpenClaw）一天从 0 暴涨到 6 万 Star，
超出突破区上限 50000，Step A 抓不到。

解决：全 GitHub stars > 50000 的仓库只有 ~200-300 个，
3 次 API 请求即可全部拿完。扫一遍看哪些不在昨天快照里，
不在的就是爆款新项目。代价：约 5 秒，几乎免费。
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import httpx
from rich.console import Console

from src.config import settings
from src.crawlers.languages import LANGUAGES

console = Console()

_BASE_URL = "https://api.github.com"
_SEARCH_ENDPOINT = "/search/repositories"

# ── 核心参数 ──────────────────────────────────────────────────────────
_EARLIEST_DATE = date(2008, 1, 1)    # GitHub 创立年，全量扫描时的起始日期
_PER_PAGE = 100                       # Search API 每页最大条数
_MAX_RECURSION_DEPTH = 64             # 二分递归深度安全上限
_REQUEST_INTERVAL = 1.2               # 秒，30次/分钟的礼貌间隔

# ── 边界区参数 ────────────────────────────────────────────────────────
_ABOVE_UPPER = 50000      # 突破区上限：一天涨 5 万 star 已属极端
_CANDIDATE_LOWER = 800    # 候选区下限：离 1000 差 200+，一天冲过去概率极低


# ══════════════════════════════════════════════════════════════════════
# HTTP 工具
# ══════════════════════════════════════════════════════════════════════

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
    """执行一次 Search API 请求，返回 (total_count, items)。"""
    params = {
        "q": query,
        "sort": "stars",
        "order": "asc",
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
        retry_after = int(resp.headers.get("retry-after", "60"))
        console.print(f"[yellow]⚠️  403 次级限速，等待 {retry_after}s ...[/yellow]")
        time.sleep(retry_after + 3)
        resp = client.get(_SEARCH_ENDPOINT, params=params)

    if resp.status_code != 200:
        console.print(f"[red]HTTP {resp.status_code}: {resp.text[:200]}[/red]")
        return 0, []

    data = resp.json()
    return data.get("total_count", 0), data.get("items", [])


# ══════════════════════════════════════════════════════════════════════
# 自适应递归二分（保留，供 language 切分后仍超 1000 条时使用）
# ══════════════════════════════════════════════════════════════════════

def _fetch_slice(
    client: httpx.Client,
    query_base: str,
    start: date,
    end: date,
    results: dict[str, dict[str, Any]],
    depth: int = 0,
    stats: dict[str, int] | None = None,
) -> None:
    """递归拉取 [start, end] 区间内的仓库，自适应二分直到每片 <= 1000 条。"""
    if stats is None:
        stats = {}

    date_range = f"{start.isoformat()}..{end.isoformat()}"
    query = f"{query_base} created:{date_range}"

    total, first_items = _search_once(client, query, page=1)
    stats["requests"] = stats.get("requests", 0) + 1

    if total == 0:
        return

    if total <= 1000:
        # 能拿完，收集所有页
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
        return

    # total > 1000 → 二分
    if start == end or depth >= _MAX_RECURSION_DEPTH:
        console.print(
            f"[yellow]⚠️  {date_range} 仍有 {total} 条，"
            f"已达最小粒度，仅抓前 1000 条[/yellow]"
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

    mid = start + timedelta(days=(end - start).days // 2)
    console.print(
        f"[cyan]  ⤷ 二分 {date_range} total={total:,}[/cyan]"
    )
    _fetch_slice(client, query_base, start, mid, results, depth + 1, stats)
    _fetch_slice(
        client, query_base,
        mid + timedelta(days=1), end,
        results, depth + 1, stats,
    )


def _fetch_range_all_languages(
    client: httpx.Client,
    star_range: str,
    label: str,
    results: dict[str, dict[str, Any]],
    stats: dict[str, int],
) -> None:
    """
    在给定的 star 范围内，按语言切分 + 日期自适应二分，拉取全部仓库。

    Parameters
    ----------
    star_range : str
        例如 "stars:1000..50000" 或 "stars:800..999"
    label : str
        用于日志显示
    """
    today = date.today()
    # 语言列表 + 无语言
    all_langs: list[str | None] = [*LANGUAGES, None]

    for lang in all_langs:
        if lang is None:
            lang_label = "(no language)"
            lang_clause = ""  # 不加 language 限定，后面单独处理
        else:
            lang_label = lang
            lang_clause = f" language:{lang}"

        query_base = f"{star_range}{lang_clause}"

        # 先探一下总数，如果为 0 直接跳过（节省日志噪音）
        probe_total, _ = _search_once(client, query_base, page=1)
        stats["requests"] = stats.get("requests", 0) + 1

        if probe_total == 0:
            continue

        before = len(results)
        slice_stats: dict[str, int] = {"requests": 0}

        if probe_total <= 1000:
            # 不需要日期切分，直接翻页拿完
            # 但第一页已经在 probe 时拿了，这里重新走 _fetch_slice 简化逻辑
            _fetch_slice(
                client, query_base,
                start=_EARLIEST_DATE, end=today,
                results=results, stats=slice_stats,
            )
        else:
            # 需要日期切分
            console.print(
                f"  [cyan]{lang_label}[/cyan] {label}"
                f" total={probe_total:,} > 1000，启用日期二分"
            )
            _fetch_slice(
                client, query_base,
                start=_EARLIEST_DATE, end=today,
                results=results, stats=slice_stats,
            )

        added = len(results) - before
        stats["requests"] += slice_stats.get("requests", 0)
        if added > 0:
            console.print(
                f"  [green]{lang_label}[/green] +{added}  "
                f"累计 {len(results)}  "
                f"（{slice_stats.get('requests', 0)} 请求）"
            )


# ══════════════════════════════════════════════════════════════════════
# 公开接口
# ══════════════════════════════════════════════════════════════════════

def _fetch_viral_repos(
    client: httpx.Client,
    stats: dict[str, int],
) -> dict[str, dict[str, Any]]:
    """
    爆款补漏：抓取 stars > UPPER_BOUND 的全部仓库。

    全 GitHub stars > 50000 的仓库只有约 200-300 个，
    不需要语言切分或日期二分，直接翻页即可拿完（最多 3 页）。
    """
    results: dict[str, dict[str, Any]] = {}
    query = f"stars:>{_ABOVE_UPPER}"

    console.rule(f"[bold blue]Step C / 爆款补漏 stars:>{_ABOVE_UPPER}[/bold blue]")

    for page in range(1, 11):  # 最多 10 页（1000条），实际 ~3 页就够了
        total, items = _search_once(client, query, page=page)
        stats["requests"] = stats.get("requests", 0) + 1

        if not items:
            break

        for item in items:
            repo = _parse_repo(item)
            results[repo["full_name"]] = repo

        if len(items) < _PER_PAGE:
            break

    console.print(
        f"[green]  爆款补漏完成：{len(results):,} 个超高星仓库[/green]"
    )
    return results


def fetch_boundary_repos() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """
    边界区快速扫描（日常模式）。

    Returns
    -------
    (above_repos, candidate_repos)
        above_repos:     stars >= 1000 的仓库（突破区 + 爆款补漏，用于差分）
        candidate_repos: stars LOWER..999 的仓库（存入今日快照，为明天差分做准备）
    """
    above: dict[str, dict[str, Any]] = {}
    candidates: dict[str, dict[str, Any]] = {}
    headers = _build_headers()
    stats: dict[str, int] = {"requests": 0}

    with httpx.Client(base_url=_BASE_URL, headers=headers, timeout=30) as client:
        # ── Step A: 突破区 stars:1000..50000 ──────────────────────
        console.rule(f"[bold blue]Step A / 突破区 stars:1000..{_ABOVE_UPPER}[/bold blue]")
        _fetch_range_all_languages(
            client,
            star_range=f"stars:1000..{_ABOVE_UPPER}",
            label="突破区",
            results=above,
            stats=stats,
        )
        console.print(
            f"[green]  突破区完成：{len(above):,} 个仓库[/green]"
        )

        # ── Step B: 候选区 stars:800..999 ─────────────────────────
        console.rule(
            f"[bold blue]Step B / 候选区 stars:{_CANDIDATE_LOWER}..999[/bold blue]"
        )
        _fetch_range_all_languages(
            client,
            star_range=f"stars:{_CANDIDATE_LOWER}..999",
            label="候选区",
            results=candidates,
            stats=stats,
        )
        console.print(
            f"[green]  候选区完成：{len(candidates):,} 个仓库[/green]"
        )

        # ── Step C: 爆款补漏 stars:>50000 ─────────────────────────
        # 全 GitHub 只有 ~200-300 个，3 次请求即可拿完，约 5 秒
        # 覆盖 OpenClaw 这类一夜暴涨到超高星的现象级项目
        viral = _fetch_viral_repos(client, stats)
        above.update(viral)  # 合并到突破区，一起参与差分

    console.print(
        f"\n[bold green]✅ 边界区扫描完毕："
        f"突破区 {len(above):,}（含爆款补漏）"
        f" + 候选区 {len(candidates):,} = "
        f"{len(above) + len(candidates):,} 个仓库，"
        f"共 {stats['requests']} 次 API 请求[/bold green]"
    )
    return above, candidates


def fetch_all_repos_above_1k() -> dict[str, dict[str, Any]]:
    """
    全量扫描 stars>=1000（冷启动模式，仅首次或 --cold-start 时使用）。

    使用语言 × 日期自适应二分，完整覆盖所有 stars>=1000 的仓库。
    速度较慢（30-60 分钟），但建立的快照最完整。
    """
    results: dict[str, dict[str, Any]] = {}
    headers = _build_headers()
    stats: dict[str, int] = {"requests": 0}

    console.rule("[bold red]全量扫描 stars:>=1000（冷启动模式，耗时较长）[/bold red]")

    with httpx.Client(base_url=_BASE_URL, headers=headers, timeout=30) as client:
        _fetch_range_all_languages(
            client,
            star_range="stars:>=1000",
            label="全量",
            results=results,
            stats=stats,
        )

    console.print(
        f"\n[bold green]✅ 全量扫描完毕：{len(results):,} 个仓库，"
        f"共 {stats['requests']} 次 API 请求[/bold green]"
    )
    return results
