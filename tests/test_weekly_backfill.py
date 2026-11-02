"""回溯模式与看点事实计算的单元测试。"""
from __future__ import annotations

from datetime import date

from src.models import DailySnapshot
from src.weekly import enrich
from src.weekly.llm import build_highlight_facts
from src.weekly.models import EnrichedCandidate, ScoredCandidate


def _cand(name: str, first_stars: int, last_seen: date, **kw) -> EnrichedCandidate:
    return EnrichedCandidate(
        full_name=name,
        url=f"https://github.com/{name}",
        stars_at_breakthrough=first_stars,
        stars_at_first_seen=first_stars,
        first_seen=last_seen,
        last_seen=last_seen,
        current_stars=99999,
        weekly_gain=99999 - first_stars,
        **kw,
    )


def test_apply_snapshot_stars_uses_window_end(monkeypatch):
    snaps = {
        date(2026, 6, 6): {"a/x": 1500},          # 结束次日
        date(2026, 6, 5): {"a/x": 1400, "b/y": 1300},
        date(2026, 6, 4): {},
        date(2026, 6, 3): {"c/z": 1100},
    }
    monkeypatch.setattr(
        enrich.snapshot_store,
        "load_snapshot",
        lambda d, cs=None: DailySnapshot(date=d.isoformat(), repos=snaps.get(d, {})),
    )
    a = _cand("a/x", 1000, date(2026, 6, 1))
    b = _cand("b/y", 1000, date(2026, 6, 1))       # 次日快照漏掉 → 回看前一天
    c = _cand("c/z", 1000, date(2026, 6, 5))       # 只有早于 last_seen 的快照 → 不用
    hit = enrich.apply_snapshot_stars([a, b, c], date(2026, 6, 5), None)

    assert hit == 2
    assert (a.current_stars, a.weekly_gain) == (1500, 500)
    assert (b.current_stars, b.weekly_gain) == (1300, 300)
    assert (c.current_stars, c.weekly_gain) == (None, None)


def _scored(name: str, cat: str, gain: int | None, lang: str = "Python") -> ScoredCandidate:
    return ScoredCandidate(
        full_name=name, url=f"https://github.com/{name}", language=lang,
        stars_at_breakthrough=1000, stars_at_first_seen=1000,
        first_seen=date(2026, 6, 1), last_seen=date(2026, 6, 1),
        weekly_gain=gain, category=cat,
    )


def test_highlight_facts_are_precomputed():
    facts = build_highlight_facts([
        _scored("a/1", "ai-agent", 500),
        _scored("b/2", "ai-agent", 11205, "Rust"),
        _scored("c/3", "game", 7228),
        _scored("d/4", "game", None),
        _scored("e/5", "ai-agent", -3),
    ])
    assert facts["finalist_count"] == 5
    assert facts["category_counts"] == {"ai-agent": 3, "game": 2}
    assert [g["full_name"] for g in facts["top_gainers"]] == ["b/2", "c/3", "a/1"]
    assert facts["top_gainers"][0]["rank"] == 1
