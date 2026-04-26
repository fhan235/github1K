"""github1K 主流程。

执行逻辑
--------
1. 加载昨天快照（{full_name: star_count}）
2. 抓取今天 stars>=1000 的全量仓库
3. 差分：昨天 <1000（或不存在）且今天 >=1000 → 突破项目
4. 按今日 Star 数降序排列
5. 保存今天快照
6. 生成 Markdown 报告
7. （可选）推送企业微信
8. 清理旧快照
9. Rich 终端展示

差分的关键
----------
不限制搜索区间（不做 stars:900..1200）。
无论一个项目今天涨了多少，只要：
    yesterday_stars < 1000  AND  today_stars >= 1000
就纳入统计。
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from rich.console import Console
from rich.table import Table

from src.config import settings
from src.crawlers.github_api import fetch_all_repos_above_1k
from src.models import Milestone1KRepo
from src.notifiers.wecom import send_wecom
from src.reporters.markdown_reporter import generate_report, save_report
from src.storage.snapshot_store import (
    cleanup_old_snapshots,
    get_yesterday_stars,
    save_snapshot,
)

console = Console()


def find_milestone_repos(
    today_repos: dict,
    yesterday_stars: dict[str, int],
) -> list[Milestone1KRepo]:
    """
    差分：找出昨天 <1000、今天 >=1000 的仓库。

    Parameters
    ----------
    today_repos :
        ``fetch_all_repos_above_1k()`` 的返回值。
    yesterday_stars :
        昨天快照中的 {full_name: star_count}。

    Returns
    -------
    list[Milestone1KRepo]
        按今日 Star 数降序排列。
    """
    milestones: list[Milestone1KRepo] = []

    for full_name, info in today_repos.items():
        today_stars = info["stars"]
        if today_stars < 1000:
            # 理论上不应出现（搜索条件就是 >=1000），保险起见过滤掉
            continue

        yesterday_count = yesterday_stars.get(full_name, -1)

        if yesterday_count == -1:
            # 昨天快照中不存在该仓库
            # 两种可能：1. 昨天 <1000；2. 新项目（今天才创建）
            # 都应纳入，标记 is_new_to_snapshot=True
            is_new = True
            stars_yday = 0
        elif yesterday_count < 1000:
            # 昨天存在但 <1000 → 今天突破
            is_new = False
            stars_yday = yesterday_count
        else:
            # 昨天已经 >=1000，不是今天突破的，跳过
            continue

        gained = today_stars - stars_yday
        milestones.append(
            Milestone1KRepo(
                full_name=full_name,
                url=info["url"],
                description=info["description"],
                language=info["language"],
                stars_today=today_stars,
                stars_yesterday=stars_yday,
                stars_gained=gained,
                forks=info["forks"],
                topics=info["topics"],
                created_at=info["created_at"],
                updated_at=info["updated_at"],
                is_new_to_snapshot=is_new,
            )
        )

    milestones.sort(key=lambda r: r.stars_today, reverse=True)
    return milestones


def _print_table(repos: list[Milestone1KRepo], top_n: int = 30) -> None:
    display = repos[:top_n] if top_n > 0 else repos

    table = Table(
        title=f"🚀 GitHub 1K 突破榜（共 {len(repos)} 个，展示 {len(display)} 个）",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("仓库", style="cyan", min_width=30)
    table.add_column("今日 ⭐", justify="right", style="yellow")
    table.add_column("昨日 ⭐", justify="right", style="dim")
    table.add_column("增量", justify="right", style="green")
    table.add_column("语言", style="magenta")
    table.add_column("描述", max_width=50)

    for idx, repo in enumerate(display, start=1):
        gained = f"+{repo.stars_gained:,}" if repo.stars_gained > 0 else str(repo.stars_gained)
        table.add_row(
            str(idx),
            repo.full_name,
            f"{repo.stars_today:,}",
            f"{repo.stars_yesterday:,}" if not repo.is_new_to_snapshot else "—",
            gained,
            repo.language or "—",
            repo.description[:60] + ("…" if len(repo.description) > 60 else ""),
        )

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="收集昨天突破 1000 Star 的 GitHub 项目")
    parser.add_argument("--notify", action="store_true", help="推送企业微信通知")
    parser.add_argument("-n", "--top", type=int, default=30, help="终端展示前 N 条（默认 30）")
    parser.add_argument("--skip-save", action="store_true", help="跳过保存快照（调试用）")
    args = parser.parse_args()

    today = date.today()
    yesterday = today - timedelta(days=1)

    console.rule("[bold cyan]github1K — 1000 Star 突破追踪器[/bold cyan]")
    console.print(f"📅 运行日期: {today}  |  对比昨天: {yesterday}")
    console.print()

    # ── Step 1: 加载昨天快照 ──────────────────────────────────────
    console.rule("[bold]Step 1 / 加载昨天快照[/bold]")
    yesterday_stars = get_yesterday_stars()
    console.print(f"  昨天快照记录数: {len(yesterday_stars):,}")

    # ── Step 2: 抓取今天数据 ──────────────────────────────────────
    console.rule("[bold]Step 2 / 抓取今天 stars>=1000 的全量仓库[/bold]")
    today_repos = fetch_all_repos_above_1k()

    # ── Step 3: 差分，找突破项目 ──────────────────────────────────
    console.rule("[bold]Step 3 / 差分计算突破项目[/bold]")
    milestones = find_milestone_repos(today_repos, yesterday_stars)
    console.print(
        f"[bold green]🎯 发现 {len(milestones)} 个项目在此期间突破 1000 Star[/bold green]"
    )

    # ── Step 4: 保存今天快照 ──────────────────────────────────────
    if not args.skip_save:
        console.rule("[bold]Step 4 / 保存今天快照[/bold]")
        save_snapshot(today, today_repos)

    # ── Step 5: 生成报告 ──────────────────────────────────────────
    console.rule("[bold]Step 5 / 生成 Markdown 报告[/bold]")
    report_top_n = settings.report_top_n  # 0 = 全部
    content = generate_report(milestones, today, yesterday, top_n=report_top_n)
    report_path = save_report(content, today)
    console.print(f"[green]📄 报告已生成: {report_path}[/green]")

    # ── Step 6: 推送通知（可选）──────────────────────────────────
    if args.notify:
        console.rule("[bold]Step 6 / 推送企业微信[/bold]")
        send_wecom(milestones, today)

    # ── Step 7: 清理旧快照 ────────────────────────────────────────
    console.rule("[bold]Step 7 / 清理旧快照[/bold]")
    cleanup_old_snapshots(keep_days=30)

    # ── Step 8: 终端展示 ──────────────────────────────────────────
    console.rule("[bold]结果预览[/bold]")
    _print_table(milestones, top_n=args.top)

    console.rule("[bold green]✅ 完成[/bold green]")


if __name__ == "__main__":
    main()
