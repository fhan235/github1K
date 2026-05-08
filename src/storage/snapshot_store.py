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


def build_created_since_suffix(created_since: date | None = None) -> str:
    """生成用于快照/报告/日志文件名的创建日期范围后缀。"""
    return f"_created-since-{created_since.isoformat()}" if created_since else ""


def _snapshot_stem(d: date, created_since: date | None = None) -> str:
    return f"snapshot_{d.isoformat()}{build_created_since_suffix(created_since)}"


def _candidate_paths(d: date, created_since: date | None = None) -> list[Path]:
    """按优先级返回两种可能的快照路径。"""
    stem = _snapshot_stem(d, created_since)
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


def load_snapshot(d: date, created_since: date | None = None) -> DailySnapshot:
    """加载某天的快照，找不到则返回空快照。"""
    for path in _candidate_paths(d, created_since):
        if not path.exists():
            continue
        try:
            data = _read_snapshot_file(path)
            return DailySnapshot(**data)
        except Exception as exc:
            console.print(f"[yellow]⚠️  读取快照 {path.name} 失败: {exc}[/yellow]")
            return DailySnapshot(date=d.isoformat())

    console.print(f"[dim]快照文件不存在: {_snapshot_stem(d, created_since)}.*[/dim]")
    return DailySnapshot(date=d.isoformat())


def save_snapshot(d: date, repos: dict[str, Any], created_since: date | None = None) -> Path:
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
    path = _DATA_DIR / f"{_snapshot_stem(d, created_since)}{_SUFFIX_PLAIN}"

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


def _parse_snapshot_name(path: Path) -> tuple[date, date | None] | None:
    """从快照文件名解析运行日期和 created_since 范围。"""
    stem = path.name
    for suffix in (_SUFFIX_GZ, _SUFFIX_PLAIN):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    if not stem.startswith("snapshot_"):
        return None

    rest = stem.removeprefix("snapshot_")
    date_part, sep, created_part = rest.partition("_created-since-")
    try:
        snapshot_date = date.fromisoformat(date_part)
        created_since = date.fromisoformat(created_part) if sep else None
    except ValueError:
        return None
    return snapshot_date, created_since


def _iter_snapshot_entries() -> list[tuple[date, date | None]]:
    """扫描 data/ 目录，返回所有已存在快照的日期和创建日期范围。"""
    if not _DATA_DIR.exists():
        return []
    entries: set[tuple[date, date | None]] = set()
    for pattern in ("snapshot_*.json", "snapshot_*.json.gz"):
        for path in _DATA_DIR.glob(pattern):
            parsed = _parse_snapshot_name(path)
            if parsed is not None:
                entries.add(parsed)
    return sorted(entries, key=lambda item: (item[0], item[1] or date.min))


def _iter_snapshot_dates() -> list[date]:
    """扫描 data/ 目录，返回所有已存在快照的日期（升序）。"""
    return sorted({snapshot_date for snapshot_date, _ in _iter_snapshot_entries()})


def _choose_default_created_since(before: date) -> date | None:
    """未指定范围时，选择历史快照中覆盖最广的 created_since。"""
    candidates = [
        created_since
        for snapshot_date, created_since in _iter_snapshot_entries()
        if snapshot_date < before
    ]
    if not candidates:
        return None
    if None in candidates:
        return None
    return min(candidates)


def find_latest_snapshot_date(
    before: date | None = None,
    created_since: date | None = None,
) -> date | None:
    """找到早于 ``before`` 的最近一次快照日期（不含 before 当天）。

    ``created_since`` 为 ``None`` 时，自动使用历史快照中覆盖最广的范围；
    例如同时存在 2020-01-01 和 2022-01-01 两组快照时，默认选择 2020-01-01。
    """
    cutoff = before or date.today()
    effective_created_since = (
        _choose_default_created_since(cutoff)
        if created_since is None
        else created_since
    )
    candidates = [
        d
        for d, entry_created_since in _iter_snapshot_entries()
        if d < cutoff and entry_created_since == effective_created_since
    ]
    return candidates[-1] if candidates else None


def load_latest_stars(
    before: date | None = None,
    created_since: date | None = None,
) -> tuple[date | None, dict[str, int]]:
    """加载最近一次历史快照的 ``{full_name: star_count}``。

    Returns
    -------
    (snapshot_date, stars)
        若无任何历史快照，返回 ``(None, {})``。
    """
    cutoff = before or date.today()
    effective_created_since = (
        _choose_default_created_since(cutoff)
        if created_since is None
        else created_since
    )
    latest = find_latest_snapshot_date(cutoff, effective_created_since)
    if latest is None:
        return None, {}
    return latest, load_snapshot(latest, effective_created_since).repos


def cleanup_old_snapshots(keep_days: int = 30) -> None:
    """删除超过 keep_days 天的快照文件（.json 和 .json.gz 都清）。"""
    if not _DATA_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=keep_days)
    deleted = 0
    for pattern in ("snapshot_*.json", "snapshot_*.json.gz"):
        for path in _DATA_DIR.glob(pattern):
            parsed = _parse_snapshot_name(path)
            if parsed is None:
                continue
            file_date, _ = parsed
            if file_date < cutoff:
                path.unlink()
                deleted += 1
    if deleted:
        console.print(
            f"[dim]🗑️  清理旧快照 {deleted} 个（保留最近 {keep_days} 天）[/dim]"
        )
