# github1K

> 每日自动追踪在「昨天」突破 **1000 Star** 的 GitHub 项目。

## 核心逻辑

- 每天运行一次，抓取当前 GitHub 上 `stars >= 1000` 的全量仓库（最多 1000 条）
- 与**昨天的快照**做差分：
  - 昨天 `stars < 1000`（或尚无记录）**且**今天 `stars >= 1000` → 纳入统计
- 不限制 Star 增量上限——无论今天涨了 100 还是 10000，只要昨天不足 1000、今天达到 1000 就算

## 快速开始

```bash
# 1. 安装
cd github1K
pip install -e .

# 2. 配置（填写 GitHub Token）
cp .env.example .env  # 编辑 .env 填入 G1K_GITHUB_TOKEN

# 3. 运行
python -m src.main

# 带企业微信通知
python -m src.main --notify

# 只展示 Top 20
python -m src.main -n 20
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `G1K_GITHUB_TOKEN` | GitHub PAT（强烈推荐，提升速率限制） | `""` |
| `G1K_WECOM_WEBHOOK_URL` | 企业微信 Webhook（留空则不推送） | `""` |
| `G1K_PER_PAGE` | 每页条数（最大 100） | `100` |
| `G1K_MAX_PAGES` | 最多翻页数（Search API 上限 10 页 = 1000 条） | `10` |
| `G1K_REPORT_TOP_N` | 报告展示前 N 条（0 = 全部） | `0` |

## 自动化

通过 GitHub Actions 每天 **BJT 09:00** 自动运行，报告和快照自动提交回仓库。

需要在仓库 Settings → Secrets 中添加：
- `G1K_GITHUB_TOKEN`
- `G1K_WECOM_WEBHOOK_URL`（可选）

## 输出

- `reports/milestone-1k-YYYY-MM-DD.md` — Markdown 格式的每日报告
- `data/snapshot_YYYY-MM-DD.json` — 每日 Star 快照（保留 30 天）
