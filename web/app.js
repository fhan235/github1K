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
  view: "week",
  index: null,
  weekId: null,
  week: null,
  daily: { index: null, dayId: null, day: null, projects: [], q: "", cat: "", lang: "", sort: "gain", pendingDay: null },
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

function readHash() {
  const get = (k) => {
    const m = new RegExp(`(?:^|[#&])${k}=([^&]+)`).exec(location.hash);
    return m ? decodeURIComponent(m[1]) : null;
  };
  return { v: get("v"), w: get("w"), d: get("d") };
}

function writeHash() {
  const parts = [];
  if (state.view === "daily") parts.push("v=daily", `d=${encodeURIComponent(state.daily.dayId || "")}`);
  else parts.push(`w=${encodeURIComponent(state.weekId || "")}`);
  history.replaceState(null, "", `#${parts.join("&")}`);
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
  writeHash();
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
  $("d-list").replaceChildren(el("p", { class: "empty", text: "数据加载失败，请稍后刷新重试。" }));
}

/* ---------------- 日报 ---------------- */

function setView(view) {
  state.view = view;
  $("view-week").hidden = view !== "week";
  $("view-daily").hidden = view !== "daily";
  $("week-picker-box").hidden = view !== "week";
  $("day-picker-box").hidden = view !== "daily";
  $("tab-week").classList.toggle("active", view === "week");
  $("tab-daily").classList.toggle("active", view === "daily");
  $("tab-week").setAttribute("aria-selected", String(view === "week"));
  $("tab-daily").setAttribute("aria-selected", String(view === "daily"));
  writeHash();
  if (view === "daily" && !state.daily.index) initDaily().catch(showError);
}

async function initDaily() {
  state.daily.index = await fetchJSON("data/daily/index.json");
  const days = state.daily.index.days || [];
  if (!days.length) {
    $("d-list").replaceChildren(el("p", { class: "empty", text: "还没有日报数据。" }));
    return;
  }
  const sel = $("day-select");
  sel.replaceChildren(
    ...days.map((d, i) =>
      el("option", { value: d.date, text: `${d.date}（${d.count} 个）${i === 0 ? " 最新" : ""}` })),
  );
  sel.addEventListener("change", () => loadDay(sel.value).catch(showError));
  $("d-search").addEventListener("input", debounce((e) => { state.daily.q = e.target.value; renderDaily(); }, 150));
  $("d-lang-select").addEventListener("change", (e) => { state.daily.lang = e.target.value; renderDaily(); });
  $("d-sort-select").addEventListener("change", (e) => { state.daily.sort = e.target.value; renderDaily(); });
  const valid = new Set(days.map((d) => d.date));
  const first = state.daily.pendingDay && valid.has(state.daily.pendingDay)
    ? state.daily.pendingDay
    : days[0].date;
  state.daily.pendingDay = null;
  await loadDay(first).catch(showError);
}

async function loadDay(day) {
  state.daily.dayId = day;
  $("day-select").value = day;
  writeHash();
  $("d-list").replaceChildren(el("p", { class: "empty", text: "加载中…" }));

  const d = await fetchJSON(`data/daily/${encodeURIComponent(day)}.json`);
  state.daily.day = d;
  state.daily.projects = d.projects.map((p, i) => ({ ...p, rank: i + 1 }));

  const cats = new Set(state.daily.projects.map((p) => p.category));
  const langs = new Set(state.daily.projects.map((p) => p.language).filter(Boolean));
  if (!cats.has(state.daily.cat)) state.daily.cat = "";
  if (!langs.has(state.daily.lang)) state.daily.lang = "";

  renderDailyHero();
  renderDailyLangs();
  renderDaily();
}

function renderDailyHero() {
  const d = state.daily.day;
  const s = state.daily;
  const box = $("daily-hero");

  const gainers = s.projects.filter((p) => (p.gained || 0) > 0);
  const top = gainers[0];
  const langs = new Map();
  for (const p of s.projects) if (p.language) langs.set(p.language, (langs.get(p.language) || 0) + 1);
  const langTop = [...langs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);

  const highlights = d.points?.length
    ? el("div", { class: "highlights" },
        el("div", { class: "eyebrow", text: "今日看点" }),
        d.headline ? el("p", { class: "headline", text: d.headline }) : null,
        el("ul", {}, d.points.map((t) => el("li", { text: t }))),
      )
    : null;

  box.replaceChildren(...[
    el("div", { class: "hero-title" },
      el("h2", { text: `${d.date} 日报` }),
      el("span", { class: "range", text: `${s.projects.length} 个项目破千` }),
    ),
    highlights,
    el("div", { class: "stats" },
      stat("当日破千", String(s.projects.length), d.has_digest ? "全部带 AI 解读" : "无 AI 解读"),
      d.gained_total ? stat("合计增量", fmtGain(d.gained_total), "可信增量的总和", "up") : null,
      top ? stat("日增第一", fmtGain(top.gained), [repoLink(top)]) : null,
      langTop.length ? stat("热门语言", langTop[0][0], langTop.map(([l, n]) => `${l} ${n}`).join(" · ")) : null,
    ),
    d.unreliable
      ? el("div", { class: "notice", text: "当天的对比基线不完整，多数项目的单日增量是伪增量（多日积少成多），请只看 Star 总数。" })
      : null,
    !d.has_digest
      ? el("div", { class: "notice", text: "这天没有 AI 解读（只有历史日报做过 AI 处理，之后的新日报是原始数据）。" })
      : null,
  ].filter(Boolean));
}

function renderDailyLangs() {
  const counts = new Map();
  for (const p of state.daily.projects) if (p.language) counts.set(p.language, (counts.get(p.language) || 0) + 1);
  const sel = $("d-lang-select");
  sel.replaceChildren(
    el("option", { value: "", text: "全部语言" }),
    ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([lang, n]) =>
      el("option", { value: lang, text: `${lang} (${n})` })
    ),
  );
  sel.value = state.daily.lang;
}

function renderDailyChips(list) {
  const counts = new Map();
  for (const p of list) counts.set(p.category, (counts.get(p.category) || 0) + 1);
  const box = $("d-category-chips");
  if (counts.size <= 1) { box.replaceChildren(); return; }
  const chip = (value, label, n) =>
    el("button", {
      type: "button",
      class: "chip" + (state.daily.cat === value ? " active" : ""),
      "aria-pressed": state.daily.cat === value ? "true" : "false",
      onclick: () => { state.daily.cat = state.daily.cat === value ? "" : value; renderDaily(); },
    }, label, el("span", { class: "count", text: String(n) }));
  box.replaceChildren(
    chip("", "全部", list.length),
    ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) => chip(c, catLabel(c), n)),
  );
}

const DAILY_SORTERS = {
  gain: (a, b) => (b.gained ?? -Infinity) - (a.gained ?? -Infinity) || (b.stars ?? 0) - (a.stars ?? 0),
  stars: (a, b) => (b.stars ?? 0) - (a.stars ?? 0),
  created: (a, b) => (b.created_at || "").localeCompare(a.created_at || ""),
};

function matchesDaily(p, q) {
  if (!q) return true;
  const hay = [p.name, p.description, p.language, p.one_liner,
    p.intro?.what_it_is, p.intro?.problem_solved, ...(p.topics || [])]
    .filter(Boolean).join(" ").toLowerCase();
  return q.split(/\s+/).every((t) => hay.includes(t));
}

function renderDaily() {
  const s = state.daily;
  const q = s.q.trim().toLowerCase();
  const base = s.projects.filter((p) => matchesDaily(p, q) && (!s.lang || p.language === s.lang));
  renderDailyChips(base);

  const list = base.filter((p) => !s.cat || p.category === s.cat);
  list.sort(DAILY_SORTERS[s.sort] || DAILY_SORTERS.gain);

  $("d-result-count").textContent = `显示 ${list.length} / ${s.projects.length} 个项目`;
  $("d-list").replaceChildren(
    ...(list.length ? list.map(renderDailyRow) : [el("p", { class: "empty", text: "没有符合条件的项目" })])
  );
}

function renderDailyRow(p) {
  const sp = sparkline(p.spark, { width: 130, height: 32 });
  const line = p.one_liner || p.description || "（作者未填写描述）";
  return el("details", { class: "row" },
    el("summary", {},
      el("span", { class: "rank", text: String(p.rank), title: `当日第 ${p.rank}` }),
      el("div", { class: "main" },
        el("div", { class: "title" }, repoLink(p), el("span", { class: "cat", text: catLabel(p.category) }),
          p.is_fork ? el("span", { class: "tag", text: "fork" }) : null),
        el("div", { class: "line", text: line, title: line }),
      ),
      el("div", { class: "col-spark" }, sp ? sp.node : el("div", { class: "spark-none", text: "暂无走势" })),
      el("div", { class: "col-num col-stars" }, fmtShort(p.stars), el("small", { text: "Star" })),
      el("div", { class: "col-num" + ((p.gained || 0) > 0 ? " up" : "") }, fmtGain(p.gained), el("small", { text: p.gained == null ? "增量未知" : "当日" })),
      el("span", { class: "chev", "aria-hidden": "true", text: "›" }),
    ),
    el("div", { class: "row-body" },
      p.description ? el("p", { class: "desc", text: p.description }) : null,
      introList(p.intro),
      metaTags(p, 6),
    ),
  );
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
  $("tab-week").addEventListener("click", () => setView("week"));
  $("tab-daily").addEventListener("click", () => setView("daily"));
  window.addEventListener("hashchange", () => {
    const h = readHash();
    if (h.v === "daily" && state.view !== "daily") setView("daily");
    else if (h.v === "daily" && h.d && h.d !== state.daily.dayId) loadDay(h.d).catch(showError);
    else if (h.w && h.w !== state.weekId && isKnownWeek(h.w)) {
      if (state.view !== "week") setView("week");
      loadWeek(h.w).catch(showError);
    }
  });

  const h = readHash();
  const firstWeek = h.w && isKnownWeek(h.w) ? h.w : weeks[0].id;
  if (h.v === "daily") {
    state.daily.pendingDay = h.d;
    setView("daily");
  }
  await loadWeek(firstWeek).catch(showError);
}

init();
