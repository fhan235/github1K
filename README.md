# github1K

> 每日自动追踪在「昨天」突破 **1000 Star** 的 GitHub 项目。

## 核心逻辑

### 边界区快速扫描（日常模式，3-6 分钟）

不做全量扫描（那需要 30-60 分钟），只扫两个边界区：

```
【突破区】stars:1000..50000   ← 今天刚过 1000 或一夜爆火的项目都在这里
     ↕ 与昨日快照差分 → 找出"昨天 <1000，今天 >=1000"的突破项目

【候选区】stars:800..999      ← 离 1000 还差一点的项目，存快照供明天差分
```

- 语言 × 创建时间 自适应二分，绕开 Search API 单次 1000 条上限
- 不限制 Star 增量上限——昨天 500 今天 50000 的爆涨项目也能捕获

### 冷启动（仅首次，耗时较长）

首次运行无昨日快照时自动进入全量扫描（`stars:>=1000`），建立完整基线。
之后每天自动切换为快速模式。

## 快速开始

```bash
# 1. 安装
cd github1K
pip install -e .

# 2. 配置（编辑 .env 填入 G1K_GITHUB_TOKEN）

# 3. 首次运行（冷启动，建立基线快照，耗时较长）
python -m src.main --cold-start

# 4. 之后每天运行（快速模式，3-6 分钟）
python -m src.main

# 带企业微信通知
python -m src.main --notify

# 只展示 Top 20
python -m src.main -n 20
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `G1K_GITHUB_TOKEN` | GitHub PAT（强烈推荐，认证后 30次/分钟） | `""` |
| `G1K_WECOM_WEBHOOK_URL` | 企业微信 Webhook（留空则不推送） | `""` |
| `G1K_REPORT_TOP_N` | 报告展示前 N 条（0 = 全部） | `0` |

## 自动化

通过 GitHub Actions 每天 **BJT 09:00** 自动运行，报告和快照自动提交回仓库。

需要在仓库 Settings → Secrets 中添加：
- `G1K_GITHUB_TOKEN`
- `G1K_WECOM_WEBHOOK_URL`（可选）

## 输出

- `reports/milestone-1k-YYYY-MM-DD.md` — Markdown 格式的每日报告
- `data/snapshot_YYYY-MM-DD.json` — 每日 Star 快照（保留 30 天）
