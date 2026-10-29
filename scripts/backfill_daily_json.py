#!/usr/bin/env python3
"""历史回填：把 COS 上的历史 Markdown 完整报告转换为结构化 JSON 日榜。

逐日拉取（本地 JSON 已存在则跳过），解析后写入
``data/daily/milestones_YYYY-MM-DD[_created-since-*].json.gz``，
之后可直接 git add 提交回仓库，周榜即可对全部历史使用结构化数据。

用法：
    python scripts/backfill_daily_json.py
    python scripts/backfill_daily_json.py --start 2026-05-08 --end 2026-10-21
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# 允许直接以脚本方式运行（不安装包）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.models import Milestone1KRepo
from src.storage import milestone_store
from src.utils.timezone import today_bjt
from src.weekly.models import DailyEntry
from src.weekly.source import fetch_daily_entries

logger = logging.getLogger("backfill")

# 项目首次产生报告的日子（在此之前没有历史可回填）
_EARLIEST = date(2026, 4, 26)


def entry_to_milestone(e: DailyEntry) -> Milestone1KRepo:
    """把周榜解析出的 DailyEntry 转回结构化日榜记录。

    历史 Markdown 中不含 is_fork/is_archived，保持默认 False。
    """
    return Milestone1KRepo(
        full_name=e.full_name,
        url=e.url,
        description=e.description,
        language=e.language,
        stars_today=e.stars,
        stars_yesterday=e.stars_yesterday or 0,
        stars_gained=None if e.unknown_yesterday else e.gained,
        gain_reliable=e.gain_reliable,
        forks=e.forks,
        topics=e.topics,
        created_at=e.created_at,
        updated_at=None,
        unknown_yesterday=e.unknown_yesterday,
        is_recently_created=e.is_recently_created,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="回填历史结构化日榜 JSON")
    parser.add_argument("--start", default=_EARLIEST.isoformat())
    parser.add_argument("--end", default=today_bjt().isoformat())
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    created_since = (
        date.fromisoformat(settings.created_since) if settings.created_since else None
    )

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [
        d for d in days
        if milestone_store.load_milestones(d, created_since) is None
    ]
    print(
        f"📅 范围 {start} → {end}，共 {len(days)} 天，"
        f"已有 JSON {len(days) - len(todo)} 天，待回填 {len(todo)} 天"
    )
    if not todo:
        print("✅ 无需回填")
        return 0

    entries_by_date, missing = fetch_daily_entries(todo, created_since)
    written = 0
    for d, entries in sorted(entries_by_date.items()):
        baseline = entries[0].baseline_date if entries else None
        milestones = [entry_to_milestone(e) for e in entries]
        milestone_store.save_milestones(d, milestones, baseline, created_since)
        written += 1

    print()
    print(f"✅ 回填完成：写入 {written} 天，无数据 {len(missing)} 天")
    if missing:
        print(f"   无数据日期: {', '.join(d.isoformat() for d in missing)}")
    print()
    print("下一步：git add data/daily/ 并提交，让周榜在 CI 中也能读到历史 JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
