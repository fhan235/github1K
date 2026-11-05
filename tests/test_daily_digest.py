"""日报 AI 摘要的单元测试。"""
from __future__ import annotations

from src.daily_digest import (
    DailyDigestItem,
    _daily_facts,
    digest_daily_projects,
)


class _FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def chat_json(self, model, system, user):
        self.calls += 1
        return self.payload


def _repo(name: str, gained: int | None = 10, reliable: bool = True) -> dict:
    return {
        "full_name": name,
        "description": "desc",
        "language": "Python",
        "topics": [],
        "stars_today": 1000,
        "stars_gained": gained,
        "gain_reliable": reliable,
    }


def test_digest_batches_and_sanitizes_output():
    client = _FakeClient(
        {
            "results": [
                {"full_name": "a/x", "category": "not-a-category", "one_liner": "  好东西  "},
                {"full_name": "b/y", "category": "dev-tools", "one_liner": ""},
                {"full_name": 123, "category": "game", "one_liner": "x"},
                {"bad": True},
            ]
        }
    )
    out = digest_daily_projects(client, "m", [_repo("a/x"), _repo("b/y")])
    assert out["a/x"].category == "other"  # 非法类别回落
    assert out["a/x"].one_liner == "好东西"  # 去空白
    assert "b/y" not in out  # 空定位丢弃
    assert len(out) == 1


def test_daily_facts_only_counts_reliable_gains():
    items = {"a/x": DailyDigestItem(category="ai-agent", one_liner="x")}
    repos = [
        _repo("a/x", 500),
        _repo("b/y", 9999, reliable=False),  # 伪增量不参与排名
        _repo("c/z", None),
    ]
    facts = _daily_facts("2026-11-01", repos, items)
    assert facts["project_count"] == 3
    assert facts["category_counts"] == {"ai-agent": 1}
    assert facts["top_gainers"] == [{"full_name": "a/x", "gained": 500}]
