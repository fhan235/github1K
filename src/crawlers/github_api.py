"""GitHub Search API 爬虫。

核心策略
--------
用 GitHub Search API 查询 ``stars:>=1000``，分页拉取全部结果（最多 1000 条）。
将结果存为 {full_name -> star_count} 字典，供下游与昨天快照做差集。

为什么不限制搜索区间（如 stars:900..1200）？
  - 如果一个项目昨天有 500 Star，今天爆涨到 5000 Star，它在昨天快照中
    就是 <1000，今天是 >=1000，应当被收录。限制上限会漏掉这类项目。
  - 正确方法：无限制地抓 stars:>=1000 全量，再与昨天快照对比——
    昨天 <1000（或不存在） 且今天 >=1000 → 纳入结果。
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from rich.console import Console

from src.config import settings

console = Console()

_BASE_URL = "https://api.github.com"
_SEARCH_ENDPOINT = "/search/repositories"


def _build_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _parse_repo(item: dict[str, Any]) -> dict[str, Any]:
    """将 API 返回的 item 解析为扁平字典。"""
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


def _handle_rate_limit(response: httpx.Response) -> None:
    """检查速率限制，必要时休眠等待重置。"""
    remaining = int(response.headers.get("x-ratelimit-remaining", "999"))
    reset_ts = int(response.headers.get("x-ratelimit-reset", "0"))
    if remaining <= 2 and reset_ts:
        wait = max(reset_ts - int(time.time()), 0) + 3
        console.print(
            f"[yellow]⏳ GitHub API 速率限制剩余 {remaining}，等待 {wait}s ...[/yellow]"
        )
        time.sleep(wait)


def fetch_all_repos_above_1k() -> dict[str, dict[str, Any]]:
    """
    抓取当前 GitHub 上 stars >= 1000 的全部仓库（最多 1000 条）。

    返回
    ----
    dict[full_name, repo_info]
        full_name  -> {full_name, url, description, language, stars, forks,
                       topics, created_at, updated_at, is_fork, is_archived}
    """
    results: dict[str, dict[str, Any]] = {}
    headers = _build_headers()
    per_page = min(settings.per_page, 100)
    max_pages = min(settings.max_pages, 10)  # Search API 最多 1000 条

    # 按 stars 降序排列，这样越靠后的页面 stars 越少，
    # 也越接近 1000 边界，便于后续差分时覆盖所有刚跨越的项目。
    params: dict[str, Any] = {
        "q": "stars:>=1000",
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }

    with httpx.Client(base_url=_BASE_URL, headers=headers, timeout=30) as client:
        for page in range(1, max_pages + 1):
            params["page"] = page
            console.print(
                f"[cyan]📡 Search API 第 {page}/{max_pages} 页 (stars:>=1000) ...[/cyan]"
            )

            try:
                resp = client.get(_SEARCH_ENDPOINT, params=params)
            except httpx.RequestError as exc:
                console.print(f"[red]网络错误（第 {page} 页）: {exc}[/red]")
                break

            _handle_rate_limit(resp)

            if resp.status_code == 403:
                console.print("[red]403 Forbidden —— 速率限制，停止分页[/red]")
                break
            if resp.status_code == 422:
                # Search API 超出 1000 条限制时返回 422
                console.print("[yellow]⚠️  已达 Search API 1000 条上限，停止分页[/yellow]")
                break
            if resp.status_code != 200:
                console.print(
                    f"[red]HTTP {resp.status_code} —— 第 {page} 页，跳过[/red]"
                )
                break

            data = resp.json()
            items = data.get("items", [])
            if not items:
                console.print("[dim]第 {page} 页无数据，停止[/dim]")
                break

            for item in items:
                repo = _parse_repo(item)
                results[repo["full_name"]] = repo

            total_count = data.get("total_count", 0)
            console.print(
                f"  → 本页 {len(items)} 条，累计 {len(results)} 条"
                f"（API 总计约 {total_count:,} 条）"
            )

            # 如果本页已经是最后一页（item 数量 < per_page），无需继续
            if len(items) < per_page:
                break

            # 礼貌间隔，避免连续触发次级速率限制
            time.sleep(1)

    console.print(f"[green]✅ 共抓取 {len(results)} 个 stars>=1000 的仓库[/green]")
    return results
