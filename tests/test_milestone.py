"""find_milestone_repos 的单元测试。"""
from __future__ import annotations

from datetime import date, timedelta

from src.main import find_milestone_repos


def _make_repo(stars: int, created_days_ago: int = 365) -> dict:
    created = (date.today() - timedelta(days=created_days_ago)).isoformat()
    return {
        "url": "https://github.com/owner/repo",
        "description": "",
        "language": "Python",
        "stars": stars,
        "forks": 0,
        "topics": [],
        "created_at": created + "T00:00:00Z",
        "updated_at": created + "T00:00:00Z",
    }


def test_breakthrough_from_below_1000():
    """昨天 <1000、今天 >=1000：应命中。"""
    today_repos = {"a/b": _make_repo(1200)}
    yesterday_stars = {"a/b": 900}

    result = find_milestone_repos(today_repos, yesterday_stars)
    assert len(result) == 1
    assert result[0].full_name == "a/b"
    assert result[0].stars_today == 1200
    assert result[0].stars_yesterday == 900
    assert result[0].stars_gained == 300
    assert result[0].unknown_yesterday is False


def test_already_above_1000_yesterday_is_skipped():
    """昨天已 >=1000：不算突破，跳过。"""
    today_repos = {"a/b": _make_repo(1500)}
    yesterday_stars = {"a/b": 1100}
    assert find_milestone_repos(today_repos, yesterday_stars) == []


def test_unknown_yesterday_flag():
    """昨天快照中不存在：标记 unknown_yesterday，增量为 None（伪增量）。"""
    today_repos = {"a/b": _make_repo(1100)}
    yesterday_stars = {}
    result = find_milestone_repos(today_repos, yesterday_stars)
    assert len(result) == 1
    assert result[0].unknown_yesterday is True
    assert result[0].stars_yesterday == 0
    assert result[0].stars_gained is None
    assert result[0].gain_reliable is False


def test_gain_reliable_only_when_baseline_is_yesterday():
    """基准恰好是前一天 → gain_reliable；断跑回退多日 → 不可信。"""
    today = date(2026, 10, 21)
    yesterday = date(2026, 10, 20)
    today_repos = {"a/b": _make_repo(1500)}
    yesterday_stars = {"a/b": 900}

    r1 = find_milestone_repos(today_repos, yesterday_stars, today, baseline_date=yesterday)
    assert r1[0].stars_gained == 600
    assert r1[0].gain_reliable is True

    r2 = find_milestone_repos(
        today_repos, yesterday_stars, today, baseline_date=date(2026, 10, 19)
    )
    assert r2[0].stars_gained == 600  # 多日累计增量仍展示
    assert r2[0].gain_reliable is False  # 但标记为不可信

    r3 = find_milestone_repos(today_repos, yesterday_stars, today, baseline_date=None)
    assert r3[0].gain_reliable is False


def test_recently_created_flag():
    """近 30 天内创建的视为新项目。"""
    today_repos = {
        "new/repo": _make_repo(1100, created_days_ago=5),
        "old/repo": _make_repo(1100, created_days_ago=500),
    }
    yesterday_stars = {}
    result = find_milestone_repos(today_repos, yesterday_stars)
    by_name = {r.full_name: r for r in result}
    assert by_name["new/repo"].is_recently_created is True
    assert by_name["old/repo"].is_recently_created is False


def test_sort_by_stars_desc():
    today_repos = {
        "low/one": _make_repo(1100),
        "mid/two": _make_repo(2500),
        "high/three": _make_repo(5000),
    }
    yesterday_stars = {"low/one": 900, "mid/two": 900, "high/three": 900}
    result = find_milestone_repos(today_repos, yesterday_stars)
    assert [r.full_name for r in result] == ["high/three", "mid/two", "low/one"]


def test_below_1000_today_is_skipped():
    """今天 <1000：不算突破。"""
    today_repos = {"a/b": _make_repo(999)}
    yesterday_stars = {}
    assert find_milestone_repos(today_repos, yesterday_stars) == []
