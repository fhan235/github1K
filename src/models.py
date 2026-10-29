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

    stars_gained: int | None = None
    """相对对比基准的增量。``unknown_yesterday`` 时为 None —— 因为
    「昨天不存在」无法推出真实增量，stars - 0 是伪增量。"""

    gain_reliable: bool = False
    """增量是否可信：昨天已被追踪，且对比基准恰好是前一天。
    断跑后基准回退多日时，gained 是多日累计，此标记为 False。"""

    forks: int = 0
    topics: list[str] = []
    created_at: str | None = None
    updated_at: str | None = None

    is_fork: bool = False
    is_archived: bool = False

    unknown_yesterday: bool = False
    """True = 昨天快照中根本没有这个仓库（可能是新项目，也可能昨天 star 数
    低于追踪窗口 candidate_lower）。"""

    is_recently_created: bool = False
    """True = 仓库创建时间在最近 30 天内，可视为真正的"新项目"。"""


class DailyMilestones(BaseModel):
    """某天的全量突破项目清单（结构化持久化，供周榜等下游消费）。"""

    date: str  # "YYYY-MM-DD"
    baseline_date: str | None = None
    """本次差分的对比基准快照日期（断跑回退时会早于此前一天）。"""
    created_since: str | None = None
    repos: list[Milestone1KRepo] = []
