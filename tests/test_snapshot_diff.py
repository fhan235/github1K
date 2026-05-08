from __future__ import annotations

import json
from pathlib import Path

from src.utils.snapshot_diff import find_latest_snapshots


def _write_snapshot(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "date": "2026-05-08",
                "repos": {},
                "collected_at": "2026-05-08T00:00:00",
            }
        ),
        encoding="utf-8",
    )


def test_find_latest_snapshots_prefers_earliest_created_since_range(tmp_path: Path):
    _write_snapshot(tmp_path / "snapshot_2026-05-01_created-since-2020-01-01.json")
    _write_snapshot(tmp_path / "snapshot_2026-05-08_created-since-2020-01-01.json")
    _write_snapshot(tmp_path / "snapshot_2026-05-07_created-since-2022-01-01.json")
    _write_snapshot(tmp_path / "snapshot_2026-05-08_created-since-2022-01-01.json")

    newer, older = find_latest_snapshots(tmp_path)

    assert newer is not None
    assert older is not None
    assert newer.name == "snapshot_2026-05-08_created-since-2020-01-01.json"
    assert older.name == "snapshot_2026-05-01_created-since-2020-01-01.json"
