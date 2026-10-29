"""快照速查工具：解压并查看 data/snapshot_*.json.gz 的内容。

设计动机
--------
为了节省仓库体积，每日快照默认以 ``.json.gz`` 形式存储；但调试时
经常需要肉眼看一眼内容。这个脚本提供几种轻量级的查看方式，避免
每次都手动 ``gunzip``。

典型用法
--------
::

    # 看摘要（条数 + Top 10）
    python -m src.tools.peek_snapshot 2026-05-26

    # 整份 JSON 打到 stdout，方便 | less / | jq
    python -m src.tools.peek_snapshot 2026-05-26 --full

    # 解压到 data/_peek/ 下成 .json，看完即弃（已被 .gitignore 排除）
    python -m src.tools.peek_snapshot 2026-05-26 --extract

    # 模糊搜索某个仓库
    python -m src.tools.peek_snapshot 2026-05-26 --grep affaan

    # 列出 data/ 目录下所有快照
    python -m src.tools.peek_snapshot --list
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PEEK_DIR = _DATA_DIR / "_peek"


def _find_snapshot(date_str: str, created_since: str | None) -> Path | None:
    """在 data/ 下找匹配 date 和 created_since 的快照文件。

    优先 ``.json.gz``，找不到再退回 ``.json``。``created_since`` 留空时，
    优先匹配带有任意 ``_created-since-*`` 后缀的文件（最常用的形式），
    再退回纯 ``snapshot_<date>.*``。
    """
    suffixes = [".json.gz", ".json"]

    # 显式指定 created_since
    if created_since:
        stem = f"snapshot_{date_str}_created-since-{created_since}"
        for suf in suffixes:
            candidate = _DATA_DIR / f"{stem}{suf}"
            if candidate.exists():
                return candidate
        return None

    # 未指定：优先带 created-since 的（按字典序取第一个），再回退裸快照
    for suf in suffixes:
        candidates = sorted(_DATA_DIR.glob(f"snapshot_{date_str}_created-since-*{suf}"))
        if candidates:
            return candidates[0]
    for suf in suffixes:
        candidate = _DATA_DIR / f"snapshot_{date_str}{suf}"
        if candidate.exists():
            return candidate
    return None


def _load(path: Path) -> dict[str, Any]:
    """统一读取 ``.json`` / ``.json.gz``。"""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def cmd_list() -> int:
    """列出 data/ 下所有快照。"""
    if not _DATA_DIR.exists():
        console.print("[yellow]data/ 目录不存在[/yellow]")
        return 1

    rows: list[tuple[str, str, str]] = []
    for path in sorted(_DATA_DIR.glob("snapshot_*.*")):
        if path.is_dir():
            continue
        if path.suffix not in (".gz", ".json"):
            continue
        size_kb = path.stat().st_size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.2f} MB"
        rows.append((path.name, size_str, "压缩" if path.suffix == ".gz" else "原始"))

    if not rows:
        console.print("[yellow]data/ 下没有任何快照文件[/yellow]")
        return 0

    table = Table(title=f"📦 data/ 快照清单（共 {len(rows)} 份）", show_lines=False)
    table.add_column("文件名", style="cyan")
    table.add_column("体积", justify="right", style="green")
    table.add_column("格式", style="dim")
    for r in rows:
        table.add_row(*r)
    console.print(table)
    return 0


def cmd_summary(path: Path, top_n: int = 10) -> int:
    """打印快照摘要：条数 + Top N。"""
    data = _load(path)
    repos: dict[str, int] = data.get("repos", {})
    snapshot_date = data.get("date", "?")
    collected_at = data.get("collected_at", "?")

    console.print(
        f"[bold cyan]📅 快照日期[/bold cyan] {snapshot_date}  "
        f"[dim]采集时间 {collected_at}[/dim]"
    )
    console.print(
        f"[bold green]📊 条数[/bold green] {len(repos):,}  "
        f"[dim]来源 {path.name}[/dim]"
    )

    if not repos:
        console.print("[yellow]快照内 repos 为空[/yellow]")
        return 0

    top = sorted(repos.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    table = Table(title=f"⭐ Top {len(top)} 仓库", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("仓库", style="cyan")
    table.add_column("Stars", justify="right", style="yellow")
    for idx, (name, stars) in enumerate(top, 1):
        table.add_row(str(idx), name, f"{stars:,}")
    console.print(table)

    console.print(
        "[dim]💡 想看完整内容？试试 --full 或 --extract[/dim]"
    )
    return 0


def cmd_full(path: Path) -> int:
    """整份 JSON 打到 stdout，便于 | less / | jq。"""
    data = _load(path)
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_extract(path: Path) -> int:
    """把 .json.gz 解压一份到 data/_peek/ 下。"""
    _PEEK_DIR.mkdir(parents=True, exist_ok=True)

    if path.suffix == ".gz":
        out_name = path.name[: -len(".gz")]  # 去掉 .gz
    else:
        # 已经是 .json，仍然复制一份到 _peek 方便统一管理
        out_name = path.name

    out_path = _PEEK_DIR / out_name
    data = _load(path)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_kb = out_path.stat().st_size / 1024
    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.2f} MB"
    console.print(
        f"[green]✅ 已解压到[/green] [cyan]{out_path}[/cyan] "
        f"[dim]({size_str})[/dim]"
    )
    console.print(
        "[dim]💡 该目录已被 .gitignore 排除，看完不会污染仓库[/dim]"
    )
    return 0


def cmd_grep(path: Path, keyword: str) -> int:
    """在仓库名中模糊匹配关键词，打印命中条目。"""
    data = _load(path)
    repos: dict[str, int] = data.get("repos", {})
    keyword_lower = keyword.lower()

    hits = [
        (name, stars)
        for name, stars in repos.items()
        if keyword_lower in name.lower()
    ]
    hits.sort(key=lambda kv: kv[1], reverse=True)

    console.print(
        f"[bold cyan]🔎 关键词[/bold cyan] {keyword}  "
        f"[bold green]命中[/bold green] {len(hits)} / {len(repos):,}"
    )

    if not hits:
        return 0

    table = Table(show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("仓库", style="cyan")
    table.add_column("Stars", justify="right", style="yellow")
    for idx, (name, stars) in enumerate(hits[:50], 1):
        table.add_row(str(idx), name, f"{stars:,}")
    console.print(table)

    if len(hits) > 50:
        console.print(f"[dim]…仅展示前 50 条，剩余 {len(hits) - 50} 条已省略[/dim]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="peek_snapshot",
        description="查看 data/snapshot_*.json.gz 的内容（无需手动 gunzip）",
    )
    parser.add_argument(
        "date",
        nargs="?",
        help="快照日期，格式 YYYY-MM-DD。配合 --list 时可省略。",
    )
    parser.add_argument(
        "--created-since",
        default=None,
        help="可选：限定 created_since 后缀，例如 2020-01-01；省略时自动匹配。",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--list",
        action="store_true",
        help="列出 data/ 下所有快照文件。",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="把整份 JSON 打到 stdout（建议配合 | less 或 | jq）。",
    )
    mode.add_argument(
        "--extract",
        action="store_true",
        help="解压一份 .json 副本到 data/_peek/，方便编辑器查看。",
    )
    mode.add_argument(
        "--grep",
        metavar="KEYWORD",
        help="模糊搜索仓库名，打印命中条目。",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="摘要模式下展示的 Top N，默认 10。",
    )

    args = parser.parse_args(argv)

    if args.list:
        return cmd_list()

    if not args.date:
        parser.error("缺少 date 参数（除非使用 --list）")

    snapshot_path = _find_snapshot(args.date, args.created_since)
    if snapshot_path is None:
        console.print(
            f"[red]❌ 未找到 {args.date} 的快照[/red]  "
            f"[dim]试试 --list 看可用快照列表[/dim]"
        )
        return 1

    if args.full:
        return cmd_full(snapshot_path)
    if args.extract:
        return cmd_extract(snapshot_path)
    if args.grep:
        return cmd_grep(snapshot_path, args.grep)
    return cmd_summary(snapshot_path, top_n=args.top)


if __name__ == "__main__":
    sys.exit(main())
