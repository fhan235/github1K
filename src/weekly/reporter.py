"""周报渲染与落盘。"""
from __future__ import annotations

import html as _html
import json
from datetime import date
from pathlib import Path

import markdown as _md

from src.weekly.models import ProjectIntro, ScoredCandidate

_ROOT = Path(__file__).parent.parent.parent
_WEEKLY_REPORTS_DIR = _ROOT / "reports" / "weekly"
_WEEKLY_DATA_DIR = _ROOT / "data" / "weekly"

_CATEGORY_LABELS = {
    "ai-agent": "🤖 AI Agent",
    "ai-model": "🧠 AI 模型/推理",
    "dev-tools": "🛠️ 开发工具",
    "web-frontend": "🌐 Web 前端",
    "security": "🔒 安全隐私",
    "content-media": "🎨 内容创作",
    "data-finance": "📊 数据金融",
    "learning-resource": "📚 学习资源",
    "automation": "⚙️ 自动化",
    "desktop-system": "💻 桌面系统",
    "mobile": "📱 移动端",
    "game": "🎮 游戏",
    "hardware-iot": "🔌 硬件/IoT",
    "other": "📦 其他",
}


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, _CATEGORY_LABELS["other"])


def _medal(idx: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"#{idx}")


def _esc(s: str) -> str:
    """转义不可信文本（LLM 输出 / GitHub 描述），防止生成 HTML 时被注入标签。"""
    return _html.escape(s, quote=False)


def _fmt_num(n: int | None) -> str:
    return f"{n:,}" if n is not None else "—"


def _fmt_gain(n: int | None) -> str:
    if n is None:
        return "—"
    return f"+{n:,}" if n > 0 else f"{n:,}"


def _render_entry(
    idx: int, c: ScoredCandidate, intro: ProjectIntro | None
) -> list[str]:
    lines: list[str] = []
    cat = category_label(c.category)
    lines.append(f"### {_medal(idx)} [{c.full_name}]({c.url}) · {cat}")
    lines.append("")

    star_line = (
        f"⭐ 上榜时 **{_fmt_num(c.stars_at_breakthrough)}** → "
        f"周末复查 **{_fmt_num(c.current_stars)}**"
        f"（一周 {_fmt_gain(c.weekly_gain)}）"
    )
    meta: list[str] = []
    if c.language:
        meta.append(f"`{c.language}`")
    if c.license_spdx:
        meta.append(f"📜 {c.license_spdx}")
    if c.created_at:
        meta.append(f"📅 创建于 {c.created_at[:10]}")
    if meta:
        star_line += "  " + "  ".join(meta)
    lines.append(star_line)
    lines.append("")

    risk_flags = [f for f in c.flags if f.startswith("suspected")]
    if risk_flags or c.triage_quality == "suspicious":
        tags = "、".join(risk_flags)
        lines.append(f"> ⚠️ 数据风险标记：{tags}（解读时请留意）")
        lines.append("")

    if intro is None or intro.one_liner == "unknown":
        # dry-run 或 LLM 失败：退回原始描述
        if c.description:
            lines.append(f"> {_esc(c.description)}")
            lines.append("")
    else:
        lines.append(f"**{_esc(intro.one_liner)}**")
        lines.append("")
        lines.append(f"- **是什么**：{_esc(intro.what_it_is)}")
        lines.append(f"- **解决什么**：{_esc(intro.problem_solved)}")
        lines.append(f"- **谁该关注**：{_esc(intro.who_should_care)}")
        if intro.use_cases:
            cases = "；".join(_esc(u) for u in intro.use_cases[:3])
            lines.append(f"- **典型场景**：{cases}")
        if intro.alternatives != "unknown":
            lines.append(f"- **同类对比**：{_esc(intro.alternatives)}")
        judge: list[str] = []
        if intro.maturity != "unknown":
            judge.append(f"成熟度：{_esc(intro.maturity)}")
        if intro.hype_or_trend != "unknown":
            judge.append(_esc(intro.hype_or_trend))
        if judge:
            lines.append(f"- **判断**：{'；'.join(judge)}")
        if intro.risk_notes:
            lines.append(f"- **注意**：{_esc(intro.risk_notes)}")
        lines.append("")

    lines.append(
        f"<sub>评分 {c.score}（{json.dumps(c.score_parts, ensure_ascii=False)}）"
        f"· 上榜 {c.days_seen} 天</sub>"
    )
    lines.append("")
    return lines


def render_weekly_md(
    finalists: list[ScoredCandidate],
    intros: dict[str, ProjectIntro],
    start: date,
    end: date,
    covered_days: list[date],
    missing_days: list[date],
    total_breakthroughs: int,
    continuing: list[ScoredCandidate],
    dry_run: bool = False,
) -> str:
    """渲染周报 Markdown。"""
    lines: list[str] = []
    lines.append(f"# 📅 GitHub 破千周榜 | {start.isoformat()} → {end.isoformat()}")
    lines.append("")
    lines.append(
        f"> 本周共 **{total_breakthroughs}** 个项目突破 1000 Star，"
        f"精选 **{len(finalists)}** 个"
    )
    coverage = f"> 数据覆盖 {len(covered_days)}/{len(covered_days) + len(missing_days)} 天"
    if missing_days:
        missing_str = "、".join(d.isoformat() for d in missing_days)
        coverage += f"（缺：{missing_str}）"
    lines.append(coverage)
    if dry_run:
        lines.append("> ⚙️ 本次为 dry-run，未调用大模型，展示原始描述")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 类别分布
    cat_count: dict[str, int] = {}
    for c in finalists:
        cat_count[c.category] = cat_count.get(c.category, 0) + 1
    if any(k != "other" for k in cat_count):
        lines.append("## 🧭 本周赛道分布")
        lines.append("")
        dist = "  ".join(
            f"{category_label(k)} × {v}"
            for k, v in sorted(cat_count.items(), key=lambda x: -x[1])
        )
        lines.append(dist)
        lines.append("")
        lines.append("---")
        lines.append("")

    for idx, c in enumerate(finalists, start=1):
        lines.extend(_render_entry(idx, c, intros.get(c.full_name)))

    if continuing:
        lines.append("---")
        lines.append("")
        lines.append("## 📈 持续走强（往期上榜，本周仍在涨）")
        lines.append("")
        lines.append("| 项目 | 上榜时 ⭐ | 当前 ⭐ | 一周增量 |")
        lines.append("|------|----------:|--------:|---------:|")
        for c in continuing:
            lines.append(
                f"| [{c.full_name}]({c.url}) | {_fmt_num(c.stars_at_breakthrough)} "
                f"| {_fmt_num(c.current_stars)} | {_fmt_gain(c.weekly_gain)} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*项目介绍由大模型基于 GitHub 公开信息与 README 生成，"
        "可能存在偏差，请以项目主页为准。*"
    )
    lines.append(
        f"*由 [github1K](https://github.com/fhan235/github1K) 周榜流水线生成 · "
        f"{end.isoformat()}*"
    )
    return "\n".join(lines)


def save_weekly_outputs(
    md: str,
    finalists: list[ScoredCandidate],
    intros: dict[str, ProjectIntro],
    continuing: list[ScoredCandidate],
    start: date,
    end: date,
    missing_days: list[date],
) -> tuple[Path, Path]:
    """写入 reports/weekly/*.md 与 data/weekly/*.json，返回两者路径。"""
    stem = f"weekly-{start.isoformat()}_to_{end.isoformat()}"
    _WEEKLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _WEEKLY_DATA_DIR.mkdir(parents=True, exist_ok=True)

    md_path = _WEEKLY_REPORTS_DIR / f"{stem}.md"
    md_path.write_text(md, encoding="utf-8")

    payload = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "missing_days": [d.isoformat() for d in missing_days],
        "finalists": [
            {
                **c.model_dump(mode="json"),
                "intro": intros[c.full_name].model_dump(mode="json")
                if c.full_name in intros
                else None,
            }
            for c in finalists
        ],
        "continuing": [c.model_dump(mode="json") for c in continuing],
    }
    json_path = _WEEKLY_DATA_DIR / f"{stem}.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path, json_path


# ── HTML 渲染（自包含单文件，适合 COS 静态访问/手机阅读）────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; background: #f6f7f9; color: #1f2329;
  font-family: -apple-system, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
  line-height: 1.75; }}
main {{ max-width: 720px; margin: 0 auto; padding: 20px 16px 60px; }}
h1 {{ font-size: 1.5rem; border-bottom: 2px solid #e5e6eb; padding-bottom: 12px; }}
h2 {{ font-size: 1.2rem; margin-top: 32px; }}
h3 {{ font-size: 1.05rem; margin-top: 36px; }}
h3 a {{ color: #1f2329; text-decoration: none; }}
a {{ color: #2563eb; }}
blockquote {{ margin: 8px 0; padding: 4px 14px; color: #4e5969;
  border-left: 3px solid #c9cdd4; background: #fff; border-radius: 0 6px 6px 0; }}
code {{ background: #eef0f3; padding: 1px 6px; border-radius: 4px; font-size: .9em; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: .92rem; }}
th, td {{ border: 1px solid #e5e6eb; padding: 6px 10px; }}
sub {{ color: #86909c; }}
hr {{ border: none; border-top: 1px solid #e5e6eb; margin: 28px 0; }}
ul {{ padding-left: 1.2em; }}
</style>
</head>
<body><main>
{content}
</main></body>
</html>
"""


def render_weekly_html(md_text: str, title: str) -> str:
    """把周报 Markdown 渲染成自包含的 HTML 单文件（移动端友好）。"""
    body = _md.markdown(md_text, extensions=["tables", "fenced_code"])
    return _HTML_TEMPLATE.format(title=_html.escape(title), content=body)


def save_weekly_html(html_text: str, start: date, end: date) -> Path:
    """写入 reports/weekly/weekly-*.html（不提交仓库，仅用于上传 COS / 本地预览）。"""
    _WEEKLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _WEEKLY_REPORTS_DIR / f"weekly-{start.isoformat()}_to_{end.isoformat()}.html"
    path.write_text(html_text, encoding="utf-8")
    return path


def load_seen(path: Path | None = None) -> dict:
    """读取历史已上榜名单 {full_name: {week, date}}。"""
    p = path or (_WEEKLY_DATA_DIR / "seen.json")
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_seen(seen: dict, path: Path | None = None) -> Path:
    p = path or (_WEEKLY_DATA_DIR / "seen.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return p
