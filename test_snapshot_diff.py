#!/usr/bin/env python3
"""
测试快照差异分析功能
"""

import sys
from pathlib import Path

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.utils.snapshot_diff import send_snapshot_diff_to_wecom


def main():
    """测试5月8号和4月26号快照的差异"""
    newer_snapshot = "data/snapshot_2026-05-08.json"
    older_snapshot = "data/snapshot_2026-04-26.json"

    print(f"比较快照: {newer_snapshot} vs {older_snapshot}")

    # 检查文件是否存在
    newer_path = Path(newer_snapshot)
    older_path = Path(older_snapshot)

    if not newer_path.exists():
        print(f"错误: 文件 {newer_snapshot} 不存在")
        return
    if not older_path.exists():
        print(f"错误: 文件 {older_snapshot} 不存在")
        return

    # 发送企业微信推送
    success = send_snapshot_diff_to_wecom(newer_snapshot, older_snapshot)

    if success:
        print("✅ 测试成功！企业微信推送已发送")
    else:
        print("❌ 测试失败，请检查企业微信配置")

if __name__ == "__main__":
    main()
