"""markdown_reporter 的单元测试。"""
from __future__ import annotations

from datetime import date

from src.models import Milestone1KRepo
from src.reporters.markdown_reporter import _stars_bar, generate_report, generate_summary_report


def _repo(**kw) -> Milestone1KRepo:
    defaults = dict(
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description="A cool project",
        language="Python",
        stars_today=1500,
        stars_yesterday=900,
        stars_gained=600,
        forks=10,
        topics=["python", "cli"],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        unknown_yesterday=False,
        is_recently_created=False,
    )
    defaults.update(kw)
    return Milestone1KRepo(**defaults)


def test_stars_bar_boundaries():
    assert _stars_bar(0, 100) == "░" * 10
    assert _stars_bar(100, 100) == "█" * 10
    assert _stars_bar(50, 100) == "█" * 5 + "░" * 5
    # 除 0 保护
    assert _stars_bar(10, 0) == "░" * 10


def test_generate_report_basic():
    repos = [_repo()]
    content = generate_report(repos, date(2026, 5, 1), date(2026, 4, 30))
    assert "GitHub 1K 突破榜" in content
    assert "owner/repo" in content
    assert "1,500" in content
    assert "Python" in content


def test_report_shows_new_project_flag():
    repo = _repo(is_recently_created=True, unknown_yesterday=True)
    content = generate_report([repo], date(2026, 5, 1), date(2026, 4, 30))
    assert "🆕" in content
    # 新项目标签优先于"昨日未追踪"
    assert "新项目" in content


def test_report_shows_unknown_yesterday_flag():
    repo = _repo(is_recently_created=False, unknown_yesterday=True)
    content = generate_report([repo], date(2026, 5, 1), date(2026, 4, 30))
    assert "❓" in content
    assert "昨日未追踪" in content


def test_report_top_n_limits_display():
    repos = [_repo(full_name=f"o/r{i}", stars_today=2000 - i) for i in range(5)]
    content = generate_report(repos, date(2026, 5, 1), date(2026, 4, 30), top_n=2)
    assert "展示 Top 2" in content
    # 前 2 个展示
    assert "o/r0" in content
    assert "o/r1" in content
    # 但"语言分布"仍包含全部 5 个
    assert "| Python | 5 |" in content


def test_report_empty_repos():
    content = generate_report([], date(2026, 5, 1), date(2026, 4, 30))
    assert "共发现 **0**" in content


def test_generate_summary_report_includes_full_report_url_and_limits_top_n():
    repos = [_repo(full_name=f"o/r{i}", stars_today=2000 - i) for i in range(3)]
    content = generate_summary_report(
        repos,
        date(2026, 5, 1),
        date(2026, 4, 30),
        top_n=2,
        full_report_url="https://example.com/reports/full.md",
    )

    assert "GitHub 1K 突破摘要" in content
    assert "查看完整报告" in content
    assert "o/r0" in content
    assert "o/r1" in content
    assert "o/r2" not in content
