"""时区工具：所有"今天"的概念统一为北京时间（Asia/Shanghai, UTC+8）。

为什么要这个模块？
------------------
GitHub Actions runner 默认在 UTC 时区运行，直接调用 ``date.today()``
会得到 UTC 当天日期；当 BJT 06:00 触发任务时（对应 UTC 前一天 22:00），
``date.today()`` 会返回**前一天**，导致快照、报告、日志的命名与运行
所属的"那一天"（用户视角）错位一天。

通过本模块统一获取 BJT 视角的"今天"，所有调用 ``date.today()`` 的位置
都应替换为 ``today_bjt()``，确保文件命名与人类直觉一致。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# 北京时间固定 UTC+8（无夏令时），不依赖系统时区也能稳定工作。
BJT = timezone(timedelta(hours=8))


def now_bjt() -> datetime:
    """返回当前北京时间（带 tz 信息）。"""
    return datetime.now(tz=BJT)


def today_bjt() -> date:
    """返回北京时间视角下的今天日期。"""
    return now_bjt().date()
