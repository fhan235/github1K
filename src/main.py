"""github1K 主流程。

两种运行模式
------------
1. 日常模式（默认）：
   只扫边界区（stars:1000..UPPER + stars:LOWER..999），约 3-6 分钟。
   与昨天快照差分找突破项目。

2. 冷启动模式（--cold-start）：
   全量扫 stars>=1000，建立完整基线快照。耗时较长，仅需运行一次。
   之后每天切回日常模式即可。

差分逻辑
--------
today_above（今天 stars:1000..UPPER 的仓库 + 爆款区）与昨天快照对比：
  - 昨天快照中 stars < 1000（或不存在） → 今天 >=1000 → 突破项目 ✅
  - 昨天快照中 stars >= 1000 → 跳过

今日快照 = today_above ∪ today_candidates（stars:LOWER..999）
  这样明天的差分就有基准了。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.config import settings
from src.crawlers.github_api import fetch_all_repos_above_1k, fetch_boundary_repos
from src.models import Milestone1KRepo
from src.notifiers.wecom import send_wecom
from src.reporters.markdown_reporter import generate_report, save_report
from src.storage.snapshot_store import (
    cleanup_old_snapshots,
    get_yesterday_stars,
    has_yesterday_snapshot,
    save_snapshot,
)

console = Console()
logger = logging.getLogger("github1k")

_RECENT_REPO_DAYS = 30  # 创建于近 N 天内的视为"新项目"


def _is_recently_created(created_at: str | None, ref_date: date) -> bool:
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    delta = (
        datetime.combine(ref_date, datetime.min.time(), tzinfo=timezone.utc)
        - created
    )
    return 0 <= delta.days <= _RECENT_REPO_DAYS


def find_milestone_repos(
    today_repos: dict,
    yesterday_stars: dict[str, int],
    today: date | None = None,
) -> list[Milestone1KRepo]:
    """
    差分：找出昨天 <1000、今天 >=1000 的仓库。

    Parameters
    ----------
    today_repos :
        stars >= 1000 的仓库字典。
    yesterday_stars :
        昨天快照中的 {full_name: star_count}。
    today :
        参考日期（用于判断是否新创建仓库）。默认今天。
    """
    ref_date = today or date.today()
    milestones: list[Milestone1KRepo] = []

    for full_name, info in today_repos.items():
        today_stars = info["stars"]
        if today_stars < 1000:
            continue

        yesterday_count = yesterday_stars.get(full_name, -1)

        if yesterday_count == -1:
            # 昨天快照中不存在
            unknown_yesterday = True
            stars_yday = 0
        elif yesterday_count < 1000:
            unknown_yesterday = False
            stars_yday = yesterday_count
        else:
            # 昨天已经 >=1000，跳过
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
                unknown_yesterday=unknown_yesterday,
                is_recently_created=_is_recently_created(
                    info.get("created_at"), ref_date
                ),
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
        gained = (
            f"+{repo.stars_gained:,}" if repo.stars_gained > 0 else str(repo.stars_gained)
        )
        table.add_row(
            str(idx),
            repo.full_name,
            f"{repo.stars_today:,}",
            f"{repo.stars_yesterday:,}" if not repo.unknown_yesterday else "—",
            gained,
            repo.language or "—",
            repo.description[:60] + ("…" if len(repo.description) > 60 else ""),
        )

    console.print(table)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="收集昨天突破 1000 Star 的 GitHub 项目",
    )
    parser.add_argument(
        "--cold-start",
        action="store_true",
        help="全量扫描 stars>=1000 建立基线快照（首次运行时使用，耗时较长）",
    )
    parser.add_argument(
        "--notify", action="store_true", help="推送企业微信通知"
    )
    parser.add_argument(
        "-n", "--top", type=int, default=30, help="终端展示前 N 条（默认 30）"
    )
    parser.add_argument(
        "--skip-save", action="store_true", help="跳过保存快照（调试用）"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="DEBUG 级别日志"
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    today = date.today()
    yesterday = today - timedelta(days=1)

    console.rule("[bold cyan]github1K — 1000 Star 突破追踪器[/bold cyan]")
    console.print(f"📅 运行日期: {today}  |  对比昨天: {yesterday}")
    console.print()

    # ── 判断运行模式 ──────────────────────────────────────────────
    has_yesterday = has_yesterday_snapshot()
    use_cold_start = args.cold_start or not has_yesterday

    if not has_yesterday and not args.cold_start:
        console.print(
            "[yellow]⚠️  未找到昨天的快照。首次运行将自动使用冷启动模式，"
            "建立基线快照。之后每天运行会自动切换为快速模式（3-6 分钟）。[/yellow]"
        )
        console.print()

    try:
        # ── Step 1: 加载昨天快照 ──────────────────────────────────
        console.rule("[bold]Step 1 / 加载昨天快照[/bold]")
        yesterday_stars = get_yesterday_stars()
        console.print(f"  昨天快照记录数: {len(yesterday_stars):,}")

        # ── Step 2: 抓取今天数据 ──────────────────────────────────
        if use_cold_start:
            console.rule("[bold]Step 2 / 冷启动：全量扫描 stars>=1000[/bold]")
            today_all = fetch_all_repos_above_1k()
            today_above = today_all
            today_candidates: dict = {}
        else:
            console.rule("[bold]Step 2 / 日常模式：边界区快速扫描[/bold]")
            today_above, today_candidates = fetch_boundary_repos()

        if not today_above:
            console.print(
                "[red]❌ 未抓取到任何今日仓库数据（可能 API 异常），终止。[/red]"
            )
            return 1

        # ── Step 3: 差分，找突破项目 ──────────────────────────────
        console.rule("[bold]Step 3 / 差分计算突破项目[/bold]")
        milestones = find_milestone_repos(today_above, yesterday_stars, today)
        console.print(
            f"[bold green]🎯 发现 {len(milestones)} 个项目在此期间突破 1000 Star[/bold green]"
        )

        # ── Step 4: 保存今天快照 ──────────────────────────────────
        if not args.skip_save:
            console.rule("[bold]Step 4 / 保存今天快照[/bold]")
            all_repos = {**today_above, **today_candidates}
            save_snapshot(today, all_repos)

        # ── Step 5: 生成报告 ──────────────────────────────────────
        console.rule("[bold]Step 5 / 生成 Markdown 报告[/bold]")
        report_top_n = settings.report_top_n
        content = generate_report(milestones, today, yesterday, top_n=report_top_n)
        report_path = save_report(content, today)
        console.print(f"[green]📄 报告已生成: {report_path}[/green]")

        # ── Step 6: 推送通知（可选）──────────────────────────────
        if args.notify:
            console.rule("[bold]Step 6 / 推送企业微信[/bold]")
            send_wecom(milestones, today)

        # ── Step 7: 清理旧快照 ────────────────────────────────────
        console.rule("[bold]Step 7 / 清理旧快照[/bold]")
        cleanup_old_snapshots(keep_days=settings.snapshot_keep_days)

        # ── Step 8: 终端展示 ──────────────────────────────────────
        console.rule("[bold]结果预览[/bold]")
        _print_table(milestones, top_n=args.top)

        mode_str = "冷启动（全量）" if use_cold_start else "日常（边界区快速扫描）"
        console.rule(f"[bold green]✅ 完成 · 模式: {mode_str}[/bold green]")
        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  用户中断[/yellow]")
        return 130
    except Exception as exc:
        logger.exception("运行失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
