"""用 LLM 回填历史日报的 AI 摘要（hy4 本地跑；日榜 CI 不做这件事）。

- 每个项目：类别 + 20 字内中文定位；每天：一段「今日看点」。
- 跳过首次全量扫描的基线日（条目数 > 2000，不是真实当日突破）。
- 产物 data/daily/digest_YYYY-MM-DD.json 会提交仓库，供网站展示。
- 中断后重跑自动跳过已完成的天。

用法：
    set -a; . ./.env.local; set +a
    python scripts/backfill_daily_digest.py
    python scripts/backfill_daily_digest.py --dry-run        # 只看计划
    python scripts/backfill_daily_digest.py --days 2026-10-30 2026-10-31
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.daily_digest import (  # noqa: E402
    DailyDigest,
    digest_daily_projects,
    fill_daily_intros,
    generate_daily_headline,
)
from src.weekly.llm import LLMClient  # noqa: E402

DAILY_DIR = ROOT / "data" / "daily"
MAX_PROJECTS = 2000
"""超过此数视为冷启动基线日，跳过。"""


def _load_milestones(path: Path) -> dict | None:
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _digest_path(day: str) -> Path:
    return DAILY_DIR / f"digest_{day}.json"


def _unreliable(data: dict) -> bool:
    """当日增量整体不可信：多数是伪增量（unknown_yesterday）或基线不是前一天。"""
    repos = data.get("repos") or []
    if not repos:
        return False
    unknown = sum(1 for r in repos if r.get("unknown_yesterday"))
    if unknown / len(repos) > 0.5:
        return True
    try:
        base = date.fromisoformat(data["baseline_date"])
        day = date.fromisoformat(data["date"])
        return (day - base).days != 1
    except (KeyError, TypeError, ValueError):
        return True


def _day_status(data: dict) -> tuple[int, int]:
    """返回 (项目数, 已有完整介绍数)，用于判断是否续跑。"""
    day = str(data.get("date", ""))
    repos = data.get("repos") or []
    out = _digest_path(day)
    have = 0
    if out.exists():
        try:
            digest = DailyDigest(**json.loads(out.read_text(encoding="utf-8")))
            have = sum(
                1 for r in repos
                if (it := digest.items.get(r["full_name"])) is not None
                and it.intro is not None
                and it.intro.one_liner != "unknown"
            )
        except Exception:
            have = 0
    return len(repos), have


def process_day(path: Path, client: LLMClient, workers: int) -> str:
    data = _load_milestones(path)
    if data is None:
        return "跳过（无法解析）"
    day = str(data.get("date", ""))
    repos = data.get("repos") or []
    if not day or not repos:
        return "跳过（无数据）"
    if len(repos) > MAX_PROJECTS:
        return f"跳过（{len(repos)} 条，冷启动基线日）"

    # 按可信增量排序，看点优先引用涨得多的项目
    def _gain(r: dict) -> int:
        gained = r.get("stars_gained")
        return gained if r.get("gain_reliable") and isinstance(gained, int) else 0

    repos.sort(key=_gain, reverse=True)
    model = settings.llm_model_writer
    out = _digest_path(day)

    # 续跑：读取已有产物，只补缺的（分类/定位、介绍、看点分别判断）
    digest = DailyDigest(date=day)
    if out.exists():
        try:
            digest = DailyDigest(**json.loads(out.read_text(encoding="utf-8")))
        except Exception:
            digest = DailyDigest(date=day)
    items = digest.items

    if not all(r["full_name"] in items for r in repos):
        new_items = digest_daily_projects(client, model, repos, max_workers=workers)
        for name, it in new_items.items():
            items.setdefault(name, it)

    filled = fill_daily_intros(client, model, day, repos, items, max_workers=workers)

    if not digest.headline:
        digest.headline, digest.points = generate_daily_headline(
            client, model, day, repos, items
        )
    digest.items = items
    out.write_text(
        digest.model_dump_json(exclude_none=True), encoding="utf-8"
    )
    total, have = _day_status(data)
    return f"完成（{len(repos)} 条，介绍 {have}/{total}，本次新增 {filled}）"


def main() -> int:
    parser = argparse.ArgumentParser(description="回填历史日报的 AI 摘要")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--days", nargs="*", type=str, help="只处理指定日期")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = parser.parse_args()

    paths = sorted(DAILY_DIR.glob("milestones_*.json.gz"))
    if args.days:
        wanted = set(args.days)
        paths = [p for p in paths if any(day in p.name for day in wanted)]

    todo = []
    for p in paths:
        data = _load_milestones(p)
        if data is None:
            continue
        repos = data.get("repos") or []
        day = data.get("date", "?")
        if len(repos) > MAX_PROJECTS:
            print(f"  {day}  跳过（{len(repos)} 条，冷启动基线日）")
            continue
        total, have = _day_status(data)
        done = total > 0 and have >= total
        print(f"  {day}  {'已完成，跳过' if done else f'待补（介绍 {have}/{total}）'}")
        if not done:
            todo.append(p)

    print(f"\n共 {len(paths)} 天，待生成 {len(todo)} 天")
    print(f"大模型：{settings.llm_base_url} · {settings.llm_model_writer}")
    if args.dry_run or not todo:
        return 0

    client = LLMClient()
    for i, p in enumerate(todo, 1):
        result = process_day(p, client, args.workers)
        print(f"[{i}/{len(todo)}] {p.name}: {result}", flush=True)
    print("\n✅ 全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
