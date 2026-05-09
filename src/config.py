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
    """Personal Access Token（强烈推荐：认证后 Search API 30次/分钟，匿名仅 10次/分钟）。

    单 token 场景使用此字段。
    若需多 token 轮询加速，请改填 ``G1K_GITHUB_TOKENS``（逗号分隔）。
    """

    github_tokens: str = ""
    """多个 PAT，以英文逗号分隔（可选）。

    每个 token 享有独立的 30次/分钟 限额，
    通过轮询最早可用的 token 实现并行节流，冷启动可成倍提速。
    留空时自动回落到 ``github_token``。
    """

    @property
    def token_list(self) -> list[str]:
        """返回去重后的 token 列表；若全部为空则返回空列表（匿名访问）。"""
        raw: list[str] = []
        if self.github_tokens:
            raw.extend(self.github_tokens.split(","))
        if self.github_token:
            raw.append(self.github_token)
        seen: set[str] = set()
        out: list[str] = []
        for tok in raw:
            t = tok.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    # ── 通知 ────────────────────────────────────────────────────
    wecom_webhook_url: str = ""
    """企业微信 Webhook，留空则不推送"""

    # ── 报告 ────────────────────────────────────────────────────
    report_top_n: int = 0
    """完整报告展示前 N 条（0 = 全部展示）"""

    summary_top_n: int = 20
    """摘要报告和企业微信默认展示前 N 条"""

    report_public_base_url: str = ""
    """完整报告公开访问基础地址，例如腾讯云 COS 自定义域名或默认访问域名。"""

    # ── 爬虫参数（可通过环境变量覆盖，方便调试）──────────────────
    created_since: str = ""
    """仅扫描此日期之后创建的仓库（YYYY-MM-DD，留空表示不限制）。"""

    request_interval: float = 2.0
    """单 token 下的 API 请求间隔（秒）。30次/分钟的 Search API 限额 → 2.0s 精确节流。

    使用 N 个 token 轮询时，整体吞吐自动提升 N 倍（每个 token 仍按此间隔节流），
    无需手动调小此值。
    """

    above_upper: int = 50000
    """突破区上界，一天涨幅极少超过此值"""

    candidate_lower: int = 500
    """候选区下界。距离 1000 差值大于此阈值的仓库不追踪"""

    http_max_retries: int = 3
    """HTTP 请求失败时的最大重试次数"""

    http_timeout: int = 30
    """HTTP 请求超时秒数"""

    # ── 存储 ────────────────────────────────────────────────────
    snapshot_keep_days: int = 30
    """快照保留天数"""

    snapshot_compact: bool = True
    """快照 JSON 是否紧凑保存（不缩进），大幅减小体积"""

    # ── 日志 ────────────────────────────────────────────────────
    log_dir: str = "logs"
    """运行日志目录（自动创建）。按日期拆分，每次运行追加。"""

    log_keep_days: int = 30
    """日志保留天数，超过自动清理。0 = 永不清理。"""


settings = Settings()
