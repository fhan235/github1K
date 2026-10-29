"""每日突破项目的结构化持久化。

日榜完整报告（Markdown）是给「人」看的；本模块把同一份数据以
``data/daily/milestones_YYYY-MM-DD[_created-since-*].json.gz`` 落盘，
给周榜等「机器」下游消费，避免下游再去解析 Markdown。

文件提交回仓库（体积 KB 级），并随日榜 CI 上传 COS，两条链路都可用。
"""
from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

from rich.console import Console

from src.models import DailyMilestones, Milestone1KRepo
from src.storage.snapshot_store import build_created_since_suffix

console = Console()

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "daily"


def milestones_filename(d: date, created_since: date | None = None) -> str:
    return f"milestones_{d.isoformat()}{build_created_since_suffix(created_since)}.json.gz"


def milestones_path(d: date, created_since: date | None = None) -> Path:
    return _DATA_DIR / milestones_filename(d, created_since)


def save_milestones(
    d: date,
    repos: list[Milestone1KRepo],
    baseline_date: date | None,
    created_since: date | None = None,
) -> Path:
    """把当天突破项目全量清单写入 data/daily/ 并返回路径。"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = DailyMilestones(
        date=d.isoformat(),
        baseline_date=baseline_date.isoformat() if baseline_date else None,
        created_since=created_since.isoformat() if created_since else None,
        repos=repos,
    )
    path = milestones_path(d, created_since)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(payload.model_dump_json())
    size_kb = path.stat().st_size / 1024
    console.print(
        f"[green]💾 结构化日榜已保存: {path.name}"
        f"（{len(repos):,} 条, {size_kb:.0f} KB）[/green]"
    )
    return path


def load_milestones(
    d: date, created_since: date | None = None
) -> DailyMilestones | None:
    """读取某天的结构化日榜；不存在返回 None。"""
    path = milestones_path(d, created_since)
    if not path.exists() and created_since is not None:
        # 兼容无后缀（早期未启用 created-since 的时期）
        alt = milestones_path(d, None)
        if alt.exists():
            path = alt
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return DailyMilestones(**json.load(f))
    except Exception as exc:
        console.print(f"[yellow]⚠️  读取结构化日榜 {path.name} 失败: {exc}[/yellow]")
        return None


def parse_milestones_payload(data: dict) -> DailyMilestones:
    """从 dict（例如 COS 拉回的 JSON）构造 DailyMilestones。"""
    return DailyMilestones(**data)
