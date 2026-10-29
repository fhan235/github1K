"""周榜数据源：结构化 JSON 优先，Markdown 报告解析兜底。

数据链路（按优先级）：
1. 本地 ``data/daily/milestones_*.json.gz``（日榜 CI 每天提交回仓库）
2. COS 上的同名 JSON（日榜 CI 同步上传，``{BASE_URL}/data/daily/`` 前缀）
3. COS / 本地的完整 Markdown 报告（``milestone-1k-*.md``）—— 历史数据兜底
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from datetime import date
from pathlib import Path

import httpx

from src.config import settings
from src.models import DailyMilestones
from src.storage import milestone_store
from src.storage.snapshot_store import build_created_since_suffix
from src.weekly.models import DailyEntry

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
_REPORTS_DIR = _ROOT / "reports"

# ── 报告解析 ─────────────────────────────────────────────────────────────

# > 统计区间：2026-05-26 → 2026-05-27
_RANGE_RE = re.compile(
    r"统计区间：\s*(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})"
)
# ### 🥇 [owner/repo](https://github.com/owner/repo)
_ENTRY_RE = re.compile(
    r"^###\s+(?:🥇|🥈|🥉|#\d+)\s+\[([^\]]+)\]\((https://github\.com/[^)\s]+)\)"
)
# ⭐ **1,000** 星  （昨天 999，增量 **+1**）  `Python`  🆕 *新项目*
_STARS_RE = re.compile(
    r"^⭐\s+\*\*([\d,]+)\*\*\s+星\s+（昨天\s+([\d,]+|—)，增量\s+\*\*([+-]?[\d,]+)\*\*）(.*)$"
)
_FORKS_RE = re.compile(r"🍴\s+([\d,]+)\s+forks")
_CREATED_RE = re.compile(r"📅\s+创建于\s+(\d{4}-\d{2}-\d{2})")
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def _to_int(s: str) -> int:
    return int(s.replace(",", ""))


def parse_milestone_report(text: str, report_date: date) -> list[DailyEntry]:
    """解析一份完整报告，返回条目列表。解析失败时抛 ValueError。"""
    baseline_date: date | None = None
    m = _RANGE_RE.search(text)
    if m:
        baseline_date = date.fromisoformat(m.group(1))

    entries: list[DailyEntry] = []
    current: dict | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None and "stars" in current:
            entries.append(
                DailyEntry(
                    report_date=report_date,
                    baseline_date=baseline_date,
                    **current,
                )
            )
        current = None

    for line in text.splitlines():
        line = line.rstrip()

        em = _ENTRY_RE.match(line)
        if em:
            _flush()
            current = {"full_name": em.group(1).strip(), "url": em.group(2).strip()}
            continue
        if current is None:
            continue

        sm = _STARS_RE.match(line)
        if sm:
            current["stars"] = _to_int(sm.group(1))
            yday_raw = sm.group(2)
            current["stars_yesterday"] = None if yday_raw == "—" else _to_int(yday_raw)
            current["gained"] = _to_int(sm.group(3))
            rest = sm.group(4)
            lang = _BACKTICK_RE.search(rest)
            current["language"] = lang.group(1) if lang else None
            current["is_recently_created"] = "🆕" in rest
            current["unknown_yesterday"] = "❓" in rest or yday_raw == "—"
            continue

        if line.startswith("> ") and "description" not in current:
            current["description"] = line[2:].strip()
            continue

        if line.startswith("🏷️"):
            current["topics"] = _BACKTICK_RE.findall(line)
            continue

        fm = _FORKS_RE.search(line)
        if fm:
            current["forks"] = _to_int(fm.group(1))
        cm = _CREATED_RE.search(line)
        if cm:
            current["created_at"] = cm.group(1)

    _flush()
    return entries


# ── 结构化 JSON 读取（首选数据源）──────────────────────────────────────────


def milestones_to_entries(ms: DailyMilestones, report_date: date) -> list[DailyEntry]:
    """把结构化日榜转换为周榜内部的 DailyEntry。"""
    baseline = date.fromisoformat(ms.baseline_date) if ms.baseline_date else None
    return [
        DailyEntry(
            full_name=r.full_name,
            url=r.url,
            description=r.description,
            language=r.language,
            stars=r.stars_today,
            gained=r.stars_gained if r.stars_gained is not None else 0,
            stars_yesterday=r.stars_yesterday if not r.unknown_yesterday else None,
            unknown_yesterday=r.unknown_yesterday,
            is_recently_created=r.is_recently_created,
            forks=r.forks,
            topics=r.topics,
            created_at=r.created_at,
            report_date=report_date,
            baseline_date=baseline,
        )
        for r in ms.repos
    ]


def _cos_json_urls(d: date, created_since: date | None) -> list[str]:
    base = settings.report_public_base_url.strip().rstrip("/")
    if not base:
        return []
    suffix = build_created_since_suffix(created_since)
    urls = [f"{base}/data/daily/milestones_{d.isoformat()}{suffix}.json.gz"]
    if suffix:
        urls.append(f"{base}/data/daily/milestones_{d.isoformat()}.json.gz")
    return urls


def _fetch_json_from_cos(
    d: date, created_since: date | None, client: httpx.Client
) -> DailyMilestones | None:
    for url in _cos_json_urls(d, created_since):
        try:
            resp = client.get(url)
        except httpx.RequestError as exc:
            logger.warning("COS JSON 请求失败 %s: %s", url, exc)
            continue
        if resp.status_code != 200:
            continue
        try:
            return milestone_store.parse_milestones_payload(
                json.loads(gzip.decompress(resp.content).decode("utf-8"))
            )
        except Exception as exc:
            logger.warning("COS JSON 解析失败 %s: %s", url, exc)
    return None


# ── Markdown 报告获取（历史数据兜底）───────────────────────────────────────


def _cos_urls(d: date, created_since: date | None) -> list[str]:
    base = settings.report_public_base_url.strip().rstrip("/")
    if not base:
        return []
    suffix = build_created_since_suffix(created_since)
    urls = [f"{base}/reports/milestone-1k-{d.isoformat()}{suffix}.md"]
    if suffix:  # 兼容早期无后缀的报告
        urls.append(f"{base}/reports/milestone-1k-{d.isoformat()}.md")
    return urls


def _local_paths(d: date, created_since: date | None) -> list[Path]:
    suffix = build_created_since_suffix(created_since)
    paths = [_REPORTS_DIR / f"milestone-1k-{d.isoformat()}{suffix}.md"]
    if suffix:
        paths.append(_REPORTS_DIR / f"milestone-1k-{d.isoformat()}.md")
    return paths


def fetch_report_text(
    d: date,
    created_since: date | None,
    client: httpx.Client | None = None,
) -> str | None:
    """拉取某天的完整报告文本；找不到返回 None。"""
    for url in _cos_urls(d, created_since):
        try:
            own_client = client is None
            c = client or httpx.Client(timeout=settings.http_timeout, follow_redirects=True)
            try:
                resp = c.get(url)
            finally:
                if own_client:
                    c.close()
            if resp.status_code == 200:
                logger.info("COS 命中: %s", url)
                return resp.text
            if resp.status_code not in (403, 404):
                logger.warning("COS 请求异常 %s: HTTP %d", url, resp.status_code)
        except httpx.RequestError as exc:
            logger.warning("COS 请求失败 %s: %s", url, exc)

    for path in _local_paths(d, created_since):
        if path.exists():
            logger.info("本地命中: %s", path)
            return path.read_text(encoding="utf-8")
    return None


def fetch_daily_entries(
    days: list[date],
    created_since: date | None,
) -> tuple[dict[date, list[DailyEntry]], list[date]]:
    """批量拉取一周数据：本地 JSON → COS JSON → Markdown 报告兜底。

    Returns
    -------
    (entries_by_date, missing_days)
    """
    entries_by_date: dict[date, list[DailyEntry]] = {}
    missing: list[date] = []
    with httpx.Client(timeout=settings.http_timeout, follow_redirects=True) as client:
        for d in days:
            # 1. 本地结构化 JSON（仓库提交的 data/daily/）
            ms = milestone_store.load_milestones(d, created_since)
            source_label = "本地 JSON"

            # 2. COS 结构化 JSON
            if ms is None:
                ms = _fetch_json_from_cos(d, created_since, client)
                source_label = "COS JSON"

            if ms is not None:
                entries_by_date[d] = milestones_to_entries(ms, d)
                logger.info("%s 命中: %s（%d 条）", source_label, d, len(ms.repos))
                continue

            # 3. Markdown 兜底（历史数据）
            text = fetch_report_text(d, created_since, client=client)
            if text is None:
                missing.append(d)
                continue
            try:
                entries_by_date[d] = parse_milestone_report(text, d)
                logger.info("Markdown 兜底: %s（%d 条）", d, len(entries_by_date[d]))
            except Exception as exc:  # 解析失败视为当天缺失，不炸整条流水线
                logger.warning("解析 %s 报告失败: %s", d, exc)
                missing.append(d)
    return entries_by_date, missing
