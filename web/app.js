"use strict";

const CATEGORY_LABELS = {
  "ai-agent": "🤖 AI Agent",
  "ai-model": "🧠 AI 模型/推理",
  "dev-tools": "🛠️ 开发工具",
  "web-frontend": "🌐 Web 前端",
  "security": "🔒 安全隐私",
  "content-media": "🎨 内容创作",
  "data-finance": "📊 数据金融",
  "learning-resource": "📚 学习资源",
  "automation": "⚙️ 自动化",
  "desktop-system": "💻 桌面系统",
  "mobile": "📱 移动端",
  "game": "🎮 游戏",
  "hardware-iot": "🔌 硬件/IoT",
  "other": "📦 其他",
};
const ALL = "all";
const MEDALS = { 1: "🥇", 2: "🥈", 3: "🥉" };
const PODIUM_SIZE = 3;
const SVG_NS = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);
const state = {
  index: null,
  weekId: null,
  week: null,
  projects: [],
  q: "",
  cat: "",
  lang: "",
  sort: "rank",
};
const cache = new Map();

/* ---------------- 工具 ---------------- */

/** 用 DOM API 创建节点，所有文本都走 textContent，避免 XSS。 */
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
  return node;
}

const safeGithubUrl = (url) =>
  typeof url === "string" && /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(url) ? url : null;

const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString("en-US") : "—");
const fmtGain = (n) => (typeof n === "number" ? (n > 0 ? "+" : "") + n.toLocaleString("en-US") : "—");
const fmtShort = (n) => {
  if (typeof n !== "number") return "—";
  return n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : n.toLocaleString("en-US");
};
const catLabel = (c) => CATEGORY_LABELS[c] || CATEGORY_LABELS.other;
const weekLabel = (w) => `${w.start} → ${w.end}`;
const stars = (p) => p.current_stars ?? p.stars_at_breakthrough ?? 0;
const mmdd = (iso) => iso.slice(5).replace("-", "/");

function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function repoLink(p) {
  const [owner, repo] = p.name.split("/");
  const url = safeGithubUrl(p.url);
  return el("a", url ? { href: url, target: "_blank", rel: "noopener noreferrer", onclick: (e) => e.stopPropagation() } : {},
    el("span", { class: "owner", text: `${owner}/` }), repo);
}

async function fetchJSON(path) {
  if (cache.has(path)) return cache.get(path);
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  const data = await res.json();
  cache.set(path, data);
  return data;
}

function readHashWeek() {
  const m = /(?:^|[#&])w=([^&]+)/.exec(location.hash);
  return m ? decodeURIComponent(m[1]) : null;
}

const isKnownWeek = (id) => id === ALL || state.index.weeks.some((w) => w.id === id);

/* ---------------- Sparkline ---------------- */

/**
 * 画 Star 走势迷你图。values 中 null 表示当天不在快照里（多半是还没到 500 Star）。
 * 跨过 1000 时画一条金色虚线标出「破千」位置。
 */
function sparkline(spark, { width = 130, height = 32 } = {}) {
  if (!spark || !Array.isArray(spark.values)) return null;
  const n = spark.values.length - 1;
  const pts = spark.values
    .map((v, i) => [i, v])
    .filter(([, v]) => typeof v === "number");
  if (pts.length < 2 || n < 1) return null;

  const vs = pts.map(([, v]) => v);
  const min = Math.min(...vs);
  const max = Math.max(...vs);
  const range = max - min || 1;
  const pad = 3;
  const x = (i) => pad + (i / n) * (width - pad * 2);
  const y = (v) => height - pad - ((v - min) / range) * (height - pad * 2);

  const first = pts[0];
  const last = pts[pts.length - 1];
  const firstDay = addDays(spark.start, first[0]);
  const lastDay = addDays(spark.start, last[0]);
  const desc = `${mmdd(firstDay)} ${fmtNum(first[1])} → ${mmdd(lastDay)} ${fmtNum(last[1])} Star`;

  const root = svg("svg", {
    class: "spark", viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none",
    role: "img", "aria-label": `Star 走势：${desc}`,
  });
  const title = svg("title");
  title.textContent = desc;
  root.append(title);

  const line = pts.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  root.append(svg("path", {
    class: "spark-area",
    d: `M${x(first[0]).toFixed(1)},${height} L${line.replaceAll(" ", " L")} L${x(last[0]).toFixed(1)},${height} Z`,
  }));
  if (min < 1000 && max >= 1000) {
    const y1k = y(1000).toFixed(1);
    root.append(svg("line", { class: "spark-1k", x1: 0, x2: width, y1: y1k, y2: y1k }));
  }
  root.append(svg("polyline", { class: "spark-line", points: line }));
  root.append(svg("circle", { class: "spark-dot", cx: x(last[0]).toFixed(1), cy: y(last[1]).toFixed(1), r: 2.6 }));
  return { node: root, firstDay, lastDay };
}

/* ---------------- 数据加载 ---------------- */

async function loadWeek(id) {
  state.weekId = id;
  $("week-select").value = id;
  history.replaceState(null, "", `#w=${encodeURIComponent(id)}`);
  $("list").replaceChildren(el("p", { class: "empty", text: "加载中…" }));

  const tag = (w) => (p, i) => ({ ...p, rank: i + 1, weekEnd: w.end, weekText: weekLabel(w) });
  if (id === ALL) {
    const weeks = await Promise.all(
      state.index.weeks.map((w) => fetchJSON(`data/weeks/${encodeURIComponent(w.id)}.json`))
    );
    state.week = null;
    state.projects = weeks.flatMap((w) => w.finalists.map(tag(w)));
  } else {
    const w = await fetchJSON(`data/weeks/${encodeURIComponent(id)}.json`);
    state.week = w;
    state.projects = w.finalists.map(tag(w));
  }

  const cats = new Set(state.projects.map((p) => p.category));
  const langs = new Set(state.projects.map((p) => p.language).filter(Boolean));
  if (!cats.has(state.cat)) state.cat = "";
  if (!langs.has(state.lang)) state.lang = "";

  renderHero();
  renderLangOptions();
  render();
}

/* ---------------- Hero：本周看点 + 数据速览 ---------------- */

function stat(label, value, sub, valueClass) {
  return el("div", { class: "stat" },
    el("div", { class: "label", text: label }),
    el("div", { class: "value" + (valueClass ? ` ${valueClass}` : ""), text: value }),
    sub ? el("div", { class: "sub" }, sub) : null,
  );
}

function renderHero() {
  const box = $("hero");
  if (state.weekId === ALL) {
    const weeks = state.index.weeks;
    box.replaceChildren(
      el("div", { class: "hero-title" }, el("h2", { text: "全部往期" })),
      el("div", { class: "stats" },
        stat("收录期数", String(weeks.length)),
        stat("累计精选项目", fmtNum(state.projects.length)),
        stat("时间跨度", weeks.length ? `${weeks[weeks.length - 1].start} 起` : "—"),
      ),
    );
    return;
  }

  const w = state.week;
  const s = w.stats || {};
  const issueNo = state.index.weeks.length - state.index.weeks.findIndex((x) => x.id === w.id);
  const covered = 7 - w.missing_days.length;

  const highlights = w.highlights?.points?.length
    ? el("div", { class: "highlights" },
        el("div", { class: "eyebrow", text: "本周看点" }),
        w.highlights.headline ? el("p", { class: "headline", text: w.highlights.headline }) : null,
        el("ul", {}, w.highlights.points.map((t) => el("li", { text: t }))),
      )
    : null;

  const repoSub = (name, extra) => {
    const p = w.finalists.find((x) => x.name === name);
    return [p ? repoLink(p) : name, extra ? ` · ${extra}` : ""];
  };

  box.replaceChildren(...[
    el("div", { class: "hero-title" },
      el("h2", { text: `第 ${issueNo} 期` }),
      el("span", { class: "range", text: weekLabel(w) }),
    ),
    highlights,
    el("div", { class: "stats" },
      stat("本周突破 1K", w.total_breakthroughs != null ? fmtNum(w.total_breakthroughs) : "—",
        `精选 ${w.finalists.length} 个 · 数据覆盖 ${covered}/7 天`),
      s.top_gainer ? stat("涨势最猛", fmtGain(s.top_gainer.value), repoSub(s.top_gainer.name, "一周"), "up") : null,
      s.fastest ? stat("最快破千", s.fastest.value === 0 ? "当天" : `${s.fastest.value} 天`, repoSub(s.fastest.name, "从创建到破千")) : null,
      s.languages?.length
        ? stat("热门语言", s.languages[0][0], s.languages.map(([l, n]) => `${l} ${n}`).join(" · "))
        : null,
      s.categories?.length
        ? stat("热门赛道", catLabel(s.categories[0][0]), s.categories.map(([c, n]) => `${catLabel(c)} ${n}`).join(" · "))
        : null,
    ),
    w.missing_days.length ? el("div", { class: "notice", text: `本周缺少 ${w.missing_days.join("、")} 的日报数据，部分项目可能未被统计。` }) : null,
    w.dry_run ? el("div", { class: "notice", text: "本期为 dry-run，未调用大模型：没有 AI 解读，类别统一为「其他」。" }) : null,
  ].filter(Boolean));
}

/* ---------------- 筛选 ---------------- */

function renderLangOptions() {
  const counts = new Map();
  for (const p of state.projects) if (p.language) counts.set(p.language, (counts.get(p.language) || 0) + 1);
  const sel = $("lang-select");
  sel.replaceChildren(
    el("option", { value: "", text: "全部语言" }),
    ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([lang, n]) =>
      el("option", { value: lang, text: `${lang} (${n})` })
    ),
  );
  sel.value = state.lang;
}

function renderChips(list) {
  const counts = new Map();
  for (const p of list) counts.set(p.category, (counts.get(p.category) || 0) + 1);
  const box = $("category-chips");
  if (counts.size <= 1) { box.replaceChildren(); return; }
  const chip = (value, label, n) =>
    el("button", {
      type: "button",
      class: "chip" + (state.cat === value ? " active" : ""),
      "aria-pressed": state.cat === value ? "true" : "false",
      onclick: () => { state.cat = state.cat === value ? "" : value; render(); },
    }, label, el("span", { class: "count", text: String(n) }));

  box.replaceChildren(
    chip("", "全部", list.length),
    ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) => chip(c, catLabel(c), n)),
  );
}

function matchesQuery(p, q) {
  if (!q) return true;
  const hay = [
    p.name, p.description, p.language, ...(p.topics || []),
    p.intro?.one_liner, p.intro?.what_it_is, p.intro?.problem_solved,
  ].filter(Boolean).join(" ").toLowerCase();
  return q.split(/\s+/).every((t) => hay.includes(t));
}

const SORTERS = {
  rank: (a, b) => (b.weekEnd || "").localeCompare(a.weekEnd || "") || a.rank - b.rank,
  score: (a, b) => (b.score ?? -1) - (a.score ?? -1),
  gain: (a, b) => (b.weekly_gain ?? -Infinity) - (a.weekly_gain ?? -Infinity),
  stars: (a, b) => stars(b) - stars(a),
  created: (a, b) => (b.created_at || "").localeCompare(a.created_at || ""),
};

function render() {
  const q = state.q.trim().toLowerCase();
  const base = state.projects.filter((p) => matchesQuery(p, q) && (!state.lang || p.language === state.lang));
  renderChips(base);

  const list = base.filter((p) => !state.cat || p.category === state.cat);
  list.sort(SORTERS[state.sort] || SORTERS.rank);

  // 只有「单期 + 默认排序 + 无筛选」时展示前三名大卡片，其余情况统一用列表
  const showPodium = state.weekId !== ALL && state.sort === "rank" && !q && !state.cat && !state.lang;
  const podium = showPodium ? list.slice(0, PODIUM_SIZE) : [];
  const rest = showPodium ? list.slice(PODIUM_SIZE) : list;

  const podiumBox = $("podium");
  podiumBox.hidden = podium.length === 0;
  podiumBox.replaceChildren(...podium.map(renderFeature));

  $("list-title").textContent = showPodium ? "更多精选" : "精选项目";
  $("result-count").textContent = `显示 ${list.length} / ${state.projects.length} 个项目`;
  $("list").replaceChildren(
    ...(rest.length ? rest.map(renderRow) : [el("p", { class: "empty", text: list.length ? "以上就是全部" : "没有符合条件的项目" })])
  );
  renderContinuing();
}

/* ---------------- 详情块（大卡片与列表共用）---------------- */

function introRow(label, value) {
  return value ? [el("dt", { text: label }), el("dd", { text: value })] : [];
}

function introList(intro, { skipWhat = false } = {}) {
  if (!intro) return null;
  const judge = [intro.maturity && `成熟度：${intro.maturity}`, intro.hype_or_trend].filter(Boolean).join("；");
  return el("dl", { class: "intro" },
    ...(skipWhat ? [] : introRow("是什么", intro.what_it_is)),
    ...introRow("解决什么", intro.problem_solved),
    ...introRow("谁该关注", intro.who_should_care),
    ...(intro.use_cases?.length
      ? [el("dt", { text: "典型场景" }), el("dd", {}, el("ul", {}, intro.use_cases.map((u) => el("li", { text: u }))))]
      : []),
    ...introRow("同类对比", intro.alternatives),
    ...introRow("判断", judge),
    ...introRow("注意", intro.risk_notes),
  );
}

function metaTags(p, topicLimit = 4) {
  return el("div", { class: "meta" },
    p.language ? el("span", { class: "tag lang", text: p.language }) : null,
    p.license ? el("span", { class: "tag", text: p.license }) : null,
    p.created_at ? el("span", { class: "tag", text: `创建于 ${p.created_at}` }) : null,
    ...(p.topics || []).slice(0, topicLimit).map((t) => el("span", { class: "tag", text: `#${t}` })),
  );
}

function riskNote(p) {
  return p.risky ? el("div", { class: "warn", text: `⚠️ 数据存在风险标记${p.risk_reason ? `：${p.risk_reason}` : ""}，解读时请留意` }) : null;
}

/* ---------------- 前三名大卡片 ---------------- */

function renderFeature(p) {
  const intro = p.intro;
  const sp = sparkline(p.spark, { width: 300, height: 64 });

  return el("article", { class: `feature rank-${p.rank}` },
    el("div", { class: "feature-head" },
      el("span", { class: "medal", text: MEDALS[p.rank] || `#${p.rank}`, title: `第 ${p.rank} 名` }),
      el("div", { class: "repo" }, repoLink(p)),
      el("span", { class: "cat", text: catLabel(p.category) }),
    ),
    intro ? el("p", { class: "one-liner", text: intro.one_liner }) : null,
    el("p", { class: "what", text: intro?.what_it_is || p.description || "（作者未填写描述）" }),
    el("div", { class: "metrics" },
      el("span", {}, "⭐ ", el("b", { text: fmtNum(stars(p)) })),
      typeof p.weekly_gain === "number"
        ? el("span", {}, "一周 ", el("b", { class: p.weekly_gain > 0 ? "up" : "", text: fmtGain(p.weekly_gain) }))
        : null,
      typeof p.best_gained === "number" && p.best_gained > 0
        ? el("span", {}, "单日最高 ", el("b", { text: fmtGain(p.best_gained) }))
        : null,
    ),
    sp
      ? el("div", { class: "spark-box" },
          el("div", { class: "spark-caption" },
            el("span", { text: `${mmdd(sp.firstDay)} → ${mmdd(sp.lastDay)} Star 走势` }),
            el("span", { text: "虚线 = 1000" }),
          ),
          sp.node,
        )
      : null,
    metaTags(p),
    riskNote(p),
    intro
      ? el("details", { class: "more" }, el("summary", { text: "完整解读" }), introList(intro, { skipWhat: true }))
      : null,
  );
}

/* ---------------- 紧凑列表行 ---------------- */

function renderRow(p) {
  const intro = p.intro;
  const sp = sparkline(p.spark, { width: 130, height: 32 });
  const line = intro?.one_liner || p.description || "（作者未填写描述）";
  const gain = p.weekly_gain;

  return el("details", { class: "row" },
    el("summary", {},
      el("span", { class: "rank", text: MEDALS[p.rank] || String(p.rank), title: state.weekId === ALL ? p.weekText : `第 ${p.rank} 名` }),
      el("div", { class: "main" },
        el("div", { class: "title" }, repoLink(p), el("span", { class: "cat", text: catLabel(p.category) })),
        el("div", { class: "line", text: line, title: line }),
      ),
      el("div", { class: "col-spark" }, sp ? sp.node : el("div", { class: "spark-none", text: "暂无走势" })),
      el("div", { class: "col-num col-stars" }, fmtShort(stars(p)), el("small", { text: "Star" })),
      el("div", { class: "col-num" + (gain > 0 ? " up" : "") }, fmtGain(gain), el("small", { text: "一周" })),
      el("span", { class: "chev", "aria-hidden": "true", text: "›" }),
    ),
    el("div", { class: "row-body" },
      p.description ? el("p", { class: "desc", text: p.description }) : null,
      introList(intro),
      el("div", { class: "metrics" },
        el("span", {}, "⭐ ", el("b", { text: fmtNum(stars(p)) })),
        typeof p.stars_at_breakthrough === "number" ? el("span", {}, "上榜时 ", el("b", { text: fmtNum(p.stars_at_breakthrough) })) : null,
        typeof p.best_gained === "number" && p.best_gained > 0 ? el("span", {}, "单日最高 ", el("b", { text: fmtGain(p.best_gained) })) : null,
        p.days_seen ? el("span", {}, "上榜 ", el("b", { text: String(p.days_seen) }), " 天") : null,
        state.weekId === ALL ? el("span", { text: p.weekText }) : null,
      ),
      metaTags(p, 8),
      riskNote(p),
    ),
  );
}

/* ---------------- 持续走强 ---------------- */

function renderContinuing() {
  const section = $("continuing");
  const rows = state.week?.continuing || [];
  section.hidden = rows.length === 0;
  $("continuing-body").replaceChildren(
    ...rows.map((p) => el("tr", {},
      el("td", {}, repoLink(p)),
      el("td", { class: "num", text: fmtNum(p.stars_at_breakthrough) }),
      el("td", { class: "num", text: fmtNum(p.current_stars) }),
      el("td", { class: "num", text: fmtGain(p.weekly_gain) }),
    )),
  );
}

/* ---------------- 初始化 ---------------- */

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function showError(e) {
  console.error(e);
  $("list").replaceChildren(el("p", { class: "empty", text: "数据加载失败，请稍后刷新重试。" }));
}

async function init() {
  try {
    state.index = await fetchJSON("data/index.json");
  } catch (e) {
    showError(e);
    return;
  }

  const weeks = state.index.weeks || [];
  if (state.index.generated_at) {
    $("generated-at").textContent = `更新于 ${new Date(state.index.generated_at).toLocaleString("zh-CN", { hour12: false })}`;
  }
  if (!weeks.length) {
    $("list").replaceChildren(el("p", { class: "empty", text: "还没有周榜数据。" }));
    return;
  }

  const sel = $("week-select");
  sel.replaceChildren(
    ...weeks.map((w, i) => el("option", { value: w.id, text: `第 ${weeks.length - i} 期 · ${weekLabel(w)}${i === 0 ? "（最新）" : ""}` })),
    weeks.length > 1 ? el("option", { value: ALL, text: "全部往期" }) : null,
  );

  sel.addEventListener("change", () => loadWeek(sel.value).catch(showError));
  $("search").addEventListener("input", debounce((e) => { state.q = e.target.value; render(); }, 150));
  $("lang-select").addEventListener("change", (e) => { state.lang = e.target.value; render(); });
  $("sort-select").addEventListener("change", (e) => { state.sort = e.target.value; render(); });
  window.addEventListener("hashchange", () => {
    const id = readHashWeek();
    if (id && id !== state.weekId && isKnownWeek(id)) loadWeek(id).catch(showError);
  });

  const fromHash = readHashWeek();
  await loadWeek(fromHash && isKnownWeek(fromHash) ? fromHash : weeks[0].id).catch(showError);
}

init();
