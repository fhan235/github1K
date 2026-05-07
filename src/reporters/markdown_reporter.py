"""Markdown 报告生成器。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from src.models import Milestone1KRepo

_REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"


def _stars_bar(n: int, max_n: int, width: int = 10) -> str:
    """生成一个简单的 Star 数量条形图（用于 Markdown）。"""
    if max_n == 0:
        filled = 0
    else:
        filled = round(n / max_n * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _format_medal(idx: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"#{idx}")


def _format_gained(n: int) -> str:
    return f"+{n:,}" if n > 0 else f"{n:,}"


def _tag(repo: Milestone1KRepo) -> str:
    """生成状态标签（新项目 / 昨日未追踪）。"""
    if repo.is_recently_created:
        return "  🆕 *新项目*"
    if repo.unknown_yesterday:
        return "  ❓ *昨日未追踪*"
    return ""


def generate_report(
    repos: list[Milestone1KRepo],
    run_date: date,
    yesterday: date,
    top_n: int = 0,
) -> str:
    """
    生成 Markdown 报告字符串。

    Parameters
    ----------
    repos :
        已按今日 Star 数降序排好的列表。
    run_date :
        本次运行的日期（通常是今天）。
    yesterday :
        昨天的日期。
    top_n :
        只展示前 N 条；0 表示全部展示。
    """
    display = repos[:top_n] if top_n > 0 else repos
    max_stars = display[0].stars_today if display else 1

    lines: list[str] = []

    # ── 标题 ──────────────────────────────────────────────────────
    lines.append(f"# 🚀 GitHub 1K 突破榜 | {run_date.isoformat()}")
    lines.append("")
    lines.append(
        f"> 统计区间：{yesterday.isoformat()} → {run_date.isoformat()}  "
    )
    lines.append(
        f"> 共发现 **{len(repos)}** 个项目在此期间突破 1000 Star"
        + (
            f"，展示 Top {top_n}"
            if top_n > 0 and top_n < len(repos)
            else "，全部展示"
        )
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 各仓库条目 ────────────────────────────────────────────────
    for idx, repo in enumerate(display, start=1):
        medal = _format_medal(idx)

        lines.append(f"### {medal} [{repo.full_name}]({repo.url})")

        gained_str = _format_gained(repo.stars_gained)
        lang_str = f"  `{repo.language}`" if repo.language else ""
        yday_display = (
            f"{repo.stars_yesterday:,}" if not repo.unknown_yesterday else "—"
        )
        lines.append(
            f"⭐ **{repo.stars_today:,}** 星  "
            f"（昨天 {yday_display}，增量 **{gained_str}**）"
            f"{lang_str}{_tag(repo)}"
        )

        bar = _stars_bar(repo.stars_today, max_stars)
        lines.append(f"`{bar}` {repo.stars_today:,} stars")

        if repo.description:
            lines.append(f"> {repo.description}")

        if repo.topics:
            topic_badges = " ".join(f"`{t}`" for t in repo.topics[:8])
            lines.append(f"🏷️ {topic_badges}")

        meta_parts: list[str] = []
        if repo.forks:
            meta_parts.append(f"🍴 {repo.forks:,} forks")
        if repo.created_at:
            meta_parts.append(f"📅 创建于 {repo.created_at[:10]}")
        if meta_parts:
            lines.append("  ".join(meta_parts))

        lines.append("")

    # ── 语言统计 ─────────────────────────────────────────────────
    lang_count: dict[str, int] = {}
    for repo in repos:
        key = repo.language or "Unknown"
        lang_count[key] = lang_count.get(key, 0) + 1
    sorted_langs = sorted(lang_count.items(), key=lambda x: -x[1])[:15]

    lines.append("---")
    lines.append("")
    lines.append("## 📊 语言分布")
    lines.append("")
    lines.append("| 语言 | 项目数 |")
    lines.append("|------|--------|")
    for lang, cnt in sorted_langs:
        lines.append(f"| {lang} | {cnt} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"*由 [github1K](https://github.com/fhan235/github1K) "
        f"自动生成 · {run_date.isoformat()}*"
    )

    return "\n".join(lines)


def save_report(content: str, run_date: date) -> Path:
    """将报告写入 reports/milestone-1k-YYYY-MM-DD.md 并返回路径。"""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORTS_DIR / f"milestone-1k-{run_date.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return path
