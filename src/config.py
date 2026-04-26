"""全局配置，通过 .env 或环境变量注入（前缀 G1K_）。"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="G1K_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ── GitHub API ──────────────────────────────────────────────
    github_token: str = ""
    """Personal Access Token（可选，但强烈推荐，能把速率限制从 10/min 提升到 30/min）"""

    per_page: int = 100
    """每次 Search API 请求返回的条目数（最大 100）"""

    max_pages: int = 10
    """最多翻页数（Search API 最多返回 1000 条 = 100×10）"""

    # ── 通知 ────────────────────────────────────────────────────
    wecom_webhook_url: str = ""
    """企业微信 Webhook，留空则不推送"""

    # ── 报告 ────────────────────────────────────────────────────
    report_top_n: int = 0
    """报告展示前 N 条（0 = 全部展示）"""


settings = Settings()
