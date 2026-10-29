"""跨天聚合：把一周的日榜条目去重合并为周候选。"""
from __future__ import annotations

from datetime import date

from src.weekly.models import DailyEntry, WeeklyCandidate

# 合集/教程类项目关键词：有价值但不占主榜名额
_COLLECTION_KEYWORDS = [
    "awesome", "curated", "cheatsheet", "roadmap", "-list",
    "合集", "教程", "指南", "面试", "interview",
]


def _is_collection(name: str, description: str) -> bool:
    text = f"{name} {description}".lower()
    return any(kw in text for kw in _COLLECTION_KEYWORDS)


def aggregate(entries_by_date: dict[date, list[DailyEntry]]) -> list[WeeklyCandidate]:
    """按 full_name 去重合并一周的日榜条目。"""
    grouped: dict[str, list[DailyEntry]] = {}
    for d in sorted(entries_by_date):
        for entry in entries_by_date[d]:
            grouped.setdefault(entry.full_name, []).append(entry)

    candidates: list[WeeklyCandidate] = []
    for full_name, entries in grouped.items():
        entries.sort(key=lambda e: e.report_date)
        best = max(entries, key=lambda e: e.stars)
        first = entries[0]
        reliable_gains = [e.gained for e in entries if e.gain_reliable]

        flags: list[str] = []
        if _is_collection(full_name, best.description):
            flags.append("collection")

        candidates.append(
            WeeklyCandidate(
                full_name=full_name,
                url=best.url,
                description=best.description,
                language=best.language,
                topics=best.topics,
                created_at=best.created_at,
                forks_at_breakthrough=best.forks,
                stars_at_breakthrough=best.stars,
                stars_at_first_seen=first.stars,
                best_gained=max(reliable_gains) if reliable_gains else 0,
                gain_reliable=bool(reliable_gains),
                best_unknown_yesterday=best.unknown_yesterday,
                first_seen=first.report_date,
                last_seen=entries[-1].report_date,
                days_seen=len({e.report_date for e in entries}),
                flags=flags,
            )
        )
    return candidates


def shortlist(
    candidates: list[WeeklyCandidate],
    limit: int,
) -> tuple[list[WeeklyCandidate], list[WeeklyCandidate]]:
    """规则预过滤 + 截断，返回 (进入复查的候选, 被过滤掉的候选)。

    过滤：合集/教程类（进单独栏目不占主榜）、明显存量老项目
    （unknown_yesterday 且 star 体量巨大，几乎不可能是本周新破千）。
    排序键：可信增量优先，否则按上榜时 star 体量。
    """
    kept: list[WeeklyCandidate] = []
    dropped: list[WeeklyCandidate] = []
    for c in candidates:
        if "collection" in c.flags:
            dropped.append(c)
            continue
        if c.best_unknown_yesterday and c.stars_at_breakthrough >= 50000:
            c.flags.append("legacy_giant")
            dropped.append(c)
            continue
        kept.append(c)

    kept.sort(
        key=lambda c: (c.best_gained if c.gain_reliable else 0, c.stars_at_breakthrough),
        reverse=True,
    )
    return kept[:limit], dropped + kept[limit:]
