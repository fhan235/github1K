"""周报发布：上传 HTML 到腾讯云 COS，返回公开访问链接。

密钥仅从环境变量（``G1K_COS_SECRET_ID`` 等）读取；未配置时优雅跳过，
不影响本地周报生成。CI 里复用日榜已有的 ``TENCENT_*`` Secrets（在
weekly.yml 中映射为 ``G1K_COS_*`` 注入）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.config import settings

logger = logging.getLogger(__name__)


def cos_configured() -> bool:
    return all(
        [
            settings.cos_secret_id,
            settings.cos_secret_key,
            settings.cos_bucket,
            settings.cos_region,
            settings.report_public_base_url.strip(),
        ]
    )


def upload_report(html_path: Path) -> str | None:
    """上传周报 HTML 到 COS 的 reports/weekly/ 前缀，返回公开 URL。

    未配置或上传失败时返回 None（调用方降级为不带链接的推送）。
    """
    if not cos_configured():
        logger.info("未配置 COS（G1K_COS_*），跳过上传")
        return None

    # 延迟导入：没装 SDK 或未配置时不影响其他功能
    from qcloud_cos import CosConfig, CosS3Client

    cos_key = f"reports/weekly/{html_path.name}"
    try:
        client = CosS3Client(
            CosConfig(
                Region=settings.cos_region,
                SecretId=settings.cos_secret_id,
                SecretKey=settings.cos_secret_key,
            )
        )
        client.put_object(
            Bucket=settings.cos_bucket,
            Key=cos_key,
            Body=html_path.read_bytes(),
            ContentType="text/html; charset=utf-8",
        )
    except Exception as exc:  # SDK 异常类型众多，上传失败不应炸掉流水线
        logger.warning("COS 上传失败: %s", exc)
        return None

    base = settings.report_public_base_url.strip().rstrip("/")
    url = f"{base}/{cos_key}"
    logger.info("周报已上传: %s", url)
    return url
