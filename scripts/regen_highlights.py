"""只重新生成已有周榜的「本周看点」（不重跑聚合/打分/介绍），并同步更新 Markdown。

用法：
    python scripts/regen_highlights.py data/weekly/weekly-2026-10-24_to_2026-10-30.json [...]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.weekly.llm import LLMClient, generate_highlights  # noqa: E402
from src.weekly.models import ProjectIntro, ScoredCandidate  # noqa: E402
from src.weekly.reporter import render_weekly_md  # noqa: E402

WEEKLY_DIR = (ROOT / "data" / "weekly").resolve()


def regen(path: Path, client: LLMClient) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    finalists = [ScoredCandidate(**f) for f in data["finalists"]]
    intros = {
        f["full_name"]: ProjectIntro(**f["intro"])
        for f in data["finalists"]
        if isinstance(f.get("intro"), dict)
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
    print(f"✅ {path.name}: {hl.headline}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="重新生成周榜的本周看点")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    client = LLMClient()
    ok = True
    for f in args.files:
        p = f.resolve()
        if p.parent != WEEKLY_DIR or not p.name.startswith("weekly-") or p.suffix != ".json":
            print(f"跳过非周榜文件：{f}")
            ok = False
            continue
        ok &= regen(p, client)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
