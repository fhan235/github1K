# github1K

> 每日自动追踪在「昨天」突破 **1000 Star** 的 GitHub 项目。

## 核心逻辑

### 边界区快速扫描（日常模式，3-6 分钟）

不做全量扫描（那需要 30-60 分钟），只扫两个边界区：

```
【突破区】stars:1000..50000   ← 今天刚过 1000 或一夜爆火的项目都在这里
     ↕ 与昨日快照差分 → 找出"昨天 <1000，今天 >=1000"的突破项目

【候选区】stars:500..999      ← 离 1000 还差一点的项目，存快照供明天差分

【爆款区】stars:>50000        ← 一夜暴涨到超高星的现象级项目（几秒搞定）
```

- 语言 × 创建时间 自适应二分，绕开 Search API 单次 1000 条上限
- 不限制 Star 增量上限——昨天 500 今天 50000 的爆涨项目也能捕获
- 所有网络请求自带指数退避重试，单次失败不影响整体

### 冷启动（仅首次，耗时较长）

首次运行无昨日快照时自动进入全量扫描（`stars:>=1000` + 爆款补漏），建立完整基线。
之后每天自动切换为快速模式。

## 快速开始

```bash
# 1. 安装
cd github1K
pip install -e .

# 2. 配置（复制模板后编辑）
cp .env.example .env
# 然后编辑 .env 填入 G1K_GITHUB_TOKEN

# 3. 首次运行（冷启动，建立基线快照，耗时较长）
python -m src.main --cold-start

# 4. 之后每天运行（快速模式，3-6 分钟）
python -m src.main

# 带企业微信通知
python -m src.main --notify

# 只展示 Top 20
python -m src.main -n 20

# DEBUG 日志
python -m src.main -v
```

## 环境变量

所有变量以 `G1K_` 为前缀，可在 `.env` 或环境中注入。详见 `.env.example`。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `G1K_GITHUB_TOKEN` | GitHub PAT（强烈推荐，认证后 30次/分钟） | `""` |
| `G1K_WECOM_WEBHOOK_URL` | 企业微信 Webhook（留空则不推送） | `""` |
| `G1K_REPORT_TOP_N` | 报告展示前 N 条（0 = 全部） | `0` |
| `G1K_REQUEST_INTERVAL` | API 请求间隔秒数（30/min 配 2.0s） | `2.0` |
| `G1K_ABOVE_UPPER` | 突破区上界 Star 数 | `50000` |
| `G1K_CANDIDATE_LOWER` | 候选区下界 Star 数 | `500` |
| `G1K_HTTP_MAX_RETRIES` | HTTP 请求失败最大重试次数 | `3` |
| `G1K_SNAPSHOT_KEEP_DAYS` | 快照保留天数 | `30` |
| `G1K_SNAPSHOT_COMPACT` | 快照 JSON 紧凑保存 | `true` |

## 自动化

通过 GitHub Actions 每天 **BJT 09:00** 左右自动运行（GitHub Actions 定时任务可能延迟 5-30 分钟），报告和快照自动提交回仓库；CI 失败时会通过企业微信告警。

需要在仓库 Settings → Secrets 中添加：
- `G1K_GITHUB_TOKEN`
- `G1K_WECOM_WEBHOOK_URL`（可选，但强烈推荐：用于失败告警和每日推送）

手动运行冷启动：仓库 Actions → Daily 1K Milestone Tracker → Run workflow → 勾选 "全量冷启动"。

## 输出

- `reports/milestone-1k-YYYY-MM-DD.md` — Markdown 格式的每日报告
- `data/snapshot_YYYY-MM-DD.json` — 每日 Star 快照（保留 30 天，紧凑 JSON）

## 测试

```bash
pip install -e '.[dev]'
pytest
```

## 安全提示

`.env` 文件包含 GitHub PAT，**禁止提交**。`.gitignore` 已配置忽略。
若不慎将 token 提交到 Git 历史，请立即前往 <https://github.com/settings/tokens> 撤销并重新签发。
