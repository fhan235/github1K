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
    """Personal Access Token（强烈推荐：认证后 Search API 30次/分钟，匿名仅 10次/分钟）"""

    # ── 通知 ────────────────────────────────────────────────────
    wecom_webhook_url: str = ""
    """企业微信 Webhook，留空则不推送"""

    # ── 报告 ────────────────────────────────────────────────────
    report_top_n: int = 0
    """报告展示前 N 条（0 = 全部展示）"""


settings = Settings()
