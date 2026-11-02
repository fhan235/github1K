"""按时间顺序回溯生成往期周榜（周六 → 周五，与 CI 周榜窗口一致）。

- 必须按时间先后跑：每期写入 seen.json，后面的周才能正确去重。
- 已生成且带 AI 介绍的周会跳过，中断后重跑即可续上。
- 一周涨幅用窗口结束次日的快照还原（--historical），不是今天的 star。

用法：
    python scripts/backfill_weekly.py --from 2026-05-30 --to 2026-10-23
    python scripts/backfill_weekly.py --from 2026-05-30 --to 2026-10-23 --dry-run  # 只看计划
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "data" / "weekly"
SATURDAY = 5  # date.weekday()


def windows(first: date, last: date) -> list[tuple[date, date]]:
    """返回所有完整落在 [first, last] 内的「周六 → 周五」窗口。"""
    start = first + timedelta(days=(SATURDAY - first.weekday()) % 7)
    out = []
    while start + timedelta(days=6) <= last:
        out.append((start, start + timedelta(days=6)))
        start += timedelta(days=7)
    return out


def already_done(start: date, end: date) -> bool:
    path = WEEKLY_DIR / f"weekly-{start.isoformat()}_to_{end.isoformat()}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return not data.get("dry_run") and any(f.get("intro") for f in data.get("finalists", []))


def main() -> int:
    parser = argparse.ArgumentParser(description="回溯生成往期周榜")
    parser.add_argument("--from", dest="first", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="last", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3, help="单期失败后的重试次数")
    parser.add_argument("--retry-wait", type=int, default=120, help="重试前等待秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = parser.parse_args()

    plan = windows(args.first, args.last)
    todo = [(s, e) for s, e in plan if not already_done(s, e)]
    print(f"共 {len(plan)} 期，待生成 {len(todo)} 期")
    for s, e in plan:
        print(f"  {s} → {e}  {'待生成' if (s, e) in todo else '已完成，跳过'}")
    if args.dry_run:
        return 0

    for i, (s, e) in enumerate(todo, 1):
        print(f"\n===== [{i}/{len(todo)}] {s} → {e} =====", flush=True)
        cmd = [
            sys.executable, "-m", "src.weekly.main",
            "--start", s.isoformat(), "--end", e.isoformat(),
            "--historical", "--workers", str(args.workers),
        ]
        # 周榜失败时不会写入任何产物，可安全重试（应对网络抖动 / DNS 短暂失败）
        for attempt in range(1, args.retries + 2):
            rc = subprocess.run(cmd, cwd=ROOT, check=False).returncode
            if rc == 0:
                break
            if attempt <= args.retries:
                print(
                    f"⚠️  {s} → {e} 失败（退出码 {rc}），"
                    f"{args.retry_wait}s 后第 {attempt} 次重试",
                    flush=True,
                )
                time.sleep(args.retry_wait)
        if rc != 0:
            print(f"❌ {s} → {e} 失败（退出码 {rc}），已停止；修复后重跑会从这一期续上")
            return rc
    print("\n✅ 全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
