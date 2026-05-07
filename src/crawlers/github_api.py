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
  LOWER_BOUND 默认 500（离 1000 差 500 以上的项目一天内冲过去的概率极低）。
  扫完后存入今天快照中，明天就能与之对比。

合并 A + B 的结果作为今日快照保存。

=======================================================================
Step C — 爆款补漏（stars > UPPER_BOUND）
=======================================================================
问题：一个项目一天从 0 暴涨到 6 万 Star，超出突破区上限，Step A 抓不到。
解决：全 GitHub stars > 50000 的仓库只有 ~200-300 个，翻几页即可。
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

import httpx
from rich.console import Console

from src.config import settings
from src.crawlers.languages import LANGUAGES

console = Console()
logger = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com"
_SEARCH_ENDPOINT = "/search/repositories"

# ── 核心参数（非配置项，属于 API 协议硬性约束）────────────────────────
_EARLIEST_DATE = date(2008, 1, 1)    # GitHub 创立年，全量扫描时的起始日期
_PER_PAGE = 100                       # Search API 每页最大条数
_MAX_PAGES_PER_QUERY = 10             # Search API 单查询最多返回 1000 条 = 10 页
_MAX_RECURSION_DEPTH = 64             # 二分递归深度安全上限

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
    """根据响应头的 x-ratelimit-* 动态等待，避免被 429/403 拦截。"""
    try:
        remaining = int(response.headers.get("x-ratelimit-remaining", "999"))
        reset_ts = int(response.headers.get("x-ratelimit-reset", "0"))
    except (TypeError, ValueError):
        return
    if remaining <= 2 and reset_ts:
        wait = max(reset_ts - int(time.time()), 0) + 5
        console.print(
            f"[yellow]⏳ 速率限制剩余 {remaining}，等待 {wait}s ...[/yellow]"
        )
        time.sleep(wait)


class SearchAPIError(Exception):
    """GitHub Search API 不可恢复错误（多次重试后仍失败）。"""


def _search_once(
    client: httpx.Client,
    query: str,
    page: int = 1,
    stats: dict[str, int] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """执行一次 Search API 请求，自带指数退避重试。

    失败超过 ``settings.http_max_retries`` 次后抛 ``SearchAPIError``，
    由调用方决定继续还是中止。
    """
    params = {
        "q": query,
        "sort": "stars",
        "order": "asc",
        "per_page": _PER_PAGE,
        "page": page,
    }
    max_retries = settings.http_max_retries
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        time.sleep(settings.request_interval)
        try:
            resp = client.get(_SEARCH_ENDPOINT, params=params)
        except httpx.RequestError as exc:
            last_exc = exc
            backoff = min(2 ** attempt, 30)
            console.print(
                f"[yellow]⚠️  网络错误（第 {attempt + 1}/{max_retries + 1} 次）: "
                f"{exc}，{backoff}s 后重试[/yellow]"
            )
            time.sleep(backoff)
            continue

        _wait_for_rate_limit(resp)

        if resp.status_code == 403:
            # 次级限速，按 Retry-After 等待后重试
            retry_after = int(resp.headers.get("retry-after", "60"))
            console.print(
                f"[yellow]⚠️  403 次级限速，等待 {retry_after}s ...[/yellow]"
            )
            time.sleep(retry_after + 3)
            continue

        if resp.status_code == 422:
            # 非法查询（通常是语法错误），无需重试
            console.print(
                f"[red]HTTP 422 无效查询: {query[:80]} → {resp.text[:200]}[/red]"
            )
            if stats is not None:
                stats["errors"] = stats.get("errors", 0) + 1
            return 0, []

        if resp.status_code in (500, 502, 503, 504):
            backoff = min(2 ** attempt, 30)
            console.print(
                f"[yellow]⚠️  HTTP {resp.status_code}（第 {attempt + 1} 次），"
                f"{backoff}s 后重试[/yellow]"
            )
            time.sleep(backoff)
            continue

        if resp.status_code != 200:
            console.print(
                f"[red]HTTP {resp.status_code}: {resp.text[:200]}[/red]"
            )
            if stats is not None:
                stats["errors"] = stats.get("errors", 0) + 1
            return 0, []

        try:
            data = resp.json()
        except ValueError as exc:
            last_exc = exc
            console.print("[yellow]⚠️  响应 JSON 解析失败，重试[/yellow]")
            continue

        return data.get("total_count", 0), data.get("items", [])

    # 所有重试均失败
    if stats is not None:
        stats["errors"] = stats.get("errors", 0) + 1
    raise SearchAPIError(
        f"Search API 请求失败超过 {max_retries} 次: query={query[:80]} "
        f"last_error={last_exc}"
    )


# ══════════════════════════════════════════════════════════════════════
# 自适应递归二分
# ══════════════════════════════════════════════════════════════════════


def _paginate(
    client: httpx.Client,
    query: str,
    first_items: list[dict[str, Any]],
    total: int,
    results: dict[str, dict[str, Any]],
    stats: dict[str, int],
) -> None:
    """已知 total<=1000 时，收集第一页后继续翻页到结束。"""
    for item in first_items:
        repo = _parse_repo(item)
        results[repo["full_name"]] = repo

    total_pages = min((total + _PER_PAGE - 1) // _PER_PAGE, _MAX_PAGES_PER_QUERY)
    for page in range(2, total_pages + 1):
        try:
            _, items = _search_once(client, query, page=page, stats=stats)
        except SearchAPIError as exc:
            console.print(f"[red]翻页失败（忽略该页，继续）: {exc}[/red]")
            break
        stats["requests"] = stats.get("requests", 0) + 1
        for item in items:
            repo = _parse_repo(item)
            results[repo["full_name"]] = repo
        if len(items) < _PER_PAGE:
            break


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

    try:
        total, first_items = _search_once(client, query, page=1, stats=stats)
    except SearchAPIError as exc:
        console.print(f"[red]切片抓取失败，跳过: {exc}[/red]")
        return
    stats["requests"] = stats.get("requests", 0) + 1

    if total == 0:
        return

    if total <= 1000:
        _paginate(client, query, first_items, total, results, stats)
        return

    # total > 1000 → 二分
    if start == end or depth >= _MAX_RECURSION_DEPTH:
        console.print(
            f"[yellow]⚠️  {date_range} 仍有 {total} 条，"
            f"已达最小粒度，仅抓前 1000 条[/yellow]"
        )
        stats["truncated"] = stats.get("truncated", 0) + 1
        _paginate(client, query, first_items, 1000, results, stats)
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
    """
    today = date.today()
    all_langs: list[str | None] = [*LANGUAGES, None]

    for lang in all_langs:
        if lang is None:
            lang_label = "(no language)"
            lang_clause = ""
        else:
            lang_label = lang
            lang_clause = f" language:{lang}"

        query_base = f"{star_range}{lang_clause}"

        # 探一下总数
        try:
            probe_total, _ = _search_once(client, query_base, page=1, stats=stats)
        except SearchAPIError as exc:
            console.print(f"[red]探测失败（跳过语言 {lang_label}）: {exc}[/red]")
            continue
        stats["requests"] = stats.get("requests", 0) + 1

        if probe_total == 0:
            continue

        before = len(results)
        slice_stats: dict[str, int] = {"requests": 0}

        if probe_total > 1000:
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
        stats["truncated"] = (
            stats.get("truncated", 0) + slice_stats.get("truncated", 0)
        )
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

    用翻页直到 ``total_count`` 耗尽（而不是写死页数），
    这样即使将来超高星仓库数量增长到 >1000 也能正确处理
    （若真超过 1000 则启用语言切分兜底，当前不会触发）。
    """
    results: dict[str, dict[str, Any]] = {}
    upper = settings.above_upper
    query = f"stars:>{upper}"

    console.rule(f"[bold blue]Step C / 爆款补漏 stars:>{upper}[/bold blue]")

    try:
        total, first_items = _search_once(client, query, page=1, stats=stats)
    except SearchAPIError as exc:
        console.print(f"[red]爆款补漏失败: {exc}[/red]")
        return results
    stats["requests"] = stats.get("requests", 0) + 1

    if total == 0:
        return results

    if total <= 1000:
        _paginate(client, query, first_items, total, results, stats)
    else:
        # 极罕见：超高星仓库超过 1000 个
        # 退化为按语言切分扫描
        console.print(
            f"[yellow]⚠️  stars:>{upper} 总数 {total:,} > 1000，启用语言切分[/yellow]"
        )
        _fetch_range_all_languages(
            client,
            star_range=query,
            label="爆款区",
            results=results,
            stats=stats,
        )

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
    stats: dict[str, int] = {"requests": 0, "errors": 0, "truncated": 0}

    upper = settings.above_upper
    lower = settings.candidate_lower

    with httpx.Client(
        base_url=_BASE_URL,
        headers=headers,
        timeout=settings.http_timeout,
    ) as client:
        # ── Step A: 突破区 stars:1000..upper ─────────────────────
        console.rule(
            f"[bold blue]Step A / 突破区 stars:1000..{upper}[/bold blue]"
        )
        _fetch_range_all_languages(
            client,
            star_range=f"stars:1000..{upper}",
            label="突破区",
            results=above,
            stats=stats,
        )
        console.print(
            f"[green]  突破区完成：{len(above):,} 个仓库[/green]"
        )

        # ── Step B: 候选区 stars:lower..999 ──────────────────────
        console.rule(
            f"[bold blue]Step B / 候选区 stars:{lower}..999[/bold blue]"
        )
        _fetch_range_all_languages(
            client,
            star_range=f"stars:{lower}..999",
            label="候选区",
            results=candidates,
            stats=stats,
        )
        console.print(
            f"[green]  候选区完成：{len(candidates):,} 个仓库[/green]"
        )

        # ── Step C: 爆款补漏 stars:>upper ────────────────────────
        viral = _fetch_viral_repos(client, stats)
        above.update(viral)

    _print_stats_summary(stats, above, candidates)
    return above, candidates


def fetch_all_repos_above_1k() -> dict[str, dict[str, Any]]:
    """
    全量扫描 stars>=1000（冷启动模式，仅首次或 --cold-start 时使用）。

    使用语言 × 日期自适应二分，完整覆盖所有 stars>=1000 的仓库。
    速度较慢（30-60 分钟），但建立的快照最完整。

    注意：会额外合并 ``_fetch_viral_repos()`` 的结果以确保超高星仓库
    不因日期二分在极端情况下被截断。
    """
    results: dict[str, dict[str, Any]] = {}
    headers = _build_headers()
    stats: dict[str, int] = {"requests": 0, "errors": 0, "truncated": 0}

    console.rule(
        "[bold red]全量扫描 stars:>=1000（冷启动模式，耗时较长）[/bold red]"
    )

    with httpx.Client(
        base_url=_BASE_URL,
        headers=headers,
        timeout=settings.http_timeout,
    ) as client:
        _fetch_range_all_languages(
            client,
            star_range="stars:>=1000",
            label="全量",
            results=results,
            stats=stats,
        )

        # 爆款补漏：确保超高星项目不被日期二分截断丢失
        viral = _fetch_viral_repos(client, stats)
        before = len(results)
        results.update(viral)
        added = len(results) - before
        if added > 0:
            console.print(
                f"[green]  爆款补漏新增 {added} 个超高星仓库[/green]"
            )

    _print_stats_summary(stats, results, {})
    return results


def _print_stats_summary(
    stats: dict[str, int],
    above: dict[str, Any],
    candidates: dict[str, Any],
) -> None:
    """统一的统计信息输出。"""
    errors = stats.get("errors", 0)
    truncated = stats.get("truncated", 0)
    err_str = f"，错误 {errors}" if errors else ""
    trunc_str = f"，截断 {truncated}" if truncated else ""
    total = len(above) + len(candidates)
    console.print(
        f"\n[bold green]✅ 扫描完毕："
        f"{len(above):,}"
        + (f" + {len(candidates):,}" if candidates else "")
        + f" = {total:,} 个仓库，"
        f"共 {stats['requests']} 次 API 请求{err_str}{trunc_str}[/bold green]"
    )
