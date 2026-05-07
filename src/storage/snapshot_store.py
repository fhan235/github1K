"""快照存储模块。

每天将 stars>=1000 的仓库以 {full_name: star_count} 形式
持久化到 data/snapshot_YYYY-MM-DD.json(.gz)，保留最近 N 天。

为节省空间支持两项优化
---------------------
1. 紧凑 JSON：``settings.snapshot_compact = True`` 时不做缩进（体积减半）
2. 可选 gzip：文件名以 ``.json.gz`` 结尾会自动压缩（体积缩到 10-20%）
"""
from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console

from src.config import settings
from src.models import DailySnapshot

console = Console()

_DATA_DIR = Path(__file__).parent.parent.parent / "data"

# 支持两种后缀：优先查找 .json.gz（节省空间），fallback 到 .json
_SUFFIX_GZ = ".json.gz"
_SUFFIX_PLAIN = ".json"


def _candidate_paths(d: date) -> list[Path]:
    """按优先级返回两种可能的快照路径。"""
    stem = f"snapshot_{d.isoformat()}"
    return [_DATA_DIR / (stem + _SUFFIX_GZ), _DATA_DIR / (stem + _SUFFIX_PLAIN)]


def _read_snapshot_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_snapshot_file(path: Path, payload: dict[str, Any]) -> None:
    indent = None if settings.snapshot_compact else 2
    separators = (",", ":") if settings.snapshot_compact else (", ", ": ")

    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(
                payload, f, ensure_ascii=False, indent=indent, separators=separators
            )
    else:
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                payload, f, ensure_ascii=False, indent=indent, separators=separators
            )


def load_snapshot(d: date) -> DailySnapshot:
    """加载某天的快照，找不到则返回空快照。"""
    for path in _candidate_paths(d):
        if not path.exists():
            continue
        try:
            data = _read_snapshot_file(path)
            return DailySnapshot(**data)
        except Exception as exc:
            console.print(f"[yellow]⚠️  读取快照 {path.name} 失败: {exc}[/yellow]")
            return DailySnapshot(date=d.isoformat())

    console.print(f"[dim]快照文件不存在: snapshot_{d.isoformat()}.*[/dim]")
    return DailySnapshot(date=d.isoformat())


def save_snapshot(d: date, repos: dict[str, Any]) -> Path:
    """
    保存当天快照。

    Parameters
    ----------
    d :
        日期。
    repos :
        爬虫返回的 ``{full_name -> repo_info}``，自动提取 ``stars`` 字段。

    Returns
    -------
    Path
        写入的文件路径。
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 固定使用 .json 后缀（避免 Git 二进制 diff 困扰）。
    # 如需要 gzip 压缩可以手动切换后缀为 .json.gz。
    path = _DATA_DIR / f"snapshot_{d.isoformat()}{_SUFFIX_PLAIN}"

    snapshot = DailySnapshot(
        date=d.isoformat(),
        repos={name: info["stars"] for name, info in repos.items()},
        collected_at=datetime.now().isoformat(timespec="seconds"),
    )
    _write_snapshot_file(path, snapshot.model_dump())

    size_kb = path.stat().st_size / 1024
    console.print(
        f"[green]💾 快照已保存: {path.name}"
        f"（{len(snapshot.repos):,} 条, {size_kb:.0f} KB）[/green]"
    )
    return path


def has_yesterday_snapshot() -> bool:
    """检查昨天的快照文件是否存在（支持 .json 和 .json.gz）。"""
    yesterday = date.today() - timedelta(days=1)
    return any(p.exists() for p in _candidate_paths(yesterday))


def get_yesterday_stars() -> dict[str, int]:
    """返回昨天快照的 {full_name: star_count}，无记录则返回空字典。"""
    yesterday = date.today() - timedelta(days=1)
    return load_snapshot(yesterday).repos


def cleanup_old_snapshots(keep_days: int = 30) -> None:
    """删除超过 keep_days 天的快照文件（.json 和 .json.gz 都清）。"""
    if not _DATA_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=keep_days)
    deleted = 0
    for pattern in ("snapshot_*.json", "snapshot_*.json.gz"):
        for path in _DATA_DIR.glob(pattern):
            # 从文件名提取日期
            stem = path.name
            for suffix in (_SUFFIX_GZ, _SUFFIX_PLAIN):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            date_part = stem.removeprefix("snapshot_")
            try:
                file_date = date.fromisoformat(date_part)
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink()
                deleted += 1
    if deleted:
        console.print(
            f"[dim]🗑️  清理旧快照 {deleted} 个（保留最近 {keep_days} 天）[/dim]"
        )
