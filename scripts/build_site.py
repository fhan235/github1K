"""把 data/weekly/weekly-*.json 构建成静态展示站点（输出到 _site/，供 GitHub Pages 发布）。

只依赖标准库，CI 中无需安装项目依赖。

用法：
    python scripts/build_site.py                 # 构建到 _site/
    python -m http.server -d _site 8000          # 本地预览 http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "data" / "weekly"
WEB_DIR = ROOT / "web"
DEFAULT_OUT = ROOT / "_site"

_STEM_RE = re.compile(r"^weekly-(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_INTRO_FIELDS = (
    "one_liner",
    "what_it_is",
    "problem_solved",
    "who_should_care",
    "alternatives",
    "maturity",
    "hype_or_trend",
    "risk_notes",
)


def _str(v: object, limit: int = 2000) -> str:
    return v.strip()[:limit] if isinstance(v, str) else ""


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v: object) -> float | int | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _date(v: object) -> str | None:
    s = _str(v, 10)
    return s if _DATE_RE.match(s) else None


def _slim_intro(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    intro: dict = {}
    for key in _INTRO_FIELDS:
        s = _str(raw.get(key))
        if s and s.lower() != "unknown":
            intro[key] = s
    cases = [_str(u, 300) for u in raw.get("use_cases") or [] if _str(u)]
    if cases:
        intro["use_cases"] = cases[:5]
    # 与 Markdown 周报保持一致：没有 one_liner 视为无介绍
    return intro if intro.get("one_liner") else None


def _slim_project(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _str(raw.get("full_name"), 201)
    if not _REPO_RE.match(name):
        return None
    flags = [f for f in raw.get("flags") or [] if isinstance(f, str)]
    risky = any(f.startswith("suspected") for f in flags) or raw.get(
        "triage_quality"
    ) == "suspicious"
    topics = [_str(t, 50) for t in raw.get("topics") or [] if _str(t)]
    return {
        "name": name,
        # 只用校验过的仓库名拼 URL，不信任原始 url 字段
        "url": f"https://github.com/{name}",
        "description": _str(raw.get("description"), 600),
        "language": _str(raw.get("language"), 40) or None,
        "topics": topics[:8],
        "created_at": _date(_str(raw.get("created_at"))[:10]),
        "license": _str(raw.get("license_spdx"), 40) or None,
        "category": _str(raw.get("category"), 40) or "other",
        "stars_at_breakthrough": _int(raw.get("stars_at_breakthrough")),
        "current_stars": _int(raw.get("current_stars")),
        "weekly_gain": _int(raw.get("weekly_gain")),
        "best_gained": _int(raw.get("best_gained")) if raw.get("gain_reliable") else None,
        "days_seen": _int(raw.get("days_seen")),
        "first_seen": _date(raw.get("first_seen")),
        "score": _num(raw.get("score")),
        "risky": risky,
        "risk_reason": _str(raw.get("triage_reason"), 300) if risky else "",
        "intro": _slim_intro(raw.get("intro")),
    }


def _build_week(path: Path) -> dict | None:
    m = _STEM_RE.match(path.stem)
    if not m:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠️  跳过无法解析的文件 {path.name}: {e}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        return None

    finalists = [p for p in map(_slim_project, data.get("finalists") or []) if p]
    continuing = [p for p in map(_slim_project, data.get("continuing") or []) if p]
    dry_run = data.get("dry_run")
    if not isinstance(dry_run, bool):
        # 旧数据没有该字段：全部缺少介绍即视为 dry-run
        dry_run = not any(p["intro"] for p in finalists)

    return {
        "id": path.stem,
        "start": m.group(1),
        "end": m.group(2),
        "missing_days": [d for d in map(_date, data.get("missing_days") or []) if d],
        "total_breakthroughs": _int(data.get("total_breakthroughs")),
        "dry_run": dry_run,
        "finalists": finalists,
        "continuing": continuing,
    }


def _dump(obj: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def build(out: Path) -> int:
    out = out.resolve()
    if out == ROOT or out in ROOT.parents:
        raise SystemExit(f"拒绝清空输出目录：{out}")
    if not WEB_DIR.is_dir():
        raise SystemExit(f"缺少前端模板目录：{WEB_DIR}")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB_DIR, out)
    (out / ".nojekyll").write_text("", encoding="utf-8")

    weeks = [w for w in map(_build_week, sorted(WEEKLY_DIR.glob("weekly-*.json"))) if w]
    weeks.sort(key=lambda w: w["end"], reverse=True)

    for w in weeks:
        _dump(w, out / "data" / "weeks" / f"{w['id']}.json")

    _dump(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "weeks": [
                {
                    "id": w["id"],
                    "start": w["start"],
                    "end": w["end"],
                    "picked": len(w["finalists"]),
                    "total_breakthroughs": w["total_breakthroughs"],
                    "dry_run": w["dry_run"],
                }
                for w in weeks
            ],
        },
        out / "data" / "index.json",
    )
    return len(weeks)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 github1K 周榜静态站点")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录（默认 _site/）")
    args = parser.parse_args()
    n = build(args.out)
    print(f"✅ 站点已生成：{args.out.resolve()}（共 {n} 期周榜）")


if __name__ == "__main__":
    main()
