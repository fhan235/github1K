"""weekly.source 解析器与 weekly.aggregate 聚合逻辑的单元测试。"""
from __future__ import annotations

from datetime import date

from src.weekly.aggregate import aggregate, shortlist
from src.weekly.source import parse_milestone_report

SAMPLE = """# 🚀 GitHub 1K 突破榜 | 2026-05-27

> 统计区间：2026-05-26 → 2026-05-27
> 创建时间过滤：仅包含 **2020-01-01** 之后创建的仓库
> 共发现 **2** 个项目在此期间突破 1000 Star，全部展示

---

### 🥇 [atpuxiner/fastapi-scaff](https://github.com/atpuxiner/fastapi-scaff)
⭐ **1,000** 星  （昨天 999，增量 **+1**）  `Python`
`██████████` 1,000 stars
> This is a fastapi scaff. (fastapi脚手架)
🏷️ `fastapi` `fastapi-scaff` `python`
🍴 42 forks  📅 创建于 2024-07-30

### 🥈 [old/famous-repo](https://github.com/old/famous-repo)
⭐ **81,179** 星  （昨天 —，增量 **+81,179**）  `Python`  ❓ *昨日未追踪*
`██████████` 81,179 stars
🍴 1,234 forks  📅 创建于 2019-01-01

---

## 📊 语言分布

| 语言 | 项目数 |
|------|--------|
| Python | 2 |
"""

# 统计区间跨两天（断跑回退），增量不可信
SAMPLE_GAP = """# 🚀 GitHub 1K 突破榜 | 2026-10-21

> 统计区间：2026-10-19 → 2026-10-21
> 共发现 **1** 个项目在此期间突破 1000 Star，全部展示

### 🥇 [a/b](https://github.com/a/b)
⭐ **2,000** 星  （昨天 800，增量 **+1,200**）  `Go`
> some description here
"""


def test_parse_basic_fields():
    entries = parse_milestone_report(SAMPLE, date(2026, 5, 27))
    assert len(entries) == 2

    first = entries[0]
    assert first.full_name == "atpuxiner/fastapi-scaff"
    assert first.stars == 1000
    assert first.gained == 1
    assert first.stars_yesterday == 999
    assert first.language == "Python"
    assert first.description.startswith("This is a fastapi scaff")
    assert first.topics == ["fastapi", "fastapi-scaff", "python"]
    assert first.forks == 42
    assert first.created_at == "2024-07-30"
    assert first.baseline_date == date(2026, 5, 26)
    assert not first.unknown_yesterday
    assert first.gain_reliable


def test_parse_unknown_yesterday_flag():
    entries = parse_milestone_report(SAMPLE, date(2026, 5, 27))
    second = entries[1]
    assert second.full_name == "old/famous-repo"
    assert second.stars_yesterday is None
    assert second.unknown_yesterday
    # 伪增量：gain 语义不可信
    assert not second.gain_reliable


def test_gain_unreliable_when_baseline_gap():
    """断跑导致基准回退时，gained 是多日累计，不可信。"""
    entries = parse_milestone_report(SAMPLE_GAP, date(2026, 10, 21))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.baseline_date == date(2026, 10, 19)
    assert not entry.gain_reliable


SAMPLE_DAY2 = """# 🚀 GitHub 1K 突破榜 | 2026-05-28

> 统计区间：2026-05-27 → 2026-05-28
> 共发现 **1** 个项目在此期间突破 1000 Star，全部展示

### 🥇 [atpuxiner/fastapi-scaff](https://github.com/atpuxiner/fastapi-scaff)
⭐ **1,800** 星  （昨天 999，增量 **+801**）  `Python`
> This is a fastapi scaff. (fastapi脚手架)
🏷️ `fastapi` `fastapi-scaff` `python`
🍴 50 forks  📅 创建于 2024-07-30
"""


def test_aggregate_dedup_and_days_seen():
    d1 = parse_milestone_report(SAMPLE, date(2026, 5, 27))
    # 同一项目第二天再次上榜（stars 上涨）
    d2 = parse_milestone_report(SAMPLE_DAY2, date(2026, 5, 28))

    candidates = aggregate({date(2026, 5, 27): d1, date(2026, 5, 28): d2})
    assert len(candidates) == 2

    scaff = next(c for c in candidates if c.full_name == "atpuxiner/fastapi-scaff")
    assert scaff.days_seen == 2
    assert scaff.stars_at_breakthrough == 1800
    assert scaff.stars_at_first_seen == 1000
    assert scaff.best_gained == 801
    assert scaff.gain_reliable
    assert scaff.first_seen == date(2026, 5, 27)
    assert scaff.last_seen == date(2026, 5, 28)


def test_shortlist_filters_collections_and_legacy_giants():
    entries = parse_milestone_report(SAMPLE, date(2026, 5, 27))
    candidates = aggregate({date(2026, 5, 27): entries})
    # old/famous-repo: unknown_yesterday 且 81,179 stars → 存量巨型老项目被过滤
    kept, dropped = shortlist(candidates, limit=100)
    assert [c.full_name for c in kept] == ["atpuxiner/fastapi-scaff"]
    assert any("legacy_giant" in c.flags for c in dropped)


def test_shortlist_collection_flag():
    text = SAMPLE.replace(
        "atpuxiner/fastapi-scaff](https://github.com/atpuxiner/fastapi-scaff)",
        "someone/awesome-ai](https://github.com/someone/awesome-ai)",
    )
    entries = parse_milestone_report(text, date(2026, 5, 27))
    candidates = aggregate({date(2026, 5, 27): entries})
    awesome = next(c for c in candidates if c.full_name == "someone/awesome-ai")
    assert "collection" in awesome.flags
