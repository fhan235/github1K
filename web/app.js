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

const safeGithubUrl = (url) =>
  typeof url === "string" && /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(url) ? url : null;

const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString("en-US") : "—");
const fmtGain = (n) => (typeof n === "number" ? (n > 0 ? "+" : "") + n.toLocaleString("en-US") : "—");
const catLabel = (c) => CATEGORY_LABELS[c] || CATEGORY_LABELS.other;
const weekLabel = (w) => `${w.start} → ${w.end}`;
const stars = (p) => p.current_stars ?? p.stars_at_breakthrough ?? 0;

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

function isKnownWeek(id) {
  return id === ALL || state.index.weeks.some((w) => w.id === id);
}

/* ---------------- 数据加载 ---------------- */

async function loadWeek(id) {
  state.weekId = id;
  $("week-select").value = id;
  history.replaceState(null, "", `#w=${encodeURIComponent(id)}`);
  $("cards").replaceChildren(el("p", { class: "empty", text: "加载中…" }));

  if (id === ALL) {
    const weeks = await Promise.all(
      state.index.weeks.map((w) => fetchJSON(`data/weeks/${encodeURIComponent(w.id)}.json`))
    );
    state.week = null;
    state.projects = weeks.flatMap((w) =>
      w.finalists.map((p, i) => ({ ...p, rank: i + 1, weekEnd: w.end, weekText: weekLabel(w) }))
    );
  } else {
    const w = await fetchJSON(`data/weeks/${encodeURIComponent(id)}.json`);
    state.week = w;
    state.projects = w.finalists.map((p, i) => ({ ...p, rank: i + 1, weekEnd: w.end, weekText: weekLabel(w) }));
  }

  const cats = new Set(state.projects.map((p) => p.category));
  const langs = new Set(state.projects.map((p) => p.language).filter(Boolean));
  if (!cats.has(state.cat)) state.cat = "";
  if (!langs.has(state.lang)) state.lang = "";

  renderSummary();
  renderLangOptions();
  render();
}

/* ---------------- 渲染 ---------------- */

function stat(label, value, sub) {
  return el("div", { class: "stat" },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }),
    sub ? el("div", { class: "sub", text: sub }) : null,
  );
}

function renderSummary() {
  const box = $("summary");
  if (state.weekId === ALL) {
    const weeks = state.index.weeks;
    box.replaceChildren(
      stat("收录期数", String(weeks.length)),
      stat("累计精选项目", fmtNum(state.projects.length)),
      stat("时间跨度", weeks.length ? `${weeks[weeks.length - 1].start} 起` : "—"),
    );
    return;
  }
  const w = state.week;
  const totalDays = 7;
  const covered = totalDays - w.missing_days.length;
  const withIntro = w.finalists.filter((p) => p.intro).length;
  box.replaceChildren(
    stat("统计区间", weekLabel(w)),
    stat("本周突破 1K", w.total_breakthroughs != null ? fmtNum(w.total_breakthroughs) : "—", "个项目"),
    stat("精选", String(w.finalists.length), `其中 ${withIntro} 个有 AI 解读`),
    stat("数据覆盖", `${covered}/${totalDays} 天`, w.missing_days.length ? `缺：${w.missing_days.join("、")}` : "完整"),
    w.dry_run ? el("div", { class: "notice", text: "本期为 dry-run，未调用大模型，卡片里显示的是 GitHub 原始描述。" }) : null,
  );
}

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
  const chip = (value, label, n) =>
    el("button", {
      type: "button",
      class: "chip" + (state.cat === value ? " active" : ""),
      "aria-pressed": state.cat === value ? "true" : "false",
      onclick: () => { state.cat = state.cat === value ? "" : value; render(); },
    }, label, el("span", { class: "count", text: String(n) }));

  $("category-chips").replaceChildren(
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

  $("result-count").textContent = `显示 ${list.length} / ${state.projects.length} 个项目`;
  $("cards").replaceChildren(
    ...(list.length ? list.map(renderCard) : [el("p", { class: "empty", text: "没有符合条件的项目" })])
  );
  renderContinuing();
}

function introRow(label, value) {
  return value ? [el("dt", { text: label }), el("dd", { text: value })] : [];
}

function renderCard(p) {
  const [owner, repo] = p.name.split("/");
  const url = safeGithubUrl(p.url);
  const intro = p.intro;
  const medal = MEDALS[p.rank];

  const metrics = el("div", { class: "metrics" },
    el("span", {}, "⭐ ", el("b", { text: fmtNum(stars(p)) })),
    typeof p.weekly_gain === "number"
      ? el("span", {}, "一周 ", el("b", { class: p.weekly_gain > 0 ? "up" : "", text: fmtGain(p.weekly_gain) }))
      : null,
    typeof p.best_gained === "number" && p.best_gained > 0
      ? el("span", {}, "单日最高 ", el("b", { text: fmtGain(p.best_gained) }))
      : null,
    p.days_seen ? el("span", {}, "上榜 ", el("b", { text: String(p.days_seen) }), " 天") : null,
  );

  const meta = el("div", { class: "meta" },
    p.language ? el("span", { class: "tag lang", text: p.language }) : null,
    p.license ? el("span", { class: "tag", text: p.license }) : null,
    p.created_at ? el("span", { class: "tag", text: `创建于 ${p.created_at}` }) : null,
    ...(p.topics || []).slice(0, 4).map((t) => el("span", { class: "tag", text: `#${t}` })),
  );

  let details = null;
  if (intro) {
    const judge = [intro.maturity && `成熟度：${intro.maturity}`, intro.hype_or_trend].filter(Boolean).join("；");
    details = el("details", { class: "intro" },
      el("summary", { text: "查看 AI 解读" }),
      el("dl", {},
        ...introRow("是什么", intro.what_it_is),
        ...introRow("解决什么", intro.problem_solved),
        ...introRow("谁该关注", intro.who_should_care),
        ...(intro.use_cases?.length
          ? [el("dt", { text: "典型场景" }), el("dd", {}, el("ul", {}, intro.use_cases.map((u) => el("li", { text: u }))))]
          : []),
        ...introRow("同类对比", intro.alternatives),
        ...introRow("判断", judge),
        ...introRow("注意", intro.risk_notes),
      ),
    );
  }

  return el("article", { class: "card" },
    el("div", { class: "card-head" },
      el("span", { class: "rank" + (medal ? " medal" : ""), text: medal || `#${p.rank}`, title: `第 ${p.rank} 名` }),
      el("div", { class: "repo" },
        el("a", url ? { href: url, target: "_blank", rel: "noopener noreferrer" } : {},
          el("span", { class: "owner", text: `${owner}/` }), repo),
      ),
      el("span", { class: "cat", text: catLabel(p.category) }),
    ),
    intro ? el("p", { class: "one-liner", text: intro.one_liner }) : null,
    p.description ? el("p", { class: "desc", text: p.description, title: p.description }) : null,
    metrics,
    meta,
    p.risky ? el("div", { class: "warn", text: `⚠️ 数据存在风险标记${p.risk_reason ? `：${p.risk_reason}` : ""}，解读时请留意` }) : null,
    details,
    el("div", { class: "card-foot" },
      el("span", { text: typeof p.score === "number" ? `评分 ${p.score}` : "" }),
      state.weekId === ALL ? el("span", { text: p.weekText }) : null,
    ),
  );
}

function renderContinuing() {
  const section = $("continuing");
  const rows = state.week?.continuing || [];
  section.hidden = rows.length === 0;
  $("continuing-body").replaceChildren(
    ...rows.map((p) => {
      const url = safeGithubUrl(p.url);
      return el("tr", {},
        el("td", {}, el("a", url ? { href: url, target: "_blank", rel: "noopener noreferrer" } : {}, p.name)),
        el("td", { class: "num", text: fmtNum(p.stars_at_breakthrough) }),
        el("td", { class: "num", text: fmtNum(p.current_stars) }),
        el("td", { class: "num", text: fmtGain(p.weekly_gain) }),
      );
    }),
  );
}

/* ---------------- 初始化 ---------------- */

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function init() {
  try {
    state.index = await fetchJSON("data/index.json");
  } catch (e) {
    $("cards").replaceChildren(el("p", { class: "empty", text: "数据加载失败，请稍后刷新重试。" }));
    console.error(e);
    return;
  }

  const weeks = state.index.weeks || [];
  if (state.index.generated_at) {
    $("generated-at").textContent = `更新于 ${new Date(state.index.generated_at).toLocaleString("zh-CN", { hour12: false })}`;
  }
  if (!weeks.length) {
    $("cards").replaceChildren(el("p", { class: "empty", text: "还没有周榜数据。" }));
    return;
  }

  const sel = $("week-select");
  sel.replaceChildren(
    ...weeks.map((w, i) => el("option", { value: w.id, text: `${weekLabel(w)}${i === 0 ? "（最新）" : ""}` })),
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

function showError(e) {
  console.error(e);
  $("cards").replaceChildren(el("p", { class: "empty", text: "数据加载失败，请稍后刷新重试。" }));
}

init();
