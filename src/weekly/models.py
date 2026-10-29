"""周榜数据模型。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class DailyEntry(BaseModel):
    """从单日完整报告（milestone-1k-*.md）解析出的一条突破记录。"""

    full_name: str
    url: str
    description: str = ""
    language: str | None = None
    stars: int
    gained: int
    stars_yesterday: int | None = None
    unknown_yesterday: bool = False
    is_recently_created: bool = False
    forks: int = 0
    topics: list[str] = Field(default_factory=list)
    created_at: str | None = None
    report_date: date
    baseline_date: date | None = None
    """报告头部「统计区间」的起点（即对比基准快照日期）。"""

    @property
    def gain_reliable(self) -> bool:
        """增量是否可信：昨日已被追踪，且对比基准恰好是前一天。

        ``unknown_yesterday=True`` 时 gained = stars - 0，是伪增量；
        基准日期不是前一天（比如断跑后回退）时，gained 是多日累计，
        不能当作「单日爆发」使用。
        """
        if self.unknown_yesterday or self.baseline_date is None:
            return False
        return (self.report_date - self.baseline_date).days == 1


class WeeklyCandidate(BaseModel):
    """一周内同一项目多条日榜记录去重合并后的候选。"""

    full_name: str
    url: str
    description: str = ""
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    created_at: str | None = None
    forks_at_breakthrough: int = 0

    stars_at_breakthrough: int
    """上榜期间的最高 star（来自日榜条目）。"""

    stars_at_first_seen: int
    """首次上榜当天的 star，用于计算一周真实涨幅。"""

    best_gained: int = 0
    """所有可信条目中的最大单日增量（无可信条目时为 0）。"""

    gain_reliable: bool = False
    best_unknown_yesterday: bool = False
    """最高星那条记录是否 unknown_yesterday（伪增量嫌疑）。"""

    first_seen: date
    last_seen: date
    days_seen: int = 1

    flags: list[str] = Field(default_factory=list)
    """预过滤阶段打上的标记，如 collection（合集/教程类）。"""


class EnrichedCandidate(WeeklyCandidate):
    """经过 REST 元数据复查后的候选。"""

    enrich_ok: bool = False
    current_stars: int | None = None
    current_forks: int | None = None
    pushed_at: str | None = None
    license_spdx: str | None = None
    archived: bool = False
    is_fork: bool = False
    open_issues: int | None = None

    weekly_gain: int | None = None
    """周末复查 star − 首次上榜 star：一周后是否还在涨的最硬信号。"""


class ScoredCandidate(EnrichedCandidate):
    """带打分明细的候选。"""

    score: float = 0.0
    score_parts: dict[str, float] = Field(default_factory=dict)
    category: str = "other"
    """LLM 粗筛打的类别标签（未启用 triage 时为 other）。"""
    triage_quality: str = "ok"
    """LLM 粗筛质量结论：ok / junk / suspicious。"""
    triage_reason: str = ""


class TriageItem(BaseModel):
    """LLM 粗筛对单个项目的结论。"""

    full_name: str
    category: str = "other"
    quality: str = "ok"  # ok / junk / suspicious
    reason: str = ""


class ProjectIntro(BaseModel):
    """LLM 产出的项目介绍（结构化，供多种渠道渲染）。"""

    one_liner: str = "unknown"
    """20 字内中文定位。"""
    what_it_is: str = "unknown"
    problem_solved: str = "unknown"
    who_should_care: str = "unknown"
    use_cases: list[str] = Field(default_factory=list)
    alternatives: str = "unknown"
    maturity: str = "unknown"
    """demo / 可试用 / 生产可用。"""
    hype_or_trend: str = "unknown"
    """短期热点 / 长期趋势 判断。"""
    risk_notes: str = ""
    evidence: list[str] = Field(default_factory=list)
    """支撑结论的 README 原句（防幻觉抽查用）。"""
