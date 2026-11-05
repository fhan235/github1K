"""重写含英文字段名的旧介绍（改提示词之前用 DeepSeek 写的），并同步更新周报与日报。

- 用当前配置的模型（本地 hy4）重新生成，use_cache=False 强制覆盖。
- 周报 JSON 与 Markdown、日报 digest 里的旧介绍一并替换。

用法：
    set -a; . ./.env.local; set +a
    python scripts/regen_leak_intros.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.weekly.enrich import fetch_readme, make_readme_client  # noqa: E402
from src.weekly.llm import LLMClient, generate_intro, load_cached_intro  # noqa: E402
from src.weekly.models import (  # noqa: E402
    ProjectIntro,
    ScoredCandidate,
    WeeklyHighlights,
)
from src.weekly.reporter import render_weekly_md  # noqa: E402

WEEKLY_DIR = ROOT / "data" / "weekly"
DAILY_DIR = ROOT / "data" / "daily"

LEAK_RE = re.compile(r"\b[a-z]+_[a-z_]+\b|项目事实|\bnull\b|\bNone\b")
# 合法的项目名/术语也含下划线，只有明确是内部字段名的才算泄漏
FIELD_RE = re.compile(
    r"\b(open_issues|weekly_gain|current_stars|stars_at_breakthrough|stars_at_first_seen|"
    r"days_on_daily_board|first_seen|last_seen|created_at|pushed_at|gain_reliable|"
    r"risk_flags|triage_quality|score_parts|best_gained|unknown_yesterday)\b|项目事实"
)


def _leaks(intro: dict | None) -> bool:
    if not intro or intro.get("one_liner") == "unknown":
        return False
    body = " ".join(str(v) for k, v in intro.items() if k != "evidence")
    return bool(FIELD_RE.search(body))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="重写含字段名的旧介绍")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # 1. 找出所有泄漏的项目（周报 + 日报）
    weekly_files = sorted(WEEKLY_DIR.glob("weekly-*.json"))
    daily_files = sorted(DAILY_DIR.glob("digest_*.json"))
    candidates: dict[str, dict] = {}  # name -> 原始 finalist dict（供重新生成）
    for p in weekly_files:
        for f in _load(p).get("finalists", []):
            if _leaks(f.get("intro")) and f["full_name"] not in candidates:
                candidates[f["full_name"]] = f
    daily_only = set()
    for p in daily_files:
        for name, v in _load(p).get("items", {}).items():
            if _leaks(v.get("intro")) and name not in candidates:
                daily_only.add(name)
    print(f"泄漏项目：周报 {len(candidates)} 个，仅日报 {len(daily_only)} 个")
    if args.dry_run or not candidates:
        return 0

    # 2. 用当前模型重新生成（强制不用缓存）
    client = LLMClient()
    model = settings.llm_model_writer
    names = list(candidates)
    with make_readme_client() as rc:

        def _one(name: str) -> ProjectIntro:
            raw = candidates[name]
            c = ScoredCandidate(**{k: v for k, v in raw.items() if k != "intro"})
            return generate_intro(client, model, c, fetch_readme(rc, name), use_cache=False)

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            intros = list(pool.map(_one, names))
    fixed = {
        n: i for n, i in zip(names, intros, strict=True) if i.one_liner != "unknown"
    }
    print(f"重新生成 {len(fixed)}/{len(names)} 条")

    # 3. 更新周报 JSON + 重渲染 Markdown
    for p in weekly_files:
        data = _load(p)
        touched = False
        for f in data.get("finalists", []):
            if f["full_name"] in fixed and _leaks(f.get("intro")):
                f["intro"] = fixed[f["full_name"]].model_dump(mode="json")
                touched = True
        if not touched:
            continue
        _save(p, data)
        finalists = [
            ScoredCandidate(**{k: v for k, v in f.items() if k != "intro"})
            for f in data["finalists"]
        ]
        intro_map = {
            f["full_name"]: ProjectIntro(**f["intro"])
            for f in data["finalists"]
            if isinstance(f.get("intro"), dict)
        }
        start = date.fromisoformat(data["window"]["start"])
        end = date.fromisoformat(data["window"]["end"])
        missing = [date.fromisoformat(d) for d in data.get("missing_days", [])]
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        md = render_weekly_md(
            finalists, intro_map, start, end,
            covered_days=[d for d in days if d not in missing],
            missing_days=missing,
            total_breakthroughs=data.get("total_breakthroughs") or 0,
            continuing=[ScoredCandidate(**c) for c in data.get("continuing", [])],
            dry_run=bool(data.get("dry_run")),
            highlights=(
                WeeklyHighlights(**data["highlights"]) if data.get("highlights") else None
            ),
        )
        (ROOT / "reports" / "weekly" / f"{p.stem}.md").write_text(md, encoding="utf-8")
        print(f"  更新周报 {p.stem}")

    # 4. 更新日报 digest
    for p in daily_files:
        data = _load(p)
        touched = False
        for name, v in data.get("items", {}).items():
            if name in fixed and _leaks(v.get("intro")):
                v["intro"] = fixed[name].model_dump(mode="json")
                touched = True
        if touched:
            _save(p, data)

    # 5. 复查
    left = 0
    for p in weekly_files:
        left += sum(1 for f in _load(p).get("finalists", []) if _leaks(f.get("intro")))
    for p in daily_files:
        left += sum(1 for v in _load(p).get("items", {}).values() if _leaks(v.get("intro")))
    print(f"剩余泄漏 {left} 条")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
