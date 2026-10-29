"""REST 复查：对周候选补查最新元数据，并抓取 README（供 LLM 使用）。

- ``GET /repos/{owner}/{repo}``：最新 stars / forks / pushed_at / license /
  archived / fork 等，顺便算出「一周后是否还在涨」（weekly_gain）。
- ``GET /repos/{owner}/{repo}/readme``：只对最终入榜项目调用。

REST API 配额为 5000 次/小时，百余次请求一分钟内即可完成。
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from src.config import settings
from src.weekly.models import EnrichedCandidate, WeeklyCandidate

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com"
_REQUEST_INTERVAL = 0.3  # REST 配额宽裕，轻度节流即可

# README 清洗：badge 行、HTML 标签、图片
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BADGE_LINE_RE = re.compile(
    r"^\s*(\[?!\[|<a\s|<img|<p\s|!\().*(badge|shield|travis|circleci|codecov)",
    re.IGNORECASE,
)


def _token() -> str:
    tokens = settings.token_list
    return tokens[0] if tokens else ""


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _throttle(last_call: list[float]) -> None:
    wait = _REQUEST_INTERVAL - (time.time() - last_call[0])
    if wait > 0:
        time.sleep(wait)
    last_call[0] = time.time()


def clean_readme(text: str, max_chars: int | None = None) -> str:
    """剥掉 badge / HTML 注释 / 图片标签，折叠空行并截断。"""
    limit = max_chars or settings.weekly_readme_max_chars
    text = _HTML_COMMENT_RE.sub("", text)
    text = _IMG_TAG_RE.sub("", text)
    lines = [ln for ln in text.splitlines() if not _BADGE_LINE_RE.match(ln)]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) > limit:
        text = text[:limit] + "\n…(truncated)"
    return text


def fetch_readme(client: httpx.Client, full_name: str) -> str:
    """抓取并清洗 README，失败返回空串。"""
    try:
        resp = client.get(
            f"/repos/{full_name}/readme",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if resp.status_code != 200:
            return ""
        return clean_readme(resp.text)
    except httpx.RequestError as exc:
        logger.warning("README 获取失败 %s: %s", full_name, exc)
        return ""


def _parse_repo_json(data: dict) -> dict:
    license_info = data.get("license") or {}
    return {
        "enrich_ok": True,
        "current_stars": data.get("stargazers_count"),
        "current_forks": data.get("forks_count"),
        "pushed_at": data.get("pushed_at"),
        "license_spdx": license_info.get("spdx_id")
        if license_info.get("spdx_id") != "NOASSERTION"
        else None,
        "archived": bool(data.get("archived", False)),
        "is_fork": bool(data.get("fork", False)),
        "open_issues": data.get("open_issues_count"),
    }


def enrich_candidates(candidates: list[WeeklyCandidate]) -> list[EnrichedCandidate]:
    """对候选列表逐一复查最新元数据。单项失败不影响其他项。"""
    out: list[EnrichedCandidate] = []
    last_call = [0.0]
    with httpx.Client(
        base_url=_BASE_URL,
        headers=_headers(),
        timeout=settings.http_timeout,
        follow_redirects=True,
    ) as client:
        for c in candidates:
            _throttle(last_call)
            merged = c.model_dump()
            try:
                resp = client.get(f"/repos/{c.full_name}")
                if resp.status_code == 200:
                    merged.update(_parse_repo_json(resp.json()))
                elif resp.status_code in (404, 451):
                    merged["flags"] = [*merged.get("flags", []), "repo_gone"]
                    logger.info("仓库已不可访问: %s (HTTP %d)", c.full_name, resp.status_code)
                else:
                    logger.warning("复查失败 %s: HTTP %d", c.full_name, resp.status_code)
            except httpx.RequestError as exc:
                logger.warning("复查网络错误 %s: %s", c.full_name, exc)

            enriched = EnrichedCandidate(**merged)
            if enriched.enrich_ok and enriched.current_stars is not None:
                enriched.weekly_gain = enriched.current_stars - enriched.stars_at_first_seen
            out.append(enriched)
    return out


def make_readme_client() -> httpx.Client:
    """供 LLM 阶段按需抓取 README 的共享客户端（调用方负责 close）。"""
    return httpx.Client(
        base_url=_BASE_URL,
        headers=_headers(),
        timeout=settings.http_timeout,
        follow_redirects=True,
    )
