"""周榜流水线 CLI。

用法
----
```bash
# 默认：统计「昨天往前 7 天」，产出 Top 30，带 LLM 介绍
python -m src.weekly.main

# 免费调试：跳过 LLM，只看规则打分选出什么
python -m src.weekly.main --dry-run

# 指定窗口 / ISO 周
python -m src.weekly.main --start 2026-10-12 --end 2026-10-18
python -m src.weekly.main --week 2026-W42

# 推送企业微信
python -m src.weekly.main --notify
```

流程
----
1. 从 COS（本地兜底）拉取一周内每日完整报告并解析
2. 跨天去重聚合 → 规则预过滤（合集/存量巨型老项目）
3. REST 复查最新元数据，算出真实周涨幅
4. 可信度闸门 + 多因子打分
5. LLM 粗筛（打标签/判垃圾）→ 多样性筛选出 Top N
6. LLM 逐个生成结构化介绍（带缓存）
7. 渲染周报 md + 结构化 json，更新 seen.json
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from src.config import settings
from src.utils.timezone import today_bjt
from src.weekly.aggregate import aggregate, shortlist
from src.weekly.enrich import (
    enrich_candidates,
    fetch_readme,
    make_readme_client,
)
from src.weekly.llm import LLMClient, generate_intro, triage_candidates
from src.weekly.models import ProjectIntro, ScoredCandidate
from src.weekly.publish import upload_report
from src.weekly.reporter import (
    load_seen,
    render_weekly_html,
    render_weekly_md,
    save_seen,
    save_weekly_html,
    save_weekly_outputs,
)
from src.weekly.score import score_all, select_final
from src.weekly.source import fetch_daily_entries

console = Console()
logger = logging.getLogger("github1k.weekly")


def _parse_week(value: str) -> tuple[date, date]:
    """解析 ISO 周（如 2026-W42）为 (周一, 周日)。"""
    try:
        year_part, week_part = value.upper().split("-W")
        monday = date.fromisocalendar(int(year_part), int(week_part), 1)
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError(
            f"--week 必须是 ISO 周格式，例如 2026-W42，收到: {value}"
        ) from exc
    return monday, monday + timedelta(days=6)


def _resolve_window(args: argparse.Namespace) -> tuple[date, date]:
    if args.week:
        return _parse_week(args.week)
    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        if end < start:
            raise argparse.ArgumentTypeError("--end 不能早于 --start")
        return start, end
    end = today_bjt() - timedelta(days=1)
    return end - timedelta(days=6), end


def _notify_wecom(
    finalists: list[ScoredCandidate],
    md_path: Path,
    end: date,
    report_url: str | None = None,
) -> None:
    """推送一条精简的周报完成通知。"""
    webhook = settings.wecom_webhook_url.strip()
    if not webhook:
        console.print("[yellow]⚠️  未配置 G1K_WECOM_WEBHOOK_URL，跳过推送[/yellow]")
        return
    top3 = "\n".join(
        f"> {i}. [{c.full_name}]({c.url}) 周涨 {c.weekly_gain or 0:,}"
        for i, c in enumerate(finalists[:3], 1)
    )
    if report_url:
        read_line = f"👉 [点击阅读完整周报]({report_url})"
    else:
        read_line = f"周报文件：`{md_path.name}`（已提交仓库）"
    content = (
        f"## 📅 GitHub 破千周榜已生成\n"
        f"> 截至 {end.isoformat()}，精选 Top {len(finalists)}\n\n"
        f"**本周前三**\n{top3}\n\n"
        f"{read_line}"
    )
    try:
        resp = httpx.post(
            webhook,
            json={"msgtype": "markdown", "markdown": {"content": content}},
            timeout=15,
        )
        if resp.status_code == 200:
            console.print("[green]📨 企业微信已推送[/green]")
        else:
            console.print(f"[yellow]⚠️  企微推送失败: HTTP {resp.status_code}[/yellow]")
    except httpx.RequestError as exc:
        console.print(f"[yellow]⚠️  企微推送网络错误: {exc}[/yellow]")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GitHub 破千周榜：聚合一周日榜，复查打分，LLM 生成项目介绍",
    )
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="窗口起始日期")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="窗口结束日期")
    parser.add_argument("--week", metavar="YYYY-Www", help="ISO 周，例如 2026-W42")
    parser.add_argument(
        "--top", type=int, default=settings.weekly_top_n,
        help=f"最终入榜数量（默认 {settings.weekly_top_n}）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="不调 LLM，只跑聚合+复查+打分（免费调试规则用）",
    )
    parser.add_argument(
        "--no-enrich", action="store_true", help="跳过 REST 复查（离线调试）"
    )
    parser.add_argument(
        "--no-triage", action="store_true", help="跳过 LLM 粗筛（仍生成介绍）"
    )
    parser.add_argument(
        "--include-seen", action="store_true", help="允许历史已上榜项目再次入榜"
    )
    parser.add_argument("--notify", action="store_true", help="推送企业微信通知")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        start, end = _resolve_window(args)
    except (argparse.ArgumentTypeError, ValueError) as exc:
        parser.error(str(exc))

    console.rule(f"[bold cyan]📅 破千周榜 {start} → {end}[/bold cyan]")

    # ── Step 1: 拉取一周日榜 ──────────────────────────────────────
    console.rule("[bold]Step 1 / 拉取每日完整报告（COS 优先）[/bold]")
    created_since = (
        date.fromisoformat(settings.created_since) if settings.created_since else None
    )
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    entries_by_date, missing_days = fetch_daily_entries(days, created_since)
    console.print(f"  覆盖 {len(entries_by_date)}/{len(days)} 天")
    if missing_days:
        console.print(
            f"  [yellow]⚠️  缺失 {len(missing_days)} 天: "
            f"{', '.join(d.isoformat() for d in missing_days)}[/yellow]"
        )
    if not entries_by_date:
        console.print("[red]❌ 本周没有任何可用报告，终止[/red]")
        return 1

    # ── Step 2: 聚合 + 预过滤 ────────────────────────────────────
    console.rule("[bold]Step 2 / 跨天聚合 + 规则预过滤[/bold]")
    candidates = aggregate(entries_by_date)
    shortlisted, dropped = shortlist(candidates, settings.weekly_enrich_limit)
    console.print(
        f"  去重后 {len(candidates)} 个 → 预过滤保留 {len(shortlisted)} 个"
        f"（过滤 {len(dropped)} 个合集/存量老项目）"
    )
    if not shortlisted:
        console.print("[red]❌ 预过滤后没有候选，终止[/red]")
        return 1

    # ── Step 3: REST 复查 ────────────────────────────────────────
    if args.no_enrich:
        console.rule("[bold]Step 3 / REST 复查（已跳过）[/bold]")
        from src.weekly.models import EnrichedCandidate

        enriched = [EnrichedCandidate(**c.model_dump()) for c in shortlisted]
    else:
        console.rule(f"[bold]Step 3 / REST 复查（{len(shortlisted)} 项）[/bold]")
        enriched = enrich_candidates(shortlisted)
        ok = sum(1 for e in enriched if e.enrich_ok)
        growing = sum(
            1 for e in enriched if e.weekly_gain is not None and e.weekly_gain > 0
        )
        console.print(f"  复查成功 {ok}/{len(enriched)}，一周后仍在涨 {growing} 个")

    # ── Step 4: 打分 ─────────────────────────────────────────────
    console.rule("[bold]Step 4 / 可信度闸门 + 多因子打分[/bold]")
    scored = score_all(enriched, ref_date=end)
    suspicious = sum(
        1 for s in scored if any(f.startswith("suspected") for f in s.flags)
    )
    console.print(f"  打分完成，{suspicious} 个带风险标记")

    # ── Step 5: LLM 粗筛 ─────────────────────────────────────────
    llm_client: LLMClient | None = None
    if not args.dry_run:
        try:
            llm_client = LLMClient()
        except RuntimeError as exc:
            console.print(f"[yellow]⚠️  {exc}，降级为 dry-run[/yellow]")
            args.dry_run = True

    if llm_client is not None and not args.no_triage:
        console.rule("[bold]Step 5 / LLM 粗筛（打标签/判垃圾）[/bold]")
        triage_pool = scored[: min(len(scored), args.top * 2)]
        triage = triage_candidates(
            llm_client, settings.llm_model_triage, triage_pool
        )
        for c in scored:
            if c.full_name in triage:
                item = triage[c.full_name]
                c.category = item.category
                c.triage_quality = item.quality
                c.triage_reason = item.reason
        junk = sum(1 for t in triage.values() if t.quality == "junk")
        console.print(f"  粗筛完成 {len(triage)} 项，判 junk {junk} 项")

    # ── Step 6: 最终筛选 ─────────────────────────────────────────
    console.rule("[bold]Step 6 / 多样性筛选 + 历史去重[/bold]")
    seen_map = load_seen()
    finalists, continuing = select_final(
        scored, args.top, set(seen_map), include_seen=args.include_seen
    )
    console.print(
        f"  最终入榜 {len(finalists)} 个，持续走强 {len(continuing)} 个"
    )

    # ── Step 7: LLM 精写介绍 ─────────────────────────────────────
    intros: dict[str, ProjectIntro] = {}
    if llm_client is not None:
        console.rule(f"[bold]Step 7 / LLM 生成介绍（{len(finalists)} 项）[/bold]")
        with make_readme_client() as readme_client:
            for i, c in enumerate(finalists, 1):
                readme = fetch_readme(readme_client, c.full_name)
                intro = generate_intro(
                    llm_client, settings.llm_model_writer, c, readme
                )
                intros[c.full_name] = intro
                console.print(
                    f"  [{i}/{len(finalists)}] {c.full_name}: {intro.one_liner[:30]}"
                )

    # ── Step 8: 渲染 + 落盘 ──────────────────────────────────────
    console.rule("[bold]Step 8 / 生成周报[/bold]")
    md = render_weekly_md(
        finalists, intros, start, end,
        covered_days=sorted(entries_by_date),
        missing_days=missing_days,
        total_breakthroughs=len(candidates),
        continuing=continuing,
        dry_run=args.dry_run,
    )
    md_path, json_path = save_weekly_outputs(
        md, finalists, intros, continuing, start, end, missing_days
    )
    console.print(f"[green]📄 周报: {md_path}[/green]")
    console.print(f"[green]📦 结构化数据: {json_path}[/green]")

    # ── Step 9: 渲染 HTML + 上传 COS（企微里可读完整周报）─────────
    report_url: str | None = None
    html_text = render_weekly_html(md, title=f"GitHub 破千周榜 {start} → {end}")
    html_path = save_weekly_html(html_text, start, end)
    console.print(f"[green]🌐 HTML 页面: {html_path}[/green]")
    if not args.dry_run:
        report_url = upload_report(html_path)
        if report_url:
            console.print(f"[green]🔗 公开链接: {report_url}[/green]")
        else:
            console.print("[dim]未配置 COS 或上传失败，本次推送不带链接[/dim]")

    # dry-run 不更新 seen.json（避免污染历史名单）
    if not args.dry_run and finalists:
        iso = end.isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"
        for c in finalists:
            seen_map[c.full_name] = {
                "week": week_label,
                "date": end.isoformat(),
                "score": c.score,
            }
        save_seen(seen_map)
        console.print(f"[dim]seen.json 已更新（累计 {len(seen_map)} 个）[/dim]")

    if args.notify:
        _notify_wecom(finalists, md_path, end, report_url=report_url)

    # ── 终端预览 ─────────────────────────────────────────────────
    table = Table(
        title=f"🏆 周榜 Top {len(finalists)}",
        show_lines=False,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("仓库", style="cyan", max_width=38)
    table.add_column("评分", justify="right", style="yellow")
    table.add_column("周涨幅", justify="right", style="green")
    table.add_column("当前 ⭐", justify="right")
    table.add_column("类别", style="magenta")
    table.add_column("定位", max_width=32)
    for i, c in enumerate(finalists, 1):
        intro = intros.get(c.full_name)
        one_liner = intro.one_liner if intro else (c.description or "")[:30]
        table.add_row(
            str(i),
            c.full_name,
            f"{c.score:.1f}",
            f"+{c.weekly_gain:,}" if c.weekly_gain else "—",
            f"{c.current_stars:,}" if c.current_stars else "—",
            c.category,
            one_liner,
        )
    console.print(table)

    console.rule("[bold green]✅ 周榜完成[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
