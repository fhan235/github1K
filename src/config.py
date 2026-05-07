"""全局配置，通过 .env 或环境变量注入（前缀 G1K_）。"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="G1K_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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

    # ── 爬虫参数（可通过环境变量覆盖，方便调试）──────────────────
    request_interval: float = 2.0
    """API 请求间隔（秒）。30次/分钟的 Search API 限额 → 2.0s 精确节流"""

    above_upper: int = 50000
    """突破区上界，一天涨幅极少超过此值"""

    candidate_lower: int = 500
    """候选区下界。距离 1000 差值大于此阈值的仓库不追踪"""

    viral_max_pages: int = 10
    """爆款补漏区最大翻页数"""

    http_max_retries: int = 3
    """HTTP 请求失败时的最大重试次数"""

    http_timeout: int = 30
    """HTTP 请求超时秒数"""

    # ── 存储 ────────────────────────────────────────────────────
    snapshot_keep_days: int = 30
    """快照保留天数"""

    snapshot_compact: bool = True
    """快照 JSON 是否紧凑保存（不缩进），大幅减小体积"""


settings = Settings()
