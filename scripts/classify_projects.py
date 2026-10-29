#!/usr/bin/env python3
"""
项目分类整理脚本

功能：
  1. 读取指定日期范围内的 summary 报告（Markdown 表格）
  2. 去重合并所有项目（同一项目取 Star 最高的那条记录）
  3. 按预定义分类规则自动分类
  4. 输出一个整理好的总文件（Markdown）

用法：
  python scripts/classify_projects.py --start 2026-05-28 --end 2026-06-06
  python scripts/classify_projects.py --start 2026-05-28 --end 2026-06-06 --min-stars 1050
  python scripts/classify_projects.py --start 2026-05-28 --end 2026-06-06 -o content/weekly/week1.md
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# ─── 项目根目录 ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
OUTPUT_DIR = ROOT / "content" / "classified"


# ─── 数据结构 ─────────────────────────────────────────────────────────────────
@dataclass
class Project:
    """从 summary 表格中解析出的单个项目。"""

    full_name: str
    url: str
    stars: int
    gained: int
    language: str
    description: str
    report_date: str  # 来源报告日期
    is_new: bool = False  # 🆕 标记
    is_unknown_yesterday: bool = False  # ❓ 标记
    categories: list[str] = field(default_factory=list)


# ─── 分类规则 ─────────────────────────────────────────────────────────────────
# 每个分类由 (类别名, 匹配函数) 组成
# 匹配函数接收 Project，返回 True/False
# 一个项目可以属于多个分类，但最终会被归入第一个匹配的主分类

CATEGORIES: list[tuple[str, str, callable]] = []


def _kw_in(text: str, keywords: list[str]) -> bool:
    """检查 text 中是否包含任一关键词（不区分大小写）。"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _register_categories():
    """注册所有分类规则。"""
    global CATEGORIES

    # ── 1. AI Agent 基础设施 ──
    def is_agent_infra(p: Project) -> bool:
        # 核心关键词：真正的 Agent 基础设施层
        strong_keywords = [
            "sandbox", "mcp", "agent memory", "long-term memory",
            "agent-device", "capsule", "agent os", "operating system for ai",
            "agent runtime", "agent workflow engine", "orchestrat",
            "agent platform", "agent framework", "agent sdk",
            "coding agent", "dev agent", "ai agent",
        ]
        # 弱关键词：需要额外条件才算
        weak_keywords = ["agent", "agentic", "skill"]
        # 排除词：这些项目虽然包含 agent/skill 但不属于基础设施
        exclude_patterns = [
            "awesome", "curated", "collection", "合集", "商店",
            "job", "求职", "签到", "check-in", "trading", "投研",
            "roblox", "game", "illustration", "配图", "marketing",
            "social card", "小红书", "carousel", "ppt",
        ]
        desc_name = f"{p.description} {p.full_name}"
        # 如果命中排除词，直接不算
        if _kw_in(desc_name, exclude_patterns):
            return False
        # 强关键词直接命中
        if _kw_in(desc_name, strong_keywords):
            return True
        # 弱关键词需要同时有 sdk/runtime/platform/framework/hook/cli 等信号
        infra_signals = ["sdk", "runtime", "platform", "framework", "hook", "cli", "engine", "integration layer", "operating system"]
        if _kw_in(desc_name, weak_keywords) and _kw_in(desc_name, infra_signals):
            return True
        return False

    # ── 2. AI 模型 & 训练 & 推理 ──
    def is_ai_model(p: Project) -> bool:
        keywords = [
            "llm", "language model", "multimodal", "vision-language", "tts",
            "text-to-speech", "diffusion", "rl post training", "reinforcement learning",
            "world model", "foundation model", "inference", "fine-tun", "rag",
            "retrieval", "embedding", "watermark", "tokeniz",
            "transformer", "deepseek", "gpt", "claude", "gemini",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 3. 开发工具 & 工程效率 ──
    def is_dev_tools(p: Project) -> bool:
        keywords = [
            "cli", "editor", "ide", "terminal", "framework", "sdk",
            "compiler", "linter", "formatter", "build tool", "package manager",
            "docker", "container", "ci", "cd", "devops", "kubernetes",
            "database", "sql", "serializ", "validation", "testing",
            "debugg", "profil", "monitor", "observ", "tiling window",
            "window manager", "vm", "virtual machine", "coreutils",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 4. Web 框架 & 前端 & UI ──
    def is_web_frontend(p: Project) -> bool:
        keywords = [
            "web framework", "frontend", "ui component", "css", "react",
            "vue", "svelte", "next.js", "nuxt", "design system",
            "canvas", "wysiwyg", "generative ui", "transitions",
            "browser", "html",
        ]
        # 语言也是信号
        lang_signal = p.language.lower() in ["html", "vue", "css"] if p.language else False
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords) or lang_signal

    # ── 5. 身份认证 & 安全 & 隐私 ──
    def is_security(p: Project) -> bool:
        keywords = [
            "auth", "authentication", "identity", "security", "encrypt",
            "privacy", "vpn", "proxy", "firewall", "phishing", "blocklist",
            "anti-detect", "reverse engineer", "penetrat", "vulnerability",
            "0-day", "zero-day", "scanner", "逆向", "渗透", "安全",
            "sentinel", "threat", "triage", "patch",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 6. 内容创作 & 媒体工具 ──
    def is_content_media(p: Project) -> bool:
        keywords = [
            "video", "audio", "music", "image generat", "illustration",
            "ppt", "slide", "social media", "scheduler", "content",
            "xiaohongshu", "wechat", "公众号", "小红书", "carousel",
            "ffmpeg", "pixel art", "design", "demo", "mockup",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 7. 数据分析 & 金融 & 量化 ──
    def is_data_finance(p: Project) -> bool:
        keywords = [
            "data analy", "trading", "stock", "quant", "finance",
            "btc", "crypto", "mining", "investment", "账单", "金融",
            "equity research",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 8. 学习资源 & 教程 & 合集 ──
    def is_learning_resource(p: Project) -> bool:
        keywords = [
            "awesome", "curated", "guide", "tutorial", "learn",
            "cheatsheet", "resource", "course", "book", "paper",
            "指南", "教程", "合集", "商店", "collection",
            "skill合集", "skills 商店", "skill store",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 9. 自动化 & 工作流 & RPA ──
    def is_automation(p: Project) -> bool:
        keywords = [
            "automat", "workflow", "n8n", "scheduler", "cron",
            "bot", "scraper", "crawl", "rpa", "job appl",
            "签到", "check-in", "job search", "job hunt",
            "求职", "投递",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    # ── 10. 桌面应用 & 系统工具 ──
    def is_desktop_system(p: Project) -> bool:
        keywords = [
            "desktop", "macos", "windows", "linux", "electron",
            "tray", "launcher", "cleaner", "logitech", "keyboard",
            "compositor", "wayland", "homebrew", "window manag",
            "tiling", "keyviz", "按键", "blender", "home assistant",
            "obsidian", "note taking", "笔记",
        ]
        desc_name = f"{p.description} {p.full_name}"
        return _kw_in(desc_name, keywords)

    CATEGORIES = [
        ("🤖 AI Agent 基础设施", "Agent 运行时、沙箱、记忆、设备控制、MCP 协议等", is_agent_infra),
        ("🧠 AI 模型 & 训练 & 推理", "大模型、多模态、TTS、RAG、强化学习等", is_ai_model),
        ("🛠️ 开发工具 & 工程效率", "CLI、编辑器、框架、SDK、数据库工具、CI/CD 等", is_dev_tools),
        ("🌐 Web & 前端 & UI", "Web 框架、前端组件、画布、浏览器工具等", is_web_frontend),
        ("🔒 安全 & 认证 & 隐私", "身份认证、VPN、代理、扫描器、反检测等", is_security),
        ("🎨 内容创作 & 媒体工具", "视频、音频、PPT、社媒工具、设计等", is_content_media),
        ("📊 数据分析 & 金融 & 量化", "数据分析、交易、量化、加密货币等", is_data_finance),
        ("📚 学习资源 & 教程 & 合集", "Awesome 列表、指南、教程、论文合集等", is_learning_resource),
        ("⚙️ 自动化 & 工作流", "n8n、RPA、爬虫、定时任务、求职自动化等", is_automation),
        ("💻 桌面应用 & 系统工具", "桌面软件、系统工具、窗口管理、启动器等", is_desktop_system),
        ("📦 其他", "未归入以上分类的项目", lambda p: True),  # 兜底
    ]


_register_categories()


# ─── 解析 Summary 报告 ────────────────────────────────────────────────────────
# 表格行格式示例：
# | 🥇 | [mrkai77/Loop](https://github.com/mrkai77/Loop) ❓ | 10,800 | +10,800 | Swift | Window management made elegant. |
_TABLE_ROW_RE = re.compile(
    r"\|\s*(?:#?\d+|🥇|🥈|🥉)\s*\|"  # 排名列
    r"\s*\[([^\]]+)\]\(([^)]+)\)(.*?)\s*\|"  # 仓库名、URL、标记
    r"\s*([\d,]+)\s*\|"  # Stars
    r"\s*\+?([\d,]+)\s*\|"  # 增量
    r"\s*([^|]*?)\s*\|"  # 语言
    r"\s*(.*?)\s*\|"  # 说明
)


def parse_summary_file(filepath: Path) -> list[Project]:
    """解析单个 summary 报告文件，返回项目列表。"""
    text = filepath.read_text(encoding="utf-8")
    # 从文件名提取日期
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filepath.name)
    report_date = date_match.group(1) if date_match else "unknown"

    projects = []
    for match in _TABLE_ROW_RE.finditer(text):
        full_name = match.group(1).strip()
        url = match.group(2).strip()
        flags = match.group(3).strip()
        stars = int(match.group(4).replace(",", ""))
        gained = int(match.group(5).replace(",", ""))
        language = match.group(6).strip() or "—"
        description = match.group(7).strip()

        # 解析标记
        is_new = "🆕" in flags
        is_unknown = "❓" in flags

        projects.append(Project(
            full_name=full_name,
            url=url,
            stars=stars,
            gained=gained,
            language=language if language != "—" else "",
            description=description,
            report_date=report_date,
            is_new=is_new,
            is_unknown_yesterday=is_unknown,
        ))

    return projects


def collect_projects(start_date: date, end_date: date) -> list[Project]:
    """收集日期范围内所有 summary 报告中的项目，去重后返回。"""
    all_projects: dict[str, Project] = {}

    current = start_date
    while current <= end_date:
        # 尝试匹配文件名
        pattern = f"summary-1k-{current.isoformat()}_created-since-*.md"
        files = list(REPORTS_DIR.glob(pattern))
        if not files:
            # 也尝试不带 created-since 后缀的
            alt = REPORTS_DIR / f"summary-1k-{current.isoformat()}.md"
            if alt.exists():
                files = [alt]

        for f in files:
            projects = parse_summary_file(f)
            for p in projects:
                # 去重：同一项目保留 Star 数最高的记录
                if p.full_name not in all_projects or p.stars > all_projects[p.full_name].stars:
                    all_projects[p.full_name] = p

        current += timedelta(days=1)

    return list(all_projects.values())


# ─── 分类逻辑 ─────────────────────────────────────────────────────────────────
def classify_projects(projects: list[Project]) -> dict[str, list[Project]]:
    """对项目列表进行分类，返回 {分类名: [项目列表]}。"""
    classified: dict[str, list[Project]] = defaultdict(list)
    used: set[str] = set()

    for cat_name, _desc, match_fn in CATEGORIES:
        for p in projects:
            if p.full_name in used:
                continue
            if match_fn(p):
                p.categories.append(cat_name)
                classified[cat_name].append(p)
                used.add(p.full_name)

    return dict(classified)


# ─── 输出 Markdown ────────────────────────────────────────────────────────────
def generate_classified_report(
    classified: dict[str, list[Project]],
    start_date: date,
    end_date: date,
    total_count: int,
) -> str:
    """生成分类整理后的 Markdown 报告。"""
    lines: list[str] = []

    lines.append(f"# 📋 GitHub 1K Star 项目分类整理")
    lines.append("")
    lines.append(f"> 数据范围：{start_date.isoformat()} → {end_date.isoformat()}")
    lines.append(f"> 项目总数：**{total_count}** 个（去重后）")
    lines.append(f"> 数据来源：每日 summary 报告中的 Top 20 项目")
    lines.append("")

    # 目录
    lines.append("## 📑 目录")
    lines.append("")
    for cat_name, cat_desc, _ in CATEGORIES:
        if cat_name in classified and classified[cat_name]:
            count = len(classified[cat_name])
            lines.append(f"- **{cat_name}**（{count} 个）— {cat_desc}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 各分类详情
    for cat_name, cat_desc, _ in CATEGORIES:
        if cat_name not in classified or not classified[cat_name]:
            continue

        cat_projects = classified[cat_name]
        # 按 Star 数降序排列
        cat_projects.sort(key=lambda p: p.stars, reverse=True)

        lines.append(f"## {cat_name}")
        lines.append(f"> {cat_desc}")
        lines.append("")
        lines.append(f"共 **{len(cat_projects)}** 个项目")
        lines.append("")

        # 表格
        lines.append("| # | 项目 | ⭐ Stars | 增量 | 语言 | 说明 | 日期 |")
        lines.append("|--:|------|--------:|-----:|------|------|------|")

        for idx, p in enumerate(cat_projects, 1):
            lang = p.language or "—"
            desc = p.description.replace("|", "\\|")
            if len(desc) > 60:
                desc = desc[:57] + "…"
            flag = ""
            if p.is_new:
                flag = " 🆕"
            elif p.is_unknown_yesterday:
                flag = " ❓"
            lines.append(
                f"| {idx} | [{p.full_name}]({p.url}){flag} | "
                f"{p.stars:,} | +{p.gained:,} | {lang} | {desc} | {p.report_date} |"
            )

        lines.append("")
        lines.append("---")
        lines.append("")

    # 统计摘要
    lines.append("## 📈 统计摘要")
    lines.append("")
    lines.append("### 分类分布")
    lines.append("")
    lines.append("| 分类 | 项目数 | 占比 |")
    lines.append("|------|-------:|-----:|")
    for cat_name, _, _ in CATEGORIES:
        if cat_name in classified and classified[cat_name]:
            count = len(classified[cat_name])
            pct = count / total_count * 100
            lines.append(f"| {cat_name} | {count} | {pct:.1f}% |")
    lines.append("")

    # 语言统计
    lines.append("### 语言分布（Top 15）")
    lines.append("")
    lang_count: dict[str, int] = defaultdict(int)
    all_projects = []
    for ps in classified.values():
        all_projects.extend(ps)
    for p in all_projects:
        key = p.language or "Unknown"
        lang_count[key] += 1
    sorted_langs = sorted(lang_count.items(), key=lambda x: -x[1])[:15]
    lines.append("| 语言 | 项目数 |")
    lines.append("|------|-------:|")
    for lang, cnt in sorted_langs:
        lines.append(f"| {lang} | {cnt} |")
    lines.append("")

    # Star 分布
    lines.append("### Star 数分布")
    lines.append("")
    buckets = [
        (1000, 1500, "1K-1.5K"),
        (1500, 3000, "1.5K-3K"),
        (3000, 10000, "3K-10K"),
        (10000, 50000, "10K-50K"),
        (50000, 999999, "50K+"),
    ]
    lines.append("| 区间 | 项目数 |")
    lines.append("|------|-------:|")
    for lo, hi, label in buckets:
        cnt = sum(1 for p in all_projects if lo <= p.stars < hi)
        if cnt > 0:
            lines.append(f"| {label} | {cnt} |")
    lines.append("")

    lines.append("---")
    lines.append(f"*生成时间：脚本自动整理 · 数据范围 {start_date} ~ {end_date}*")

    return "\n".join(lines)


# ─── 主函数 ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="整理并分类指定日期范围内的 GitHub 1K Star 项目"
    )
    parser.add_argument(
        "--start", "-s", required=True,
        help="起始日期，格式 YYYY-MM-DD"
    )
    parser.add_argument(
        "--end", "-e", required=True,
        help="结束日期，格式 YYYY-MM-DD"
    )
    parser.add_argument(
        "--min-stars", type=int, default=0,
        help="最低 Star 数过滤（默认不过滤）"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="输出文件路径（默认自动生成到 content/classified/ 目录）"
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    print(f"📂 扫描报告目录: {REPORTS_DIR}")
    print(f"📅 日期范围: {start_date} → {end_date}")
    print()

    # 1. 收集项目
    projects = collect_projects(start_date, end_date)
    print(f"✅ 共收集到 {len(projects)} 个项目（去重后）")

    # 2. 过滤
    if args.min_stars > 0:
        projects = [p for p in projects if p.stars >= args.min_stars]
        print(f"🔍 过滤后（>= {args.min_stars} Stars）: {len(projects)} 个")

    # 3. 分类
    classified = classify_projects(projects)
    print()
    print("📊 分类结果:")
    for cat_name, _, _ in CATEGORIES:
        if cat_name in classified and classified[cat_name]:
            print(f"   {cat_name}: {len(classified[cat_name])} 个")

    # 4. 生成报告
    report = generate_classified_report(classified, start_date, end_date, len(projects))

    # 5. 保存
    if args.output:
        output_path = ROOT / args.output
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"classified_{start_date}_{end_date}.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print()
    print(f"💾 报告已保存: {output_path}")


if __name__ == "__main__":
    main()
