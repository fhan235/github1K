"""weekly.score 打分与筛选逻辑的单元测试。"""
from __future__ import annotations

from datetime import date, timedelta

from src.weekly.models import EnrichedCandidate, ScoredCandidate
from src.weekly.score import score_candidate, select_final

_REF = date(2026, 10, 18)


def _candidate(**kw) -> EnrichedCandidate:
    defaults = dict(
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description="A genuinely useful developer tool for testing things",
        language="Python",
        topics=["python", "cli", "testing"],
        created_at="2026-09-20",
        forks_at_breakthrough=30,
        stars_at_breakthrough=1200,
        stars_at_first_seen=1100,
        best_gained=600,
        gain_reliable=True,
        best_unknown_yesterday=False,
        first_seen=_REF - timedelta(days=3),
        last_seen=_REF - timedelta(days=1),
        days_seen=3,
        enrich_ok=True,
        current_stars=3100,
        current_forks=80,
        pushed_at=_REF.isoformat() + "T00:00:00Z",
        license_spdx="MIT",
        weekly_gain=2000,
    )
    defaults.update(kw)
    return EnrichedCandidate(**defaults)


def test_healthy_growing_project_scores_high():
    c = score_candidate(_candidate(), _REF)
    assert c.score >= 80
    assert c.score_parts["growth"] > 20
    assert c.score_parts["persistence"] >= 20
    assert c.score_parts["freshness"] == 20
    assert c.score_parts["quality"] == 20
    assert "penalty" not in c.score_parts


def test_star_farming_penalized():
    """高 star 低 fork 且无描述 → 刷星嫌疑，分数大降。"""
    c = score_candidate(
        _candidate(
            description="",
            current_stars=5000,
            current_forks=10,
            weekly_gain=4000,
        ),
        _REF,
    )
    assert "suspected_star_farming" in c.flags
    assert "no_description" in c.flags
    healthy = score_candidate(_candidate(), _REF)
    assert c.score < healthy.score - 20


def test_legacy_giant_penalized():
    """unknown_yesterday 且体量巨大的存量老项目被打上标记并扣分。"""
    c = score_candidate(
        _candidate(
            best_unknown_yesterday=True,
            gain_reliable=False,
            stars_at_breakthrough=81179,
            current_stars=81200,
            weekly_gain=21,
            created_at="2019-01-01",
        ),
        _REF,
    )
    assert "suspected_legacy" in c.flags
    assert c.score_parts["freshness"] == 0
    assert c.score_parts["growth"] < 15  # 一周只涨 21 星，增长分很低


def test_archived_and_fork_zeroed():
    c = score_candidate(_candidate(archived=True), _REF)
    assert c.score == 0
    assert "archived_or_fork" in c.flags


def test_enrich_failure_mild_penalty():
    """复查失败不应直接归零（可能是网络问题），但要扣分。"""
    c = score_candidate(
        _candidate(enrich_ok=False, current_stars=None, current_forks=None,
                   weekly_gain=None, pushed_at=None, license_spdx=None),
        _REF,
    )
    assert "enrich_failed" in c.flags
    assert c.score > 0  # 仍有可信日榜增量撑分


def _scored(name: str, score: float, **kw) -> ScoredCandidate:
    base = _candidate(full_name=name, url=f"https://github.com/{name}")
    data = base.model_dump()
    data.update(kw)
    return ScoredCandidate(**data, score=score)


def test_select_final_owner_dedup_and_seen():
    items = [
        _scored("alice/a", 90),
        _scored("alice/b", 85),          # 同 owner，应被去重
        _scored("bob/c", 80),
        _scored("carol/d", 70),
    ]
    finalists, _ = select_final(items, top_n=3, seen=set())
    names = [c.full_name for c in finalists]
    assert names == ["alice/a", "bob/c", "carol/d"]


def test_select_final_seen_goes_to_continuing():
    items = [
        _scored("old/star", 95, weekly_gain=1200),
        _scored("new/fresh", 90, weekly_gain=300),
    ]
    finalists, continuing = select_final(items, top_n=5, seen={"old/star"})
    assert [c.full_name for c in finalists] == ["new/fresh"]
    assert [c.full_name for c in continuing] == ["old/star"]


def test_select_final_drops_junk_and_dead():
    items = [
        _scored("bad/junk", 95, triage_quality="junk"),
        _scored("dead/archived", 90, flags=["archived_or_fork"]),
        _scored("good/one", 80),
    ]
    finalists, _ = select_final(items, top_n=5, seen=set())
    assert [c.full_name for c in finalists] == ["good/one"]
