"""对已有周榜做局部修补：补齐缺失的 AI 介绍、重新生成「本周看点」，并同步更新 Markdown。

不重跑聚合 / 打分 / 粗筛，入选名单保持不变。

用法：
    python scripts/regen_highlights.py data/weekly/weekly-2026-10-24_to_2026-10-30.json [...]
    python scripts/regen_highlights.py --fill-intros data/weekly/weekly-*.json   # 先补介绍再写看点
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.weekly.enrich import fetch_readme, make_readme_client  # noqa: E402
from src.weekly.llm import LLMClient, generate_highlights, generate_intro  # noqa: E402
from src.weekly.models import ProjectIntro, ScoredCandidate  # noqa: E402
from src.weekly.reporter import render_weekly_md  # noqa: E402

WEEKLY_DIR = (ROOT / "data" / "weekly").resolve()


def _has_intro(raw: object) -> bool:
    return isinstance(raw, dict) and raw.get("one_liner", "unknown") != "unknown"


def fill_intros(data: dict, client: LLMClient, workers: int) -> tuple[int, int]:
    """为缺少介绍的入选项目生成介绍，返回 (尝试数, 成功数)。"""
    todo = [f for f in data["finalists"] if not _has_intro(f.get("intro"))]
    if not todo:
        return 0, 0
    model = settings.llm_model_writer
    with make_readme_client() as rc:

        def _one(raw: dict) -> ProjectIntro:
            c = ScoredCandidate(**{k: v for k, v in raw.items() if k != "intro"})
            return generate_intro(client, model, c, fetch_readme(rc, c.full_name))

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            intros = list(pool.map(_one, todo))
    ok = 0
    for raw, intro in zip(todo, intros, strict=True):
        if intro.one_liner != "unknown":
            raw["intro"] = intro.model_dump(mode="json")
            ok += 1
    return len(todo), ok


def regen(path: Path, client: LLMClient, fill: bool, workers: int) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if fill:
        tried, ok = fill_intros(data, client, workers)
        if tried:
            print(f"  {path.name}: 补介绍 {ok}/{tried}")

    finalists = [
        ScoredCandidate(**{k: v for k, v in f.items() if k != "intro"})
        for f in data["finalists"]
    ]
    intros = {
        f["full_name"]: ProjectIntro(**f["intro"])
        for f in data["finalists"]
        if _has_intro(f.get("intro"))
    }
    continuing = [ScoredCandidate(**c) for c in data.get("continuing", [])]

    hl = generate_highlights(client, settings.llm_model_writer, finalists, intros)
    if hl is None:
        print(f"❌ {path.name}: 看点生成失败，保持原样")
        return False
    data["highlights"] = hl.model_dump(mode="json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    start = date.fromisoformat(data["window"]["start"])
    end = date.fromisoformat(data["window"]["end"])
    missing = [date.fromisoformat(d) for d in data.get("missing_days", [])]
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    md = render_weekly_md(
        finalists, intros, start, end,
        covered_days=[d for d in days if d not in missing],
        missing_days=missing,
        total_breakthroughs=data.get("total_breakthroughs") or 0,
        continuing=continuing,
        dry_run=bool(data.get("dry_run")),
        highlights=hl,
    )
    md_path = ROOT / "reports" / "weekly" / f"{path.stem}.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"✅ {path.name}: 介绍 {len(intros)}/{len(finalists)} · {hl.headline}")
    return len(intros) == len(finalists) or not fill


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐周榜介绍 / 重新生成本周看点")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--fill-intros", action="store_true", help="先为缺少介绍的项目生成介绍")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    client = LLMClient()
    ok = True
    for f in args.files:
        p = f.resolve()
        if p.parent != WEEKLY_DIR or not p.name.startswith("weekly-") or p.suffix != ".json":
            print(f"跳过非周榜文件：{f}")
            ok = False
            continue
        ok &= regen(p, client, args.fill_intros, args.workers)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
