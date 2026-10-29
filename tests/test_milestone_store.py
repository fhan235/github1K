"""milestone_store 落盘/读取与 weekly.source 转换层的单元测试。"""
from __future__ import annotations

from datetime import date

import pytest

from src.models import Milestone1KRepo
from src.storage import milestone_store
from src.weekly.source import milestones_to_entries


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """把 data/daily 指到临时目录，避免污染真实数据。"""
    monkeypatch.setattr(milestone_store, "_DATA_DIR", tmp_path / "daily")


def _repo(**kw) -> Milestone1KRepo:
    defaults = dict(
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description="A cool project",
        language="Python",
        stars_today=1500,
        stars_yesterday=900,
        stars_gained=600,
        gain_reliable=True,
        forks=10,
        topics=["python"],
        created_at="2024-01-01T00:00:00Z",
        is_fork=False,
        is_archived=False,
    )
    defaults.update(kw)
    return Milestone1KRepo(**defaults)


def test_save_and_load_roundtrip():
    d = date(2026, 10, 21)
    baseline = date(2026, 10, 20)
    repos = [_repo(), _repo(full_name="a/b", stars_gained=None, unknown_yesterday=True)]
    path = milestone_store.save_milestones(d, repos, baseline, date(2020, 1, 1))
    assert path.name == "milestones_2026-10-21_created-since-2020-01-01.json.gz"

    loaded = milestone_store.load_milestones(d, date(2020, 1, 1))
    assert loaded is not None
    assert loaded.date == "2026-10-21"
    assert loaded.baseline_date == "2026-10-20"
    assert loaded.created_since == "2020-01-01"
    assert len(loaded.repos) == 2
    assert loaded.repos[0].gain_reliable is True
    assert loaded.repos[1].stars_gained is None


def test_load_missing_returns_none():
    assert milestone_store.load_milestones(date(2026, 1, 1), None) is None


def test_load_fallback_to_unsuffixed():
    """传入 created_since 时也能读到无后缀的历史文件。"""
    d = date(2026, 5, 9)
    milestone_store.save_milestones(d, [_repo()], None, None)
    loaded = milestone_store.load_milestones(d, date(2020, 1, 1))
    assert loaded is not None
    assert loaded.repos[0].full_name == "owner/repo"


def test_milestones_to_entries_conversion():
    d = date(2026, 10, 21)
    baseline = date(2026, 10, 20)
    repos = [
        _repo(full_name="ok/one", stars_gained=600, gain_reliable=True),
        _repo(
            full_name="new/two",
            stars_gained=None,
            gain_reliable=False,
            unknown_yesterday=True,
            is_recently_created=True,
        ),
    ]
    milestone_store.save_milestones(d, repos, baseline, None)
    ms = milestone_store.load_milestones(d, None)
    entries = milestones_to_entries(ms, d)

    assert len(entries) == 2
    ok = next(e for e in entries if e.full_name == "ok/one")
    assert ok.gained == 600
    assert ok.gain_reliable  # 基准恰好是前一天
    assert ok.baseline_date == baseline

    new = next(e for e in entries if e.full_name == "new/two")
    assert new.gained == 0  # 伪增量被清零
    assert new.unknown_yesterday is True
    assert not new.gain_reliable
    assert new.is_recently_created is True
