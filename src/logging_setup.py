"""日志初始化工具。

职责
----
1. 控制台：保留 RichHandler 的彩色输出。
2. 文件：每天一个 ``logs/run-YYYY-MM-DD.log``，追加写入；UTF-8；多次运行自动分段。
3. 过滤掉 HTTPX / urllib3 / httpcore 的低价值 HTTP 请求日志（避免日志被
   ``HTTP Request: GET ...`` 这种信息淹没）。
4. 提供 ``log_console_line`` 帮助函数，把 Rich 的步骤分隔/状态输出也同步到日志文件，
   这样日志文件能还原完整运行脉络。
5. 自动清理超过 ``settings.log_keep_days`` 天的旧日志。
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

from src.config import settings

# ── 过滤 HTTP 噪音 ──────────────────────────────────────────────
# 形如：HTTP Request: GET https://api.github.com/... "HTTP/1.1 200 OK"
_HTTP_NOISE_PATTERN = re.compile(r"HTTP Request:\s+(GET|POST|PUT|DELETE|PATCH|HEAD)\s+")

# 这几个库的 INFO 级日志基本都是 HTTP 细节，直接调到 WARNING 静音
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "requests")


class _DropHttpNoiseFilter(logging.Filter):
    """丢弃 ``HTTP Request: GET ...`` 这类请求日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return _HTTP_NOISE_PATTERN.search(msg) is None


# 供主程序复用的文件 logger（把 Console 输出也同步到日志文件）
_console_file_logger: Optional[logging.Logger] = None


def setup_logging(console: Console, verbose: bool = False) -> Path:
    """配置 root logger，返回当天日志文件路径。

    Parameters
    ----------
    console :
        Rich Console 实例，用于控制台彩色输出。
    verbose :
        ``True`` → DEBUG 级别；否则 INFO 级别。
    """
    global _console_file_logger

    level = logging.DEBUG if verbose else logging.INFO

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run-{date.today():%Y-%m-%d}.log"

    # ── Rich 控制台 handler ──
    rich_handler = RichHandler(
        console=console, rich_tracebacks=True, show_path=False
    )
    rich_handler.setLevel(level)
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))

    # ── 文件 handler（人类可读的纯文本） ──
    file_handler = logging.FileHandler(
        log_path, mode="a", encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # 过滤 HTTP 噪音（只作用于文件；控制台本身也加一份，避免终端被刷屏）
    noise_filter = _DropHttpNoiseFilter()
    file_handler.addFilter(noise_filter)
    rich_handler.addFilter(noise_filter)

    # ── 配置 root logger（覆盖旧 handlers，避免多次调用重复输出） ──
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)
    root.addHandler(rich_handler)
    root.addHandler(file_handler)

    # 静音 HTTP 库
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # 创建一个只写文件的 logger，给 log_console_line 使用
    _console_file_logger = logging.getLogger("github1k.console")
    _console_file_logger.setLevel(level)
    _console_file_logger.propagate = False  # 不重复进 rich handler（控制台自己 print）
    _console_file_logger.handlers.clear()
    _console_file_logger.addHandler(file_handler)

    # 分隔符标明新一次运行
    _console_file_logger.info("=" * 72)
    _console_file_logger.info(
        "新运行开始 @ %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    _console_file_logger.info("=" * 72)

    return log_path


_RICH_MARKUP_RE = re.compile(r"\[/?[^\[\]]+?\]")


def _strip_rich_markup(s: str) -> str:
    """去掉 Rich 的 ``[bold cyan]...[/bold cyan]`` 等标签，得到纯文本。"""
    return _RICH_MARKUP_RE.sub("", s)


def log_console_line(text: str, *, level: int = logging.INFO) -> None:
    """把一行 Rich 控制台文本（去除标记后）写入日志文件。

    用法：配合 ``console.print(...)`` / ``console.rule(...)`` 同步使用。
    """
    if _console_file_logger is None:
        return
    clean = _strip_rich_markup(str(text)).strip()
    if not clean:
        return
    _console_file_logger.log(level, clean)


def cleanup_old_logs(keep_days: int | None = None) -> int:
    """清理超过 keep_days 天的日志文件。返回清理条数。"""
    days = settings.log_keep_days if keep_days is None else keep_days
    if days <= 0:
        return 0
    log_dir = Path(settings.log_dir)
    if not log_dir.is_dir():
        return 0

    cutoff = date.today() - timedelta(days=days)
    removed = 0
    for path in log_dir.glob("run-*.log"):
        stem = path.stem  # run-YYYY-MM-DD
        try:
            d = datetime.strptime(stem[4:], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed
