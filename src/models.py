"""数据模型。"""
from __future__ import annotations

from pydantic import BaseModel


class RepoSnapshot(BaseModel):
    """某仓库在某次快照时的 Star 数量（用于持久化）。"""

    full_name: str
    stars: int


class DailySnapshot(BaseModel):
    """某天的全量快照：{full_name -> star_count}。"""

    date: str  # "YYYY-MM-DD"
    repos: dict[str, int] = {}
    collected_at: str = ""


class Milestone1KRepo(BaseModel):
    """昨天 < 1000 Star、今天 >= 1000 Star 的仓库。"""

    full_name: str
    url: str
    description: str = ""
    language: str | None = None

    stars_today: int
    """今天的 Star 数"""

    stars_yesterday: int
    """昨天快照中的 Star 数（若无记录则为 0）"""

    stars_gained: int
    """今天相对昨天的增量"""

    forks: int = 0
    topics: list[str] = []
    created_at: str | None = None
    updated_at: str | None = None

    unknown_yesterday: bool = False
    """True = 昨天快照中根本没有这个仓库（可能是新项目，也可能昨天 star 数
    低于追踪窗口 candidate_lower）。"""

    is_recently_created: bool = False
    """True = 仓库创建时间在最近 30 天内，可视为真正的"新项目"。"""
