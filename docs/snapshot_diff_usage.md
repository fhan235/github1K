# 快照差异分析工具使用说明

## 功能概述

`snapshot_diff.py` 是一个可复用的工具模块，用于分析两个GitHub快照文件之间的差异，找出新增的1k star项目，并支持企业微信推送功能。

## 主要功能

1. **快照差异分析**：比较两个时间点的快照，找出新达到1k star的项目
2. **企业微信推送**：将差异结果推送到企业微信
3. **统计摘要**：生成详细的统计信息
4. **自动查找**：自动查找最新的快照文件

## 使用方法

### 1. 基本用法（比较指定文件）

```python
from src.utils.snapshot_diff import send_snapshot_diff_to_wecom

# 比较两个快照文件并发送推送
success = send_snapshot_diff_to_wecom(
    "data/snapshot_2026-05-08.json",
    "data/snapshot_2026-04-26.json"
)
```

### 2. 获取统计摘要

```python
from src.utils.snapshot_diff import get_snapshot_diff_summary

# 获取差异统计信息
summary = get_snapshot_diff_summary(
    "data/snapshot_2026-05-08.json",
    "data/snapshot_2026-04-26.json"
)

print(f"新增项目数: {summary['total_new_milestones']}")
print(f"最高star数: {summary['max_stars']}")
print(f"平均star数: {summary['avg_stars']}")

# 查看Top项目
for project in summary['top_projects']:
    print(f"{project['rank']}. {project['full_name']} - {project['stars_today']} ⭐")
```

### 3. 自动查找最新快照

```python
from src.utils.snapshot_diff import find_latest_snapshots

# 自动查找最新的两个快照文件
newer_path, older_path = find_latest_snapshots("data")

if newer_path and older_path:
    print(f"最新快照: {newer_path.name}")
    print(f"次新快照: {older_path.name}")
    
    # 比较这两个快照
    milestones = compare_snapshots(newer_path, older_path)
    print(f"发现 {len(milestones)} 个新增1k star项目")
```

## 命令行接口

### 基本用法

```bash
# 比较两个指定文件并发送推送
python -m src.utils.snapshot_diff data/snapshot_2026-05-08.json data/snapshot_2026-04-26.json
```

### 只显示统计摘要

```bash
# 只显示统计信息，不发送推送
python -m src.utils.snapshot_diff data/snapshot_2026-05-08.json data/snapshot_2026-04-26.json --summary
```

### 自动查找最新快照

```bash
# 自动查找最新的两个快照文件进行比较
python -m src.utils.snapshot_diff --latest
```

### 使用自定义Webhook

```bash
# 使用指定的企业微信Webhook URL
python -m src.utils.snapshot_diff data/snapshot_2026-05-08.json data/snapshot_2026-04-26.json --webhook "https://qyapi.weixin.qq.com/..."
```

## 配置要求

### 环境变量配置

在 `.env` 文件中配置企业微信Webhook：

```bash
G1K_WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-webhook-key
```

### 文件路径要求

- 快照文件应位于 `data/` 目录下
- 文件名格式应为 `snapshot_YYYY-MM-DD.json` 或 `snapshot_YYYY-MM-DD.json.gz`
- 使用创建时间过滤时，也支持 `snapshot_YYYY-MM-DD_created-since-YYYY-MM-DD.json` 或 `.json.gz`

## 示例输出

### 统计摘要示例

```
📊 快照差异统计摘要:
   新增1k star项目总数: 2627
   最高star数: 50,000
   平均star数: 1,245.3

🏆 Top 10 项目:
   1. microsoft/vscode - 50,000 ⭐ (+12,345)
   2. facebook/react - 45,678 ⭐ (+8,901)
   ...
```

### 企业微信推送示例

推送内容包含：
- 标题：GitHub 1K 突破榜
- Top 10 新增项目列表
- 项目名称、star数量、增量信息
- 项目链接（可点击跳转）

## 错误处理

- 如果快照文件不存在，会抛出 `FileNotFoundError`
- 如果企业微信推送失败，会返回 `False` 并打印错误信息
- 如果找不到任何快照文件，会返回 `None`

## 集成到其他项目

可以将此模块集成到其他Python项目中：

```python
import sys
sys.path.insert(0, "/path/to/github1k/src")

from src.utils.snapshot_diff import send_snapshot_diff_to_wecom

# 在定时任务中使用
if __name__ == "__main__":
    success = send_snapshot_diff_to_wecom(
        "data/snapshot_today.json",
        "data/snapshot_yesterday.json"
    )
    
    if success:
        print("推送成功")
    else:
        print("推送失败")
```

## 注意事项

1. 确保企业微信Webhook配置正确
2. 快照文件需要包含完整的仓库信息
3. 推送内容有长度限制（4096字节），会自动调整显示项目数量
4. 支持压缩格式的快照文件（.json.gz）