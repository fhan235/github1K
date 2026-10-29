"""weekly.reporter 渲染与安全转义的单元测试。"""
from __future__ import annotations

from datetime import date

from src.weekly.models import ProjectIntro, ScoredCandidate
from src.weekly.reporter import render_weekly_html, render_weekly_md

_START = date(2026, 10, 15)
_END = date(2026, 10, 21)


def _scored(**kw) -> ScoredCandidate:
    data = dict(
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description="A useful tool",
        language="Python",
        topics=["cli"],
        created_at="2026-10-01",
        stars_at_breakthrough=1200,
        stars_at_first_seen=1100,
        best_gained=500,
        gain_reliable=True,
        first_seen=_START,
        last_seen=_END,
        days_seen=2,
        current_stars=3000,
        weekly_gain=1900,
        score=88.0,
        score_parts={"growth": 30.0},
        category="dev-tools",
    )
    data.update(kw)
    return ScoredCandidate(**data)


def test_html_render_contains_content_and_style():
    md = render_weekly_md(
        [_scored()],
        {"owner/repo": ProjectIntro(one_liner="测试定位", what_it_is="一个工具")},
        _START, _END,
        covered_days=[_START, _END],
        missing_days=[],
        total_breakthroughs=10,
        continuing=[],
    )
    html = render_weekly_html(md, title="测试周报")
    assert html.startswith("<!DOCTYPE html>")
    assert "viewport" in html  # 移动端适配
    assert "owner/repo" in html
    assert "测试定位" in html
    assert "<style>" in html  # 自包含样式


def test_llm_output_is_escaped_in_html():
    """LLM 输出若夹带 HTML 标签，渲染后必须被转义（防 XSS）。"""
    evil = ProjectIntro(
        one_liner="<script>alert(1)</script>",
        what_it_is="<img src=x onerror=alert(2)>",
    )
    md = render_weekly_md(
        [_scored(description="<b>bold</b>")],
        {"owner/repo": evil},
        _START, _END,
        covered_days=[_END],
        missing_days=[],
        total_breakthroughs=1,
        continuing=[],
    )
    html = render_weekly_html(md, title="t")
    # 标签被转义为实体，浏览器不会将其解析为 HTML
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html


def test_dry_run_banner_and_coverage_note():
    md = render_weekly_md(
        [_scored()],
        {},
        _START, _END,
        covered_days=[_START],
        missing_days=[_END],
        total_breakthroughs=5,
        continuing=[],
        dry_run=True,
    )
    assert "dry-run" in md
    assert "覆盖 1/2 天" in md
    assert "缺：2026-10-21" in md
    assert "> A useful tool" in md  # 无 intro 时回退原始描述
