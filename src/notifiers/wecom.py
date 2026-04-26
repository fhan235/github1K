"""企业微信 Webhook 通知。"""
from __future__ import annotations

from datetime import date

import httpx
from rich.console import Console

from src.config import settings
from src.models import Milestone1KRepo

console = Console()

_MAX_BYTES = 4096  # WeCom Markdown 单条消息上限


def _build_markdown(repos: list[Milestone1KRepo], run_date: date, top_n: int = 10) -> str:
    display = repos[:top_n]
    lines = [
        f"## 🚀 GitHub 1K 突破榜 {run_date.isoformat()}",
        f"> 今日共 **{len(repos)}** 个项目突破 1000 Star，展示 Top {len(display)}\n",
    ]
    for idx, repo in enumerate(display, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"#{idx}")
        gained = f"+{repo.stars_gained:,}" if repo.stars_gained > 0 else str(repo.stars_gained)
        desc = (repo.description[:60] + "…") if len(repo.description) > 60 else repo.description
        lang = f" `{repo.language}`" if repo.language else ""
        lines.append(
            f"{medal} **[{repo.full_name}]({repo.url})**{lang}\n"
            f"  ⭐ {repo.stars_today:,}（{gained}）  {desc}"
        )
    return "\n".join(lines)


def send_wecom(repos: list[Milestone1KRepo], run_date: date) -> bool:
    """推送到企业微信，超长自动缩减 top_n。"""
    if not settings.wecom_webhook_url:
        console.print("[dim]WeCom Webhook 未配置，跳过推送[/dim]")
        return False

    top_n = 10
    while top_n >= 3:
        content = _build_markdown(repos, run_date, top_n)
        if len(content.encode("utf-8")) <= _MAX_BYTES:
            break
        top_n -= 1

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        resp = httpx.post(
            settings.wecom_webhook_url,
            json=payload,
            timeout=15,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            console.print(f"[green]✅ WeCom 推送成功（Top {top_n}）[/green]")
            return True
        else:
            console.print(f"[red]WeCom 推送失败: {data}[/red]")
            return False
    except Exception as exc:
        console.print(f"[red]WeCom 推送异常: {exc}[/red]")
        return False
