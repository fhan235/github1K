"""多因子打分与最终筛选。

设计原则
--------
- 只用「可信」的增长数据：伪增量（unknown_yesterday）不参与排名。
- 一周后的真实涨幅（weekly_gain）是权重最高的信号 —— 过滤一日游项目。
- 所有扣分项都会留下 flag，并随 JSON 产物落盘，方便人工复核
  「为什么是这几个，不是别的几个」。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

from src.weekly.models import EnrichedCandidate, ScoredCandidate

# ── 权重 ────────────────────────────────────────────────────────────────
_W_GROWTH = 35.0      # 真实周涨幅
_W_PERSIST = 25.0     # 持续性（多天上榜 / 一周后仍在涨）
_W_FRESH = 20.0       # 真新（创建时间）
_W_QUALITY = 20.0     # 工程质量信号

_FRESH_DAYS_FULL = 90   # 90 天内创建拿满分
_FRESH_DAYS_HALF = 365  # 一年内创建拿一半分

_OLD_REPO_STAR_PENALTY = 20000  # unknown_yesterday 且体量超过此值 → 疑似存量老项目
_FARM_MIN_STARS = 2000          # 刷星检测的体量门槛
_FARM_FORK_RATIO = 0.005        # fork/star 低于此比例 → 疑似刷星


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # 报告里的日期（2024-07-30）无时区，REST 的带时区，统一按 UTC 处理
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(value: str | None, ref: date) -> int | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    ref_dt = datetime.combine(ref, datetime.min.time(), tzinfo=timezone.utc)
    return max(0, (ref_dt - dt).days)


def score_candidate(c: EnrichedCandidate, ref_date: date) -> ScoredCandidate:
    """对单个候选打分（纯函数，便于测试）。返回 0-100 分。"""
    flags = list(c.flags)
    parts: dict[str, float] = {}

    # 硬过滤信号：归档 / fork / 已删除 —— 打分归零，由 selection 剔除
    dead = c.archived or c.is_fork or "repo_gone" in flags

    # ── 真实增长（35）────────────────────────────────────────────
    if c.weekly_gain is not None:
        gain = c.weekly_gain
    elif c.gain_reliable:
        gain = c.best_gained
    else:
        gain = 0
    growth = _W_GROWTH * min(1.0, math.log1p(max(gain, 0)) / math.log1p(5000))
    parts["growth"] = round(growth, 1)

    # ── 持续性（25）──────────────────────────────────────────────
    persist = 0.0
    if c.days_seen >= 2:
        persist += 10.0
    if c.weekly_gain is not None and c.weekly_gain > 0:
        persist += 15.0 * min(1.0, c.weekly_gain / 2000)
    parts["persistence"] = round(min(_W_PERSIST, persist), 1)

    # ── 真新（20）────────────────────────────────────────────────
    age = _age_days(c.created_at, c.first_seen)
    fresh = 0.0
    if age is not None:
        if age <= _FRESH_DAYS_FULL:
            fresh = _W_FRESH
        elif age <= _FRESH_DAYS_HALF:
            fresh = _W_FRESH / 2
    parts["freshness"] = round(fresh, 1)

    # ── 工程质量（20）────────────────────────────────────────────
    quality = 0.0
    if c.license_spdx:
        quality += 4.0
    if len(c.topics) >= 3:
        quality += 4.0
    if len(c.description.strip()) >= 20:
        quality += 4.0
    pushed_age = _age_days(c.pushed_at, ref_date)
    if pushed_age is not None and pushed_age <= 14:
        quality += 4.0
    if c.enrich_ok and c.current_stars and c.current_forks is not None and c.current_stars > 0:
        ratio = c.current_forks / c.current_stars
        if 0.01 <= ratio <= 0.3:
            quality += 4.0
    parts["quality"] = round(min(_W_QUALITY, quality), 1)

    # ── 扣分项 ───────────────────────────────────────────────────
    penalty = 0.0
    if c.best_unknown_yesterday and c.stars_at_breakthrough >= _OLD_REPO_STAR_PENALTY:
        penalty += 30.0
        flags.append("suspected_legacy")
    if not c.description.strip():
        penalty += 15.0
        flags.append("no_description")
    if (
        c.enrich_ok
        and c.current_stars
        and c.current_stars >= _FARM_MIN_STARS
        and c.current_forks is not None
        and c.current_forks / max(c.current_stars, 1) < _FARM_FORK_RATIO
    ):
        penalty += 25.0
        flags.append("suspected_star_farming")
    if not c.enrich_ok:
        penalty += 10.0
        flags.append("enrich_failed")
    if dead:
        penalty += 100.0
        flags.append("archived_or_fork")
    if penalty:
        parts["penalty"] = -round(penalty, 1)

    total = max(0.0, min(100.0, sum(v for v in parts.values())))
    data = c.model_dump()
    data["flags"] = flags
    return ScoredCandidate(
        **data,
        score=round(total, 1),
        score_parts=parts,
    )


def score_all(
    candidates: list[EnrichedCandidate],
    ref_date: date,
) -> list[ScoredCandidate]:
    """批量打分并按分数降序返回。"""
    scored = [score_candidate(c, ref_date) for c in candidates]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def select_final(
    scored: list[ScoredCandidate],
    top_n: int,
    seen: set[str],
    include_seen: bool = False,
) -> tuple[list[ScoredCandidate], list[ScoredCandidate]]:
    """从打分结果中选出最终入榜项目。

    规则：
    - 剔除 triage 判为 junk、归档/fork/已删除的项目
    - 同一 owner 只取分数最高的一个（多样性）
    - 上过历史周榜的项目不进主榜；若本周仍在涨（weekly_gain >= 500），
      进入「持续走强」附榜

    Returns
    -------
    (finalists, continuing)
    """
    finalists: list[ScoredCandidate] = []
    continuing: list[ScoredCandidate] = []
    owners: set[str] = set()

    for c in scored:
        if c.triage_quality == "junk":
            continue
        if "archived_or_fork" in c.flags or "repo_gone" in c.flags:
            continue

        if c.full_name in seen and not include_seen:
            if c.weekly_gain is not None and c.weekly_gain >= 500:
                continuing.append(c)
            continue

        owner = c.full_name.split("/", 1)[0].lower()
        if owner in owners:
            continue
        owners.add(owner)
        finalists.append(c)
        if len(finalists) >= top_n:
            break

    continuing.sort(key=lambda c: c.weekly_gain or 0, reverse=True)
    return finalists, continuing[:10]
