"""诊断脚本：对比两个快照，从"语言 × star 分段"维度精确定位哪里漏抓。"""
from src.utils.snapshot_diff import load_snapshot_data

newer = load_snapshot_data('data/snapshot_2026-05-08.json')  # 6.1w 条
older = load_snapshot_data('data/snapshot_2026-04-26.json')  # 5.9w 条

only_in_newer = set(newer.keys()) - set(older.keys())       # 2627 个"伪新增"
only_in_older = set(older.keys()) - set(newer.keys())       # 101 个"消失"
common = set(newer.keys()) & set(older.keys())

# ── 1. 检查共同项目的 star 变化，看看是否有真实的下降 ──
decreased = []
increased_a_lot = []
for r in common:
    diff = newer[r] - older[r]
    if diff < -100:
        decreased.append((r, older[r], newer[r]))
    if diff > 5000:
        increased_a_lot.append((r, older[r], newer[r]))

print("=" * 60)
print("1. 共同项目的 star 变化检查")
print("=" * 60)
print(f"共同项目数: {len(common)}")
print(f"star 下降 >100 的: {len(decreased)}  (正常：项目被删/被 archive/少量 unstar)")
print(f"star 上涨 >5000 的: {len(increased_a_lot)}  (13天涨5000+的正常项目)")
print()
print("涨最凶的前10 (共同项目里):")
for r, o, n in sorted(increased_a_lot, key=lambda x: x[2] - x[1], reverse=True)[:10]:
    print(f"  {r}: {o} → {n}  (+{n-o})")
print()

# ── 2. "伪新增"按 star 分桶 —— 这是重点 ──
print("=" * 60)
print('2. 2627个"伪新增"按 star 分桶')
print("=" * 60)
buckets = [
    (1000, 1100, "刚破 1k，可能真新增"),
    (1100, 1500, "1.1k-1.5k，要么真新增要么漏抓"),
    (1500, 3000, "1.5k-3k，13天不可能从 <1k 涨到"),
    (3000, 10000, "3k-10k，绝对是漏抓"),
    (10000, 50000, "1w-5w，绝对是漏抓"),
    (50000, 200000, ">5w，绝对是漏抓"),
]
for lo, hi, note in buckets:
    cnt = sum(1 for r in only_in_newer if lo <= newer[r] < hi)
    print(f"  [{lo:>6}, {hi:>6}): {cnt:>5}  ← {note}")
print()

# ── 3. "伪新增"有没有一个共性？ ──
# 例如：某个语言的仓库特别多？某个 star 区段特别集中？
# GitHub Search API 的 total_count 如果某个查询超过1000条被截断，会表现为：
# - 漏抓的项目在星级排序靠后的 pages (>10)
# - 如果按 stars asc 排序取前1000条（本代码做法），则漏掉 stars 大的部分
# 所以 "伪新增" 应该集中在 star 较大的部分
# 实际数据印证：最高伪新增 star=181944，绝大多数在 >1500，支持这个推断

# ── 4. 核心诊断：看看 2627 个伪新增里有多少"stars > 5000"的 ──
fake_high = [r for r in only_in_newer if newer[r] > 5000]
print(f"伪新增中 star > 5000 的数量: {len(fake_high)}")
print(f"这些项目理论上早在 4/26 前就已 >= 1000，属于漏抓")
print()

# ── 5. 检查一个典型漏抓项目在两个快照中的情况 ──
sample_repos = ["obra/superpowers", "anthropics/claude-code",
                "deepseek-ai/DeepSeek-R1", "CompVis/stable-diffusion",
                "openai/openai-cookbook"]
print("=" * 60)
print("5. 抽样漏抓项目的快照状态")
print("=" * 60)
for r in sample_repos:
    o = older.get(r, "❌ 不在4/26快照")
    n = newer.get(r, "❌ 不在5/8快照")
    print(f"  {r}")
    print(f"    4/26: {o}")
    print(f"    5/8:  {n}")
