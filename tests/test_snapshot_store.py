"""snapshot_store 的单元测试。"""
from __future__ import annotations

import gzip
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.storage import snapshot_store as ss


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(ss, "_DATA_DIR", tmp_path)
    return tmp_path


def _repo(stars: int) -> dict:
    return {"stars": stars}


def test_save_and_load_plain_json(tmp_data_dir: Path):
    d = date(2026, 1, 15)
    ss.save_snapshot(d, {"a/b": _repo(1234), "c/d": _repo(2000)})

    loaded = ss.load_snapshot(d)
    assert loaded.date == "2026-01-15"
    assert loaded.repos == {"a/b": 1234, "c/d": 2000}


def test_load_gz_snapshot(tmp_data_dir: Path):
    """手动放一个 .json.gz 文件，确认能正确读取。"""
    d = date(2026, 2, 1)
    payload = {
        "date": d.isoformat(),
        "repos": {"x/y": 777},
        "collected_at": "2026-02-01T00:00:00",
    }
    gz_path = tmp_data_dir / f"snapshot_{d.isoformat()}.json.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)

    loaded = ss.load_snapshot(d)
    assert loaded.repos == {"x/y": 777}


def test_has_yesterday_snapshot(tmp_data_dir: Path, monkeypatch):
    yesterday = date.today() - timedelta(days=1)
    assert ss.has_yesterday_snapshot() is False

    ss.save_snapshot(yesterday, {"a/b": _repo(1000)})
    assert ss.has_yesterday_snapshot() is True


def test_cleanup_removes_old_snapshots(tmp_data_dir: Path):
    today = date.today()
    old = today - timedelta(days=40)
    recent = today - timedelta(days=5)

    ss.save_snapshot(old, {"a/b": _repo(100)})
    ss.save_snapshot(recent, {"c/d": _repo(200)})

    ss.cleanup_old_snapshots(keep_days=30)

    remaining = sorted(p.name for p in tmp_data_dir.glob("snapshot_*"))
    assert any(recent.isoformat() in name for name in remaining)
    assert not any(old.isoformat() in name for name in remaining)


def test_cleanup_handles_malformed_filename(tmp_data_dir: Path):
    """文件名非日期格式时不抛错。"""
    bad = tmp_data_dir / "snapshot_not-a-date.json"
    bad.write_text("{}")
    # 不应该抛异常
    ss.cleanup_old_snapshots(keep_days=30)
    assert bad.exists()  # 格式错误的不删


def test_load_missing_returns_empty(tmp_data_dir: Path):
    loaded = ss.load_snapshot(date(2020, 1, 1))
    assert loaded.repos == {}
