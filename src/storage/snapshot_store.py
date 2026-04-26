"""快照存储模块。

每天将 stars>=1000 的全量仓库以 {full_name: star_count} 形式
持久化到 data/snapshot_YYYY-MM-DD.json，保留最近 30 天。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console

from src.models import DailySnapshot

console = Console()

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _snapshot_path(d: date) -> Path:
    return _DATA_DIR / f"snapshot_{d.isoformat()}.json"


def load_snapshot(d: date) -> DailySnapshot:
    """加载某天的快照，文件不存在则返回空快照。"""
    path = _snapshot_path(d)
    if not path.exists():
        console.print(f"[dim]快照文件不存在: {path.name}[/dim]")
        return DailySnapshot(date=d.isoformat())
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return DailySnapshot(**data)
    except Exception as exc:
        console.print(f"[yellow]⚠️  读取快照 {path.name} 失败: {exc}[/yellow]")
        return DailySnapshot(date=d.isoformat())


def save_snapshot(d: date, repos: dict[str, Any]) -> Path:
    """
    保存当天快照。

    Parameters
    ----------
    d :
        日期。
    repos :
        ``fetch_all_repos_above_1k()`` 返回的字典
        ``{full_name -> repo_info}``，自动提取 ``stars`` 字段。

    Returns
    -------
    Path
        写入的文件路径。
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(d)

    from datetime import datetime

    snapshot = DailySnapshot(
        date=d.isoformat(),
        repos={name: info["stars"] for name, info in repos.items()},
        collected_at=datetime.now().isoformat(),
    )
    with path.open("w", encoding="utf-8") as f:
        json.dump(snapshot.model_dump(), f, ensure_ascii=False, indent=2)

    console.print(f"[green]💾 快照已保存: {path.name}（{len(snapshot.repos)} 条）[/green]")
    return path


def has_yesterday_snapshot() -> bool:
    """检查昨天的快照文件是否存在。"""
    yesterday = date.today() - timedelta(days=1)
    return _snapshot_path(yesterday).exists()


def get_yesterday_stars() -> dict[str, int]:
    """返回昨天快照的 {full_name: star_count}，无记录则返回空字典。"""
    yesterday = date.today() - timedelta(days=1)
    snapshot = load_snapshot(yesterday)
    return snapshot.repos


def cleanup_old_snapshots(keep_days: int = 30) -> None:
    """删除超过 keep_days 天的快照文件。"""
    if not _DATA_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=keep_days)
    deleted = 0
    for path in _DATA_DIR.glob("snapshot_*.json"):
        try:
            file_date = date.fromisoformat(path.stem.removeprefix("snapshot_"))
            if file_date < cutoff:
                path.unlink()
                deleted += 1
        except ValueError:
            pass
    if deleted:
        console.print(f"[dim]🗑️  清理旧快照 {deleted} 个（保留最近 {keep_days} 天）[/dim]")
