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

# 5. 找创建时间在2020-01-01后的项目
python -m src.main --created-since 2020-01-01

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
| `G1K_SUMMARY_TOP_N` | 摘要报告和企业微信展示前 N 条 | `20` |
| `G1K_REPORT_PUBLIC_BASE_URL` | 完整报告公开访问基础地址，例如腾讯云 COS 域名 | `""` |
| `G1K_CREATED_SINCE` | 仅扫描此日期之后创建的仓库，例如 `2020-01-01` 表示 `created:>2020-01-01` | `2020-01-01` |
| `G1K_REQUEST_INTERVAL` | API 请求间隔秒数（30/min 配 2.0s） | `2.0` |
| `G1K_ABOVE_UPPER` | 突破区上界 Star 数 | `50000` |
| `G1K_CANDIDATE_LOWER` | 候选区下界 Star 数 | `500` |
| `G1K_HTTP_MAX_RETRIES` | HTTP 请求失败最大重试次数 | `3` |
| `G1K_SNAPSHOT_KEEP_DAYS` | 快照保留天数 | `30` |
| `G1K_SNAPSHOT_COMPACT` | 快照 JSON 紧凑保存 | `true` |

## 自动化

通过 GitHub Actions 每天 **BJT 09:00** 左右自动运行（GitHub Actions 定时任务可能延迟 5-30 分钟）。完整报告和快照会上传到 Actions Artifact；仓库只提交轻量摘要报告和压缩快照，避免 Git 历史被大文件撑大；CI 失败时会通过企业微信告警。

需要在仓库 Settings → Secrets 中添加：
- `G1K_GITHUB_TOKEN`
- `G1K_WECOM_WEBHOOK_URL`（可选，但强烈推荐：用于失败告警和每日推送）

可选：如果要上传完整报告到腾讯云 COS，需要继续添加：
- `TENCENT_SECRET_ID`
- `TENCENT_SECRET_KEY`
- `TENCENT_COS_BUCKET`
- `TENCENT_COS_REGION`

需要在仓库 Settings → Secrets and variables → Actions → Variables 中添加：
- `G1K_REPORT_PUBLIC_BASE_URL`：完整报告公开访问基础地址，例如 `https://your-bucket-1250000000.cos.ap-guangzhou.myqcloud.com`
- `G1K_CREATED_SINCE`（可选）：默认创建时间过滤范围

手动运行冷启动：仓库 Actions → Daily 1K Milestone Tracker → Run workflow → 勾选 "全量冷启动"。

## 输出

- `reports/milestone-1k-YYYY-MM-DD.md` — 完整 Markdown 报告，只上传 Actions Artifact / 腾讯云 COS，不提交仓库
- `reports/summary-1k-YYYY-MM-DD.md` — 轻量摘要报告，会提交回仓库，也适合企业微信推送
- `data/snapshot_YYYY-MM-DD.json.gz` — 每日 Star 压缩快照，会提交回仓库，用于下一天差分
- 使用 `--created-since YYYY-MM-DD` 时，报告、快照和日志文件名会追加 `_created-since-YYYY-MM-DD` 后缀，避免不同扫描范围混用。

## 腾讯云 COS 配置

1. 登录腾讯云控制台，进入对象存储 COS，创建一个 Bucket，例如 `github1k-reports-1250000000`。
2. 选择离你最近的地域，例如广州地域对应 `ap-guangzhou`。这个地域值就是 `TENCENT_COS_REGION`。
3. 如果希望企业微信里的完整报告链接可直接打开，把 Bucket 访问权限设为公有读私有写，或绑定自定义 CDN/域名后开放读取。
4. 进入访问管理 CAM，创建一个子用户或访问密钥，授予该 Bucket 的对象读写权限。不要使用主账号长期密钥。
5. 在 GitHub 仓库 Settings → Secrets and variables → Actions → Secrets 中添加：
   - `TENCENT_SECRET_ID`：腾讯云访问密钥 ID
   - `TENCENT_SECRET_KEY`：腾讯云访问密钥 Key
   - `TENCENT_COS_BUCKET`：Bucket 名，例如 `github1k-reports-1250000000`
   - `TENCENT_COS_REGION`：地域，例如 `ap-guangzhou`
6. 在 Variables 中添加 `G1K_REPORT_PUBLIC_BASE_URL`，通常是 Bucket 访问域名，例如 `https://github1k-reports-1250000000.cos.ap-guangzhou.myqcloud.com`。
7. 之后 Actions 每次成功运行时，会把完整报告上传到 COS 的 `reports/` 目录，把压缩快照上传到 `data/` 目录；企业微信会推送摘要和完整报告链接。

## 测试

```bash
pip install -e '.[dev]'
pytest
```

## 安全提示

`.env` 文件包含 GitHub PAT，**禁止提交**。`.gitignore` 已配置忽略。
若不慎将 token 提交到 Git 历史，请立即前往 <https://github.com/settings/tokens> 撤销并重新签发。
