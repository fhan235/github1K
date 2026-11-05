"""把 data/weekly/weekly-*.json 构建成静态展示站点（输出到 _site/，供 GitHub Pages 发布）。

只依赖标准库，CI 中无需安装项目依赖。

用法：
    python scripts/build_site.py                 # 构建到 _site/
    python -m http.server -d _site 8000          # 本地预览 http://localhost:8000
"""
from __future__ import annotations

import argparse
import gzip
import html as _html
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEEKLY_DIR = DATA_DIR / "weekly"
WEB_DIR = ROOT / "web"
DEFAULT_OUT = ROOT / "_site"

SPARK_DAYS_BEFORE = 7
"""走势曲线从周窗口起点往前多看几天，用来展示「破千前」的爬坡。"""
SPARK_DAYS_AFTER = 1
"""周窗口结束后多看 1 天（周榜复查当天）。"""

_STEM_RE = re.compile(r"^weekly-(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})$")
_SNAPSHOT_RE = re.compile(
    r"^snapshot_(\d{4}-\d{2}-\d{2})(?:_created-since-(\d{4}-\d{2}-\d{2}))?\.json\.gz$"
)
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


# ── 清洗 ────────────────────────────────────────────────────────────────────


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


def _slim_highlights(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    points = [_str(p, 200) for p in raw.get("points") or [] if _str(p)]
    if not points:
        return None
    return {"headline": _str(raw.get("headline"), 80), "points": points[:5]}


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


# ── 数据速览（不依赖 LLM，从数据直接算）────────────────────────────────────


def _days_between(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except ValueError:
        return None


def _week_stats(finalists: list[dict]) -> dict:
    stats: dict = {}

    gainers = [p for p in finalists if (p["weekly_gain"] or 0) > 0]
    if gainers:
        top = max(gainers, key=lambda p: p["weekly_gain"])
        stats["top_gainer"] = {"name": top["name"], "value": top["weekly_gain"]}

    ages = [
        (d, p)
        for p in finalists
        if (d := _days_between(p["created_at"], p["first_seen"])) is not None and d >= 0
    ]
    if ages:
        d, p = min(ages, key=lambda x: x[0])
        stats["fastest"] = {"name": p["name"], "value": d}

    langs = Counter(p["language"] for p in finalists if p["language"])
    stats["languages"] = langs.most_common(3)

    cats = Counter(p["category"] for p in finalists if p["category"] != "other")
    stats["categories"] = cats.most_common(3)

    stats["with_intro"] = sum(1 for p in finalists if p["intro"])
    return stats


# ── Star 走势（来自每日快照）─────────────────────────────────────────────────


class SnapshotIndex:
    """按日期定位每日快照文件；只在需要时解压读取。"""

    def __init__(self, data_dir: Path, created_since: str) -> None:
        self._files: dict[str, Path] = {}
        for p in data_dir.glob("snapshot_*.json.gz"):
            m = _SNAPSHOT_RE.match(p.name)
            if m and (m.group(2) or "") == created_since:
                self._files[m.group(1)] = p

    def __len__(self) -> int:
        return len(self._files)

    def load(self, day: str) -> dict | None:
        p = self._files.get(day)
        if p is None:
            return None
        try:
            raw = json.loads(gzip.decompress(p.read_bytes()))
        except (OSError, EOFError, ValueError) as e:
            print(f"⚠️  快照读取失败 {p.name}: {e}", file=sys.stderr)
            return None
        repos = raw.get("repos") if isinstance(raw, dict) else None
        return repos if isinstance(repos, dict) else None


def _spark_dates(week: dict) -> list[str]:
    start = date.fromisoformat(week["start"]) - timedelta(days=SPARK_DAYS_BEFORE)
    end = date.fromisoformat(week["end"]) + timedelta(days=SPARK_DAYS_AFTER)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _attach_sparks(
    groups: list[tuple[list[dict], list[str]]],
    snapshots: SnapshotIndex,
    last_fallback: dict[str, int] | None = None,
) -> None:
    """为每组项目附上 Star 走势。每份快照只读一次，只抽取需要的仓库。

    groups: (项目列表, 日期列表)。last_fallback: {仓库名: 点数}，快照缺最后一个点时用
    （周榜复查 star 发生在窗口结束次日，正好补曲线末端）。
    """
    needs: dict[str, set[str]] = defaultdict(set)
    for projects, dates in groups:
        for d in dates:
            needs[d].update(p["name"] for p in projects)

    stars: dict[tuple[str, str], int] = {}
    for d, names in needs.items():
        repos = snapshots.load(d)
        if not repos:
            continue
        for n in names:
            v = _int(repos.get(n))
            if v is not None:
                stars[(d, n)] = v

    for projects, dates in groups:
        for p in projects:
            values = [stars.get((d, p["name"])) for d in dates]
            fb = (last_fallback or {}).get(p["name"])
            if values[-1] is None and fb is not None:
                values[-1] = fb
            enough = sum(v is not None for v in values) >= 2
            p["spark"] = {"start": dates[0], "values": values} if enough else None


def _attach_sparklines(weeks: list[dict], snapshots: SnapshotIndex) -> None:
    fallback = {
        p["name"]: p["current_stars"]
        for w in weeks
        for p in w["finalists"]
        if p["current_stars"] is not None
    }
    _attach_sparks(
        [(w["finalists"], _spark_dates(w)) for w in weeks], snapshots, fallback
    )


# ── 日报 ────────────────────────────────────────────────────────────────────

MAX_DAILY_PROJECTS = 2000
"""超过此数视为冷启动基线日，不在网站显示。"""

DAILY_SPARK_DAYS = 13
"""日报走势曲线看当天往前多少天。"""


def _load_milestones(path: Path) -> dict | None:
    try:
        data = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError, ValueError) as e:
        print(f"⚠️  日报读取失败 {path.name}: {e}", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def _daily_unreliable(data: dict, repos: list[dict]) -> bool:
    """当日增量整体不可信：多数是伪增量，或对比基线不是前一天。"""
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


def _slim_daily_project(raw: object, digest: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _str(raw.get("full_name"), 201)
    if not _REPO_RE.match(name):
        return None
    gained = _int(raw.get("stars_gained")) if raw.get("gain_reliable") else None
    topics = [_str(t, 50) for t in raw.get("topics") or [] if _str(t)]
    item = digest.get(name) if isinstance(digest, dict) else None
    intro = _slim_intro((item or {}).get("intro"))
    one_liner = _str((item or {}).get("one_liner"), 40) or (intro or {}).get("one_liner", "")
    return {
        "name": name,
        "url": f"https://github.com/{name}",
        "description": _str(raw.get("description"), 400),
        "language": _str(raw.get("language"), 40) or None,
        "topics": topics[:6],
        "created_at": _date(_str(raw.get("created_at"))[:10]),
        "stars": _int(raw.get("stars_today")),
        "gained": gained,
        "is_fork": bool(raw.get("is_fork")),
        "category": _str((item or {}).get("category"), 40) or "other",
        "one_liner": one_liner,
        "intro": intro,
    }


def _build_day(path: Path) -> dict | None:
    data = _load_milestones(path)
    if data is None:
        return None
    day = _date(data.get("date"))
    repos = [p for p in map(dict, data.get("repos") or [])]
    if not day or not repos or len(repos) > MAX_DAILY_PROJECTS:
        return None

    digest: dict = {}
    dpath = DATA_DIR / "daily" / f"digest_{day}.json"
    if dpath.exists():
        try:
            raw = json.loads(dpath.read_text(encoding="utf-8"))
            digest = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass
    items = digest.get("items") if isinstance(digest.get("items"), dict) else {}

    projects = [p for p in (_slim_daily_project(r, items) for r in repos) if p]
    # 默认排序：可信日增高的在前，其余按破千时 star
    projects.sort(key=lambda p: (p["gained"] or 0, p["stars"] or 0), reverse=True)
    return {
        "date": day,
        "unreliable": _daily_unreliable(data, repos),
        "headline": _str(digest.get("headline"), 60),
        "points": [_str(p, 120) for p in digest.get("points") or [] if _str(p)][:3],
        "has_digest": any(p["intro"] for p in projects),
        "gained_total": sum(p["gained"] or 0 for p in projects),
        "projects": projects,
    }


def _daily_spark_dates(day: str) -> list[str]:
    end = date.fromisoformat(day)
    start = end - timedelta(days=DAILY_SPARK_DAYS)
    return [(start + timedelta(days=i)).isoformat() for i in range(DAILY_SPARK_DAYS + 1)]


# ── 组装 ────────────────────────────────────────────────────────────────────


def _total_from_markdown(stem: str) -> int | None:
    """旧周报 JSON 没有 total_breakthroughs，从同名 Markdown 头部兜底解析。"""
    md = ROOT / "reports" / "weekly" / f"{stem}.md"
    try:
        head = md.read_text(encoding="utf-8")[:1000]
    except OSError:
        return None
    m = re.search(r"本周共 \*\*([\d,]+)\*\* 个项目突破", head)
    return int(m.group(1).replace(",", "")) if m else None


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
        "total_breakthroughs": _int(data.get("total_breakthroughs"))
        or _total_from_markdown(path.stem),
        "dry_run": dry_run,
        "highlights": _slim_highlights(data.get("highlights")),
        "stats": _week_stats(finalists),
        "finalists": finalists,
        "continuing": continuing,
    }


def _dump(obj: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


# ── 静态分享页 / SEO / RSS ─────────────────────────────────────────────────
#
# SPA 里的内容搜索引擎和微信转发卡片抓不到，所以构建时额外生成：
# - /w/<期号>/、/d/<日期>/ ：无 JS 也能读、带 OG 标签的静态页
# - /feed.xml：RSS 订阅；/sitemap.xml、/robots.txt：给搜索引擎

_PAGE_CSS = (
    "body{margin:0;background:#f4f5f7;color:#1f2329;line-height:1.7;"
    "font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif}"
    "main{max-width:760px;margin:0 auto;padding:24px 18px 48px}"
    "a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}"
    ".meta{color:#8f959e;font-size:.85rem}"
    ".box{background:#fff;border:1px solid #e4e6eb;border-radius:12px;"
    "padding:16px 20px;margin:14px 0}"
    ".box .hl{font-size:1.1rem;font-weight:700;margin:4px 0 8px}"
    ".eyebrow{color:#2563eb;font-size:.78rem;font-weight:600;letter-spacing:1px}"
    "ol{padding-left:1.4em}li{margin:8px 0}"
    "li .t{font-weight:600}"
    "h1{font-size:1.4rem}h2{font-size:1.05rem;margin-top:28px}"
)


def _esc(s: object) -> str:
    return _html.escape(str(s or ""))


def _render_week_page(w: dict, no: int, base: str) -> str:
    title = f"第 {no} 期 GitHub 破千周榜（{w['start']} → {w['end']}）"
    hl = w.get("highlights") or {}
    desc = hl.get("headline") or (
        f"本周 {w['total_breakthroughs'] or '—'} 个项目突破 1000 Star，"
        f"精选 {len(w['finalists'])} 个"
    )
    url = f"{base}/w/{w['id']}/"
    items = []
    for p in w["finalists"]:
        intro = p.get("intro") or {}
        line = intro.get("one_liner") or (p.get("description") or "")[:60]
        meta = [f"⭐ {p['current_stars'] or p['stars_at_breakthrough'] or '—'}"]
        if p.get("weekly_gain"):
            meta.append(f"一周 +{p['weekly_gain']:,}")
        if p.get("language"):
            meta.append(p["language"])
        items.append(
            f'<li><a href="{_esc(p["url"])}">{_esc(p["name"])}</a>'
            f' <span class="t">{_esc(line)}</span>'
            f' <span class="meta">{" · ".join(_esc(m) for m in meta)}</span></li>'
        )
    points = "".join(f"<li>{_esc(p)}</li>" for p in hl.get("points", []))
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · github1K</title>
<meta name="description" content="{_esc(desc)}">
<link rel="canonical" href="{_esc(url)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{_esc(url)}">
<meta property="og:image" content="{_esc(base)}/assets/og.png">
<meta name="twitter:card" content="summary_large_image">
<style>{_PAGE_CSS}</style>
</head>
<body><main>
<p class="meta"><a href="{_esc(base)}/">GitHub 破千周榜</a> / 第 {no} 期</p>
<h1>{_esc(title)}</h1>
<p class="meta">本周共 {w['total_breakthroughs'] or '—'} 个项目突破 1000 Star，
精选 {len(w['finalists'])} 个 · 由 AI 解读</p>
<div class="box"><div class="eyebrow">本周看点</div><p class="hl">{_esc(hl.get('headline', ''))}</p>
<ul>{points}</ul></div>
<h2>完整榜单（{len(w['finalists'])} 个）</h2>
<ol>
{''.join(items)}
</ol>
<p><a href="{_esc(base)}/#w={_esc(w['id'])}">查看交互版（筛选 / 走势 / 完整解读）→</a></p>
<p class="meta">项目介绍由大模型根据 GitHub 公开信息与 README 生成，可能存在偏差 ·
数据与源码：<a href="https://github.com/fhan235/github1K">github1K</a> ·
<a href="{_esc(base)}/feed.xml">RSS 订阅</a></p>
</main></body>
</html>
"""


def _render_day_page(d: dict, base: str) -> str:
    title = f"{d['date']} GitHub 破千日报"
    desc = d.get("headline") or f"当天 {len(d['projects'])} 个项目突破 1000 Star"
    url = f"{base}/d/{d['date']}/"
    items = []
    for p in d["projects"][:50]:
        line = p.get("one_liner") or (p.get("description") or "")[:60]
        meta = [f"⭐ {p['stars'] or '—'}"]
        if p.get("gained"):
            meta.append(f"当日 +{p['gained']:,}")
        items.append(
            f'<li><a href="{_esc(p["url"])}">{_esc(p["name"])}</a>'
            f' <span class="t">{_esc(line)}</span>'
            f' <span class="meta">{" · ".join(_esc(m) for m in meta)}</span></li>'
        )
    points = "".join(f"<li>{_esc(p)}</li>" for p in d.get("points", []))
    box = ""
    if points or d.get("headline"):
        box = (
            f'<div class="box"><div class="eyebrow">今日看点</div>'
            f'<p class="hl">{_esc(d.get("headline", ""))}</p><ul>{points}</ul></div>'
        )
    more = ""
    if len(d["projects"]) > 50:
        more = (
            f'<p class="meta">（共 {len(d["projects"])} 个，'
            f"此处列出增量前 50，完整列表见交互版）</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · github1K</title>
<meta name="description" content="{_esc(desc)}">
<link rel="canonical" href="{_esc(url)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{_esc(url)}">
<meta property="og:image" content="{_esc(base)}/assets/og.png">
<meta name="twitter:card" content="summary_large_image">
<style>{_PAGE_CSS}</style>
</head>
<body><main>
<p class="meta"><a href="{_esc(base)}/">GitHub 破千周榜</a> / 日报</p>
<h1>{_esc(title)}</h1>
<p class="meta">当天 {len(d['projects'])} 个项目突破 1000 Star</p>
{box}
<ol>
{''.join(items)}
</ol>
{more}
<p><a href="{_esc(base)}/#v=daily&amp;d={_esc(d['date'])}">查看交互版 →</a></p>
</main></body>
</html>
"""


def _render_feed(weeks: list[dict], base: str) -> str:
    items = []
    # weeks 是最新在前；RSS 里新条目在前，期号 = 总期数 - 序号（最早的是第 1 期）
    total = len(weeks)
    for i, w in enumerate(weeks):
        no = total - i
        hl = w.get("highlights") or {}
        desc = hl.get("headline", "")
        top = "；".join(
            f"{p['name']}（{(p.get('intro') or {}).get('one_liner') or ''}）"
            for p in w["finalists"][:5]
        )
        body = _esc(desc + "\n" + top)
        end = datetime.fromisoformat(w["end"]).replace(tzinfo=timezone.utc)
        url = f"{base}/w/{w['id']}/"
        suffix = _esc("：" + desc[:40] if desc else "")
        items.append(
            f"<item><title>第 {no} 期（{w['start']} → {w['end']}）{suffix}</title>"
            f"<link>{_esc(url)}</link><guid isPermaLink=\"true\">{_esc(url)}</guid>"
            f"<pubDate>{format_datetime(end)}</pubDate>"
            f"<description>{body}</description></item>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>GitHub 破千周榜</title>
<link>{_esc(base)}/</link>
<description>每周精选刚突破 1000 Star 的 GitHub 新项目，AI 中文解读</description>
<language>zh-CN</language>
{''.join(items)}
</channel></rss>
"""


def _render_sitemap(weeks: list[dict], days: list[dict], base: str) -> str:
    urls = [f"<url><loc>{_esc(base)}/</loc></url>"]
    urls += [
        f"<url><loc>{_esc(base)}/w/{_esc(w['id'])}/</loc><lastmod>{w['end']}</lastmod></url>"
        for w in weeks
    ]
    urls += [
        f"<url><loc>{_esc(base)}/d/{_esc(d['date'])}/</loc><lastmod>{d['date']}</lastmod></url>"
        for d in days
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )


_ANALYTICS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


def _inject_index(out: Path, base: str, analytics: str) -> None:
    path = out / "index.html"
    page = path.read_text(encoding="utf-8").replace("__BASE_URL__", base)
    if analytics:
        if not _ANALYTICS_RE.match(analytics):
            raise SystemExit(f"--analytics 的值不合法：{analytics!r}")
        page = page.replace(
            "script-src 'self'",
            "script-src 'self' https://gc.zgo.at",
        ).replace(
            "connect-src 'self'",
            "connect-src 'self' https://*.goatcounter.com",
        ).replace(
            "</body>",
            f'<script data-goatcounter="https://{analytics}.goatcounter.com/count" '
            f'async src="https://gc.zgo.at/count.js"></script>\n</body>',
        )
    path.write_text(page, encoding="utf-8")


def build(out: Path, created_since: str, base_url: str, analytics: str = "") -> int:
    out = out.resolve()
    if out == ROOT or out in ROOT.parents:
        raise SystemExit(f"拒绝清空输出目录：{out}")
    if not WEB_DIR.is_dir():
        raise SystemExit(f"缺少前端模板目录：{WEB_DIR}")

    weeks = [w for w in map(_build_week, sorted(WEEKLY_DIR.glob("weekly-*.json"))) if w]
    weeks.sort(key=lambda w: w["end"], reverse=True)
    days = [
        d
        for d in map(_build_day, sorted((DATA_DIR / "daily").glob("milestones_*.json.gz")))
        if d
    ]
    days.sort(key=lambda d: d["date"], reverse=True)

    # 日报 ↔ 周榜互链
    day_set = {d["date"] for d in days}
    week_by_name = {
        p["name"]: w["id"] for w in weeks for p in w["finalists"]
    }
    for w in weeks:
        for p in w["finalists"]:
            p["daily_page"] = bool(p.get("first_seen") and p["first_seen"] in day_set)
    for d in days:
        for p in d["projects"]:
            p["week"] = week_by_name.get(p["name"])

    snapshots = SnapshotIndex(DATA_DIR, created_since)
    if len(snapshots):
        _attach_sparklines(weeks, snapshots)
        _attach_sparks([(d["projects"], _daily_spark_dates(d["date"])) for d in days], snapshots)
    else:
        print(
            f"⚠️  未找到 created-since={created_since} 的快照，跳过走势曲线",
            file=sys.stderr,
        )

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB_DIR, out)
    (out / ".nojekyll").write_text("", encoding="utf-8")

    for w in weeks:
        _dump(w, out / "data" / "weeks" / f"{w['id']}.json")

    for d in days:
        _dump(d, out / "data" / "daily" / f"{d['date']}.json")
    _dump(
        {
            "days": [
                {
                    "date": d["date"],
                    "count": len(d["projects"]),
                    "gained_total": d["gained_total"],
                    "unreliable": d["unreliable"],
                    "has_digest": d["has_digest"],
                }
                for d in days
            ]
        },
        out / "data" / "daily" / "index.json",
    )

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

    # 静态分享页 / SEO / RSS
    base = base_url.rstrip("/")
    for no, w in enumerate(reversed(weeks), 1):
        page = _render_week_page(w, no, base)
        (out / "w" / w["id"]).mkdir(parents=True, exist_ok=True)
        (out / "w" / w["id"] / "index.html").write_text(page, encoding="utf-8")
    for d in days:
        page = _render_day_page(d, base)
        (out / "d" / d["date"]).mkdir(parents=True, exist_ok=True)
        (out / "d" / d["date"] / "index.html").write_text(page, encoding="utf-8")
    (out / "feed.xml").write_text(_render_feed(weeks, base), encoding="utf-8")
    (out / "sitemap.xml").write_text(_render_sitemap(weeks, days, base), encoding="utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8"
    )
    og = ROOT / "docs" / "assets" / "screenshot.png"
    if og.exists():
        (out / "assets").mkdir(exist_ok=True)
        shutil.copyfile(og, out / "assets" / "og.png")
    _inject_index(out, base, analytics)
    return len(weeks)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 github1K 周榜静态站点")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录（默认 _site/）")
    parser.add_argument(
        "--created-since",
        default=os.environ.get("G1K_CREATED_SINCE", "2020-01-01"),
        help="使用哪一组每日快照画走势（默认 2020-01-01，与日榜配置一致）",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("G1K_SITE_BASE_URL", "https://fhan235.github.io/github1K"),
        help="站点根地址（用于 OG 标签、RSS、sitemap 的绝对链接）",
    )
    parser.add_argument(
        "--analytics",
        default=os.environ.get("G1K_GOATCOUNTER", ""),
        help="GoatCounter 站点代码（如 mysite）；留空不加访问统计",
    )
    args = parser.parse_args()
    if args.created_since and not _DATE_RE.match(args.created_since):
        parser.error("--created-since 必须是 YYYY-MM-DD")
    n = build(args.out, args.created_since, args.base_url, args.analytics)
    print(f"✅ 站点已生成：{args.out.resolve()}（共 {n} 期周榜）")


if __name__ == "__main__":
    main()
