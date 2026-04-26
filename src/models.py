"""数据模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RepoSnapshot(BaseModel):
    """某仓库在某次快照时的 Star 数量（用于持久化）。"""

    full_name: str
    stars: int


class DailySnapshot(BaseModel):
    """某天的全量快照：{full_name -> star_count}。"""

    date: str  # "YYYY-MM-DD"
    repos: dict[str, int] = {}  # full_name -> star_count
    collected_at: str = ""


class Milestone1KRepo(BaseModel):
    """昨天 < 1000 Star、今天 >= 1000 Star 的仓库。"""

    full_name: str
    url: str
    description: str = ""
    language: Optional[str] = None
    stars_today: int
    """今天的 Star 数"""

    stars_yesterday: int
    """昨天快照中的 Star 数（若无记录则为 0）"""

    stars_gained: int
    """今天相对昨天的增量"""

    forks: int = 0
    topics: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_new_to_snapshot: bool = False
    """True = 昨天快照中根本没有这个仓库（新项目或之前被过滤掉）"""
