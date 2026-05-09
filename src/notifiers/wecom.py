"""企业微信 Webhook 通知。"""
from __future__ import annotations

from datetime import date

import httpx
from rich.console import Console

from src.config import settings
from src.models import Milestone1KRepo

console = Console()

_MAX_BYTES = 4096  # WeCom Markdown 单条消息上限


def _build_markdown(
    repos: list[Milestone1KRepo],
    run_date: date,
    top_n: int = 10,
    full_report_url: str | None = None,
) -> str:
    display = repos[:top_n]
    lines = [
        f"## 🚀 GitHub 1K 突破榜 {run_date.isoformat()}",
        f"> 今日共 **{len(repos)}** 个项目突破 1000 Star，展示 Top {len(display)}\n",
    ]
    if full_report_url:
        lines.append(f"> [查看完整报告]({full_report_url})\n")
    for idx, repo in enumerate(display, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"#{idx}")
        gained = (
            f"+{repo.stars_gained:,}"
            if repo.stars_gained > 0
            else str(repo.stars_gained)
        )
        desc = (
            (repo.description[:60] + "…")
            if len(repo.description) > 60
            else repo.description
        )
        lang = f" `{repo.language}`" if repo.language else ""
        flag = ""
        if repo.is_recently_created:
            flag = " 🆕"
        elif repo.unknown_yesterday:
            flag = " ❓"
        lines.append(
            f"{medal} **[{repo.full_name}]({repo.url})**{lang}{flag}\n"
            f"  ⭐ {repo.stars_today:,}（{gained}）  {desc}"
        )
    return "\n".join(lines)


def send_wecom(
    repos: list[Milestone1KRepo],
    run_date: date,
    webhook_url: str | None = None,
    full_report_url: str | None = None,
) -> bool:
    """推送到企业微信，超长自动缩减 top_n。

    Parameters
    ----------
    webhook_url :
        自定义 webhook，缺省读取 settings.wecom_webhook_url。
        便于失败告警时注入另一个 webhook。
    """
    url = webhook_url or settings.wecom_webhook_url
    if not url:
        console.print("[dim]WeCom Webhook 未配置，跳过推送[/dim]")
        return False

    top_n = max(settings.summary_top_n, 3)
    content = _build_markdown(repos, run_date, top_n, full_report_url)
    while top_n >= 3 and len(content.encode("utf-8")) > _MAX_BYTES:
        top_n -= 1
        content = _build_markdown(repos, run_date, top_n, full_report_url)

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        resp = httpx.post(url, json=payload, timeout=15)
        data = resp.json()
        if data.get("errcode") == 0:
            console.print(f"[green]✅ WeCom 推送成功（Top {top_n}）[/green]")
            return True
        console.print(f"[red]WeCom 推送失败: {data}[/red]")
        return False
    except Exception as exc:
        console.print(f"[red]WeCom 推送异常: {exc}[/red]")
        return False


def send_wecom_alert(title: str, message: str, webhook_url: str | None = None) -> bool:
    """纯文本告警推送，用于 CI 失败通知。"""
    url = webhook_url or settings.wecom_webhook_url
    if not url:
        return False
    content = f"## ⚠️ {title}\n\n{message}"
    payload = {"msgtype": "markdown", "markdown": {"content": content[:_MAX_BYTES]}}
    try:
        resp = httpx.post(url, json=payload, timeout=15)
        return resp.json().get("errcode") == 0
    except Exception:
        return False
