"""按时间顺序回溯生成往期周榜（周六 → 周五，与 CI 周榜窗口一致）。

- 必须按时间先后跑：每期写入 seen.json，后面的周才能正确去重。
- 已按相同 --top 生成且带 AI 介绍的周会跳过，中断后重跑即可续上。
- 一周涨幅用窗口结束次日的快照还原（--historical），不是今天的 star。
- 开跑前会把已有周报里的 AI 介绍写回缓存：换模型或扩容时，旧项目不会重新生成。

用法：
    python scripts/backfill_weekly.py --from 2026-05-30 --to 2026-10-30 --top 100 --reset-seen
    python scripts/backfill_weekly.py --from 2026-05-30 --to 2026-10-30 --dry-run  # 只看计划
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
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.weekly.llm import seed_intro_cache  # noqa: E402

WEEKLY_DIR = ROOT / "data" / "weekly"
SEEN_PATH = WEEKLY_DIR / "seen.json"
SATURDAY = 5  # date.weekday()
SEED_MODEL = "deepseek-chat"
"""已有周报里的介绍都是 DeepSeek 写的，按这个模型名写回缓存。"""


def windows(first: date, last: date) -> list[tuple[date, date]]:
    """返回所有完整落在 [first, last] 内的「周六 → 周五」窗口。"""
    start = first + timedelta(days=(SATURDAY - first.weekday()) % 7)
    out = []
    while start + timedelta(days=6) <= last:
        out.append((start, start + timedelta(days=6)))
        start += timedelta(days=7)
    return out


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def already_done(start: date, end: date, top: int) -> bool:
    data = _load(WEEKLY_DIR / f"weekly-{start.isoformat()}_to_{end.isoformat()}.json")
    if data is None or data.get("dry_run") or data.get("top_n") != top:
        return False
    return any(f.get("intro") for f in data.get("finalists", []))


def seed_cache() -> int:
    n = 0
    for path in sorted(WEEKLY_DIR.glob("weekly-*.json")):
        data = _load(path) or {}
        for f in data.get("finalists", []):
            if isinstance(f.get("intro"), dict) and isinstance(f.get("full_name"), str):
                n += seed_intro_cache(SEED_MODEL, f["full_name"], f["intro"])
    return n


def reset_seen(since: date) -> tuple[int, int]:
    """删除 since 当天及之后上榜的记录，返回 (原数量, 剩余数量)。"""
    seen = _load(SEEN_PATH) or {}
    kept = {
        k: v for k, v in seen.items()
        if isinstance(v, dict) and str(v.get("date", "")) < since.isoformat()
    }
    SEEN_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(seen), len(kept)


def main() -> int:
    parser = argparse.ArgumentParser(description="回溯生成往期周榜")
    parser.add_argument("--from", dest="first", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="last", required=True, type=date.fromisoformat)
    parser.add_argument("--top", type=int, default=settings.weekly_top_n, help="每期精选数量")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3, help="单期失败后的重试次数")
    parser.add_argument("--retry-wait", type=int, default=120, help="重试前等待秒数")
    parser.add_argument(
        "--reset-seen", action="store_true",
        help="重做整段历史时使用：先清掉窗口起点之后的 seen.json 记录",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = parser.parse_args()

    plan = windows(args.first, args.last)
    todo = [(s, e) for s, e in plan if not already_done(s, e, args.top)]
    print(f"共 {len(plan)} 期，每期 {args.top} 个，待生成 {len(todo)} 期")
    print(f"大模型：{settings.llm_base_url} · {settings.llm_model_writer}")
    for s, e in plan:
        print(f"  {s} → {e}  {'待生成' if (s, e) in todo else '已完成，跳过'}")
    if args.dry_run or not todo:
        return 0

    print(f"\n已有介绍写回缓存：{seed_cache()} 条")
    if args.reset_seen:
        before, after = reset_seen(todo[0][0])
        print(f"seen.json：{before} → {after}（清除 {todo[0][0]} 之后的记录）")

    for i, (s, e) in enumerate(todo, 1):
        print(f"\n===== [{i}/{len(todo)}] {s} → {e} =====", flush=True)
        cmd = [
            sys.executable, "-m", "src.weekly.main",
            "--start", s.isoformat(), "--end", e.isoformat(),
            "--top", str(args.top),
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
