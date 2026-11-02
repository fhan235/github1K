"""LLM 配置回归测试：CI 中未定义的 vars.* 会以空字符串注入。"""
from __future__ import annotations

import pytest

from src.config import Settings
from src.weekly.llm import LLMClient


def test_empty_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("G1K_LLM_BASE_URL", "")
    monkeypatch.setenv("G1K_LLM_MODEL_WRITER", "")
    s = Settings(_env_file=None)
    assert s.llm_base_url == "https://api.deepseek.com"
    assert s.llm_model_writer == "deepseek-chat"


@pytest.mark.parametrize("bad", ["api.deepseek.com", "ftp://x.com", "https://"])
def test_invalid_base_url_fails_fast(bad):
    with pytest.raises(RuntimeError, match="G1K_LLM_BASE_URL"):
        LLMClient(api_key="k", base_url=bad)


def test_missing_key_fails_fast():
    with pytest.raises(RuntimeError, match="G1K_LLM_API_KEY"):
        LLMClient(api_key="")


def test_valid_base_url_trailing_slash_trimmed():
    c = LLMClient(api_key="k", base_url="https://api.deepseek.com/ ")
    assert c._base == "https://api.deepseek.com"
