"""快照差异分析工具。

提供可复用的函数来分析两个快照文件的差异并发送企业微信推送。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from src.models import Milestone1KRepo
from src.notifiers.wecom import send_wecom


def load_snapshot_data(snapshot_path: str | Path) -> dict[str, int]:
    """加载快照文件数据。

    Parameters
    ----------
    snapshot_path : str | Path
        快照文件路径

    Returns
    -------
    dict[str, int]
        {仓库全名: star数量} 的字典
    """
    path = Path(snapshot_path)
    if not path.exists():
        raise FileNotFoundError(f"快照文件不存在: {snapshot_path}")

    if path.suffix == ".gz":
        import gzip

        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    else:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

    return data["repos"]


def compare_snapshots(
    newer_snapshot_path: str | Path,
    older_snapshot_path: str | Path,
    newer_date: date | None = None,
    older_date: date | None = None,
) -> list[Milestone1KRepo]:
    """比较两个快照文件，找出新增的1k star项目。

    Parameters
    ----------
    newer_snapshot_path : str | Path
        较新的快照文件路径
    older_snapshot_path : str | Path
        较旧的快照文件路径
    newer_date : date, optional
        较新快照的日期，用于判断是否为新创建项目
    older_date : date, optional
        较旧快照的日期

    Returns
    -------
    list[Milestone1KRepo]
        新增的1k star项目列表
    """
    # 加载快照数据
    newer_stars = load_snapshot_data(newer_snapshot_path)
    older_stars = load_snapshot_data(older_snapshot_path)

    # 从文件名提取日期（如果未提供）
    if newer_date is None:
        newer_date = _extract_date_from_filename(newer_snapshot_path)
    if older_date is None:
        older_date = _extract_date_from_filename(older_snapshot_path)

    milestones = []

    # 只比较两个快照中都存在的项目，避免数据采集范围不一致的问题
    common_repos = set(newer_stars.keys()) & set(older_stars.keys())

    for full_name in common_repos:
        today_stars = newer_stars[full_name]
        yesterday_count = older_stars[full_name]

        if today_stars < 1000:
            continue

        if yesterday_count < 1000:
            # 只有两个快照中都存在，且从<1000增长到>=1000的项目才算作新增
            gained = today_stars - yesterday_count

            # 创建Milestone1KRepo对象（简化版，缺少一些信息）
            milestones.append(
                Milestone1KRepo(
                    full_name=full_name,
                    url=f"https://github.com/{full_name}",
                    description="",  # 需要额外信息才能获取描述
                    language=None,  # 需要额外信息才能获取语言
                    stars_today=today_stars,
                    stars_yesterday=yesterday_count,
                    stars_gained=gained,
                    forks=0,
                    topics=[],
                    created_at=None,
                    updated_at=None,
                    unknown_yesterday=False,
                    is_recently_created=False,  # 需要创建时间信息才能判断
                )
            )

    milestones.sort(key=lambda r: r.stars_today, reverse=True)
    return milestones


def _parse_snapshot_filename(snapshot_path: str | Path) -> tuple[date, date | None]:
    """从快照文件名中提取运行日期和 created_since 范围。"""
    path = Path(snapshot_path)
    filename = path.name

    # 移除后缀
    for suffix in [".json.gz", ".json"]:
        if filename.endswith(suffix):
            filename = filename[: -len(suffix)]

    if not filename.startswith("snapshot_"):
        raise ValueError(f"无法从文件名 {path.name} 中提取日期")

    rest = filename[len("snapshot_"):]
    date_str, sep, created_part = rest.partition("_created-since-")
    snapshot_date = date.fromisoformat(date_str)
    created_since = date.fromisoformat(created_part) if sep else None
    return snapshot_date, created_since


def _extract_date_from_filename(snapshot_path: str | Path) -> date:
    """从快照文件名中提取日期。"""
    return _parse_snapshot_filename(snapshot_path)[0]


def send_snapshot_diff_to_wecom(
    newer_snapshot_path: str | Path,
    older_snapshot_path: str | Path,
    webhook_url: str | None = None,
) -> bool:
    """比较两个快照并发送差异到企业微信。

    Parameters
    ----------
    newer_snapshot_path : str | Path
        较新的快照文件路径
    older_snapshot_path : str | Path
        较旧的快照文件路径
    webhook_url : str, optional
        企业微信Webhook URL，如果为None则使用配置中的默认URL

    Returns
    -------
    bool
        是否发送成功
    """
    # 比较快照
    milestones = compare_snapshots(newer_snapshot_path, older_snapshot_path)

    # 从文件名提取日期
    newer_date = _extract_date_from_filename(newer_snapshot_path)

    if not milestones:
        print(f"在 {newer_date} 相比之前没有新增的1k star项目")
        # 使用告警推送发送无新增项目的消息
        from src.notifiers.wecom import send_wecom_alert

        title = f"GitHub 1K 突破榜 {newer_date.isoformat()}"
        common_count = len(
            set(load_snapshot_data(newer_snapshot_path).keys())
            & set(load_snapshot_data(older_snapshot_path).keys())
        )
        message = (
            "📊 今日没有新增突破1k star的项目\n\n"
            "分析范围:\n"
            f"- 较新快照: {Path(newer_snapshot_path).name}\n"
            f"- 较旧快照: {Path(older_snapshot_path).name}\n"
            f"- 共同项目数: {common_count}"
        )
        return send_wecom_alert(title, message, webhook_url)

    print(f"发现 {len(milestones)} 个新增1k star项目")

    # 发送企业微信推送
    return send_wecom(milestones, newer_date, webhook_url)


def get_snapshot_diff_summary(
    newer_snapshot_path: str | Path,
    older_snapshot_path: str | Path,
) -> dict[str, Any]:
    """获取快照差异的统计摘要。

    Parameters
    ----------
    newer_snapshot_path : str | Path
        较新的快照文件路径
    older_snapshot_path : str | Path
        较旧的快照文件路径

    Returns
    -------
    dict[str, Any]
        包含统计信息的字典
    """
    milestones = compare_snapshots(newer_snapshot_path, older_snapshot_path)

    if not milestones:
        return {
            "total_new_milestones": 0,
            "top_projects": [],
            "max_stars": 0,
            "avg_stars": 0,
        }

    # 统计信息
    total = len(milestones)
    max_stars = max(r.stars_today for r in milestones)
    avg_stars = sum(r.stars_today for r in milestones) / total

    # 前10个项目
    top_projects = [
        {
            "rank": i + 1,
            "full_name": repo.full_name,
            "stars_today": repo.stars_today,
            "stars_gained": repo.stars_gained,
            "url": repo.url,
        }
        for i, repo in enumerate(milestones[:10])
    ]

    return {
        "total_new_milestones": total,
        "top_projects": top_projects,
        "max_stars": max_stars,
        "avg_stars": round(avg_stars, 1),
    }


def find_latest_snapshots(data_dir: str | Path = "data") -> tuple[Path | None, Path | None]:
    """在数据目录中查找最新的两个快照文件。

    Parameters
    ----------
    data_dir : str | Path
        数据目录路径

    Returns
    -------
    tuple[Path | None, Path | None]
        (最新快照路径, 次新快照路径)，如果找不到则返回(None, None)
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        return None, None

    # 查找所有快照文件
    snapshot_files: list[tuple[date, date | None, Path]] = []
    for pattern in ["snapshot_*.json", "snapshot_*.json.gz"]:
        for path in data_path.glob(pattern):
            try:
                snapshot_date, created_since = _parse_snapshot_filename(path)
                snapshot_files.append((snapshot_date, created_since, path))
            except ValueError:
                continue

    if not snapshot_files:
        return None, None

    created_since_values = {item[1] for item in snapshot_files}
    if None in created_since_values:
        selected_created_since = None
    else:
        selected_created_since = min(d for d in created_since_values if d is not None)

    selected_files = [
        item for item in snapshot_files if item[1] == selected_created_since
    ]
    selected_files.sort(key=lambda x: x[0], reverse=True)

    if len(selected_files) >= 2:
        return selected_files[0][2], selected_files[1][2]
    else:
        return selected_files[0][2], None


# 命令行接口
def main():
    """命令行接口示例。"""
    import argparse

    parser = argparse.ArgumentParser(description="比较两个快照文件并发送企业微信推送")

    # 使用互斥组来处理两种使用方式
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("newer_snapshot", nargs="?", help="较新的快照文件路径")
    group.add_argument("--latest", action="store_true", help="自动查找最新的两个快照文件")

    parser.add_argument("older_snapshot", nargs="?", help="较旧的快照文件路径")
    parser.add_argument("--webhook", help="企业微信Webhook URL")
    parser.add_argument("--summary", action="store_true", help="只显示统计摘要，不发送推送")

    args = parser.parse_args()

    if args.latest:
        newer_path, older_path = find_latest_snapshots()
        if newer_path is None:
            print("❌ 找不到任何快照文件")
            return
        if older_path is None:
            print("❌ 只找到一个快照文件，需要至少两个文件进行比较")
            return

        print("自动选择快照文件:")
        print(f"  较新: {newer_path.name}")
        print(f"  较旧: {older_path.name}")
    else:
        if not args.newer_snapshot or not args.older_snapshot:
            parser.error("当不使用--latest时，必须提供newer_snapshot和older_snapshot参数")
        newer_path = Path(args.newer_snapshot)
        older_path = Path(args.older_snapshot)

    if not newer_path.exists():
        print(f"❌ 文件不存在: {newer_path}")
        return
    if not older_path.exists():
        print(f"❌ 文件不存在: {older_path}")
        return

    if args.summary:
        # 只显示统计摘要
        summary = get_snapshot_diff_summary(newer_path, older_path)
        print("\n📊 快照差异统计摘要:")
        print(f"   新增1k star项目总数: {summary['total_new_milestones']}")
        print(f"   最高star数: {summary['max_stars']:,}")
        print(f"   平均star数: {summary['avg_stars']:,}")

        if summary["top_projects"]:
            print(f"\n🏆 Top {len(summary['top_projects'])} 项目:")
            for project in summary["top_projects"]:
                print(
                    f"   {project['rank']}. {project['full_name']} - "
                    f"{project['stars_today']:,} ⭐ "
                    f"(+{project['stars_gained']:,})"
                )
    else:
        # 发送企业微信推送
        success = send_snapshot_diff_to_wecom(newer_path, older_path, args.webhook)

        if success:
            print("✅ 企业微信推送成功")
        else:
            print("❌ 企业微信推送失败")


if __name__ == "__main__":
    main()
