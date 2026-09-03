const SCANNER_URL = "data/stock_scanner.json";
const FILTER_STORAGE_KEY = "scannerFilters";

let ALL_STOCKS = [];
let FILTERED = [];
let SELECTED = new Set(); // symbols
let SEARCH_TERM = "";
let SORT_KEY = "turnover";
let SORT_DIR = "desc";

const FILTER_FIELD_IDS = [
  "f-ema-21", "f-ema-50", "f-ema-200",
  "f-high-max", "f-low-min",
  "f-price-min", "f-turnover-min",
  "f-mcap-min", "f-mcap-max",
];

function saveFiltersToStorage() {
  const state = {};
  FILTER_FIELD_IDS.forEach(id => {
    const el = document.getElementById(id);
    state[id] = el.type === "checkbox" ? el.checked : el.value;
  });
  try {
    localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(state));
  } catch (err) {
    // localStorage can fail in private-browsing mode or if disabled --
    // filters just won't persist this session, nothing else breaks.
  }
}

function loadFiltersFromStorage() {
  let state;
  try {
    const raw = localStorage.getItem(FILTER_STORAGE_KEY);
    if (!raw) return;
    state = JSON.parse(raw);
  } catch (err) {
    return;
  }
  FILTER_FIELD_IDS.forEach(id => {
    if (!(id in state)) return;
    const el = document.getElementById(id);
    if (el.type === "checkbox") el.checked = !!state[id];
    else el.value = state[id];
  });
}

function ratingClass(rating) {
  if (rating === null || rating === undefined) return "score-low";
  if (rating >= 80) return "score-high";
  if (rating >= 50) return "score-mid";
  return "score-low";
}

function rsRatingCell(rating) {
  if (rating === null || rating === undefined) return `<span class="muted">n/a</span>`;
  return `<span class="score-badge ${ratingClass(rating)}">${rating}</span>`;
}

function returnCell(v) {
  if (v === null || v === undefined) return `<span class="muted">n/a</span>`;
  const cls = v > 0 ? "trend-up" : v < 0 ? "trend-down" : "";
  return `<span class="${cls}">${v}%</span>`;
}

function stackLadder(ema) {
  if (!ema || !ema.available) return `<span class="muted">n/a</span>`;
  const bars = [
    ["21", ema.above_21],
    ["50", ema.above_50],
    ["200", ema.above_200],
  ];
  const html = bars.map(([label, on]) => {
    if (on === null || on === undefined) return `<div class="stack-bar" title="${label} EMA: no data"></div>`;
    return `<div class="stack-bar ${on ? "on" : "off"}" title="${label} EMA: ${on ? "above" : "below"}"></div>`;
  }).join("");
  return `<div class="stack-ladder">${html}</div>`;
}

function num(id) {
  const v = document.getElementById(id).value.trim();
  return v === "" ? null : parseFloat(v);
}

function readFilters() {
  return {
    ema21: document.getElementById("f-ema-21").checked,
    ema50: document.getElementById("f-ema-50").checked,
    ema200: document.getElementById("f-ema-200").checked,
    highMax: num("f-high-max"),
    lowMin: num("f-low-min"),
    priceMin: num("f-price-min"),
    turnoverMin: num("f-turnover-min"),
    mcapMin: num("f-mcap-min"), mcapMax: num("f-mcap-max"),
  };
}

function inRange(val, min, max) {
  if (val === null || val === undefined) return min === null && max === null;
  if (min !== null && val < min) return false;
  if (max !== null && val > max) return false;
  return true;
}

function applyFilters() {
  const f = readFilters();
  FILTERED = ALL_STOCKS.filter(s => {
    // A checked EMA box only excludes a stock that EXPLICITLY sits below
    // that EMA -- a young stock without enough history for it yet
    // (above_21/50/200 is null, not false) passes through instead of
    // being wrongly treated as failing the check.
    if (f.ema21 && s.ema && s.ema.available && s.ema.above_21 === false) return false;
    if (f.ema50 && s.ema && s.ema.available && s.ema.above_50 === false) return false;
    if (f.ema200 && s.ema && s.ema.available && s.ema.above_200 === false) return false;
    if (f.highMax !== null && !(s.pct_from_52wk_high !== null && s.pct_from_52wk_high !== undefined && s.pct_from_52wk_high <= f.highMax)) return false;
    if (f.lowMin !== null && !(s.pct_from_52wk_low !== null && s.pct_from_52wk_low !== undefined && s.pct_from_52wk_low >= f.lowMin)) return false;
    if (f.priceMin !== null && !(s.close !== null && s.close !== undefined && s.close >= f.priceMin)) return false;
    if (f.turnoverMin !== null && !(s.avg_turnover_cr_30d >= f.turnoverMin)) return false;
    if (!inRange(s.market_cap_cr, f.mcapMin, f.mcapMax)) return false;
    return true;
  });
  if (SEARCH_TERM) {
    const q = SEARCH_TERM.toLowerCase();
    FILTERED = FILTERED.filter(s =>
      s.symbol.toLowerCase().includes(q) || (s.name || "").toLowerCase().includes(q)
    );
  }
  renderResults();
}

function sortValue(row, key) {
  switch (key) {
    case "name": return row.symbol.toLowerCase();
    case "industry": return (row.basic_industry || "").toLowerCase();
    case "price": return row.close ?? -1;
    case "rsRating": return row.rs_rating ?? -1;
    case "return1m": return row.return_1m ?? -9999;
    case "return3m": return row.return_3m ?? -9999;
    case "ema": {
      if (!row.ema || !row.ema.available) return -1;
      const count = [row.ema.above_21, row.ema.above_50, row.ema.above_200].filter(Boolean).length;
      return count + (row.ema.bullish_stack ? 0.5 : 0);
    }
    case "fromHigh": return row.pct_from_52wk_high ?? 9999;
    case "fromLow": return row.pct_from_52wk_low ?? -9999;
    case "turnover": return row.avg_turnover_cr_30d ?? -1;
    case "mcap": return row.market_cap_cr ?? -1;
    default: return 0;
  }
}

function sortedData() {
  const arr = FILTERED.slice();
  arr.sort((a, b) => {
    const va = sortValue(a, SORT_KEY), vb = sortValue(b, SORT_KEY);
    let cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return SORT_DIR === "asc" ? cmp : -cmp;
  });
  return arr;
}

function updateSortHeaderStyles() {
  document.querySelectorAll("th.sortable").forEach(th => {
    const key = th.dataset.sort;
    th.classList.toggle("sort-active", key === SORT_KEY);
    const existing = th.querySelector(".sort-arrow");
    if (existing) existing.remove();
    if (key === SORT_KEY) {
      const arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      arrow.textContent = SORT_DIR === "asc" ? "▲" : "▼";
      th.appendChild(arrow);
    }
  });
}

document.querySelectorAll("th.sortable").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (key === SORT_KEY) SORT_DIR = SORT_DIR === "asc" ? "desc" : "asc";
    else { SORT_KEY = key; SORT_DIR = "desc"; }
    updateSortHeaderStyles();
    renderResults();
  });
});

function fmt(v, suffix = "") {
  return (v === null || v === undefined) ? `<span class="muted">n/a</span>` : `${v}${suffix}`;
}

function updateSelectAllState() {
  const shown = sortedData();
  const allSelected = shown.length > 0 && shown.every(s => SELECTED.has(s.symbol));
  document.getElementById("select-all").checked = allSelected;
  document.getElementById("select-all-th").checked = allSelected;
  document.getElementById("copy-tv").textContent =
    SELECTED.size ? `Copy selected for TradingView (${SELECTED.size})` : "Copy selected for TradingView";
}

function renderResults() {
  const data = sortedData();
  document.getElementById("results-count").textContent = `${data.length} of ${ALL_STOCKS.length} stocks`;
  const tbody = document.getElementById("board-body");
  tbody.innerHTML = "";
  if (!data.length) {
    document.getElementById("board").classList.add("hidden");
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("empty-state").querySelector("p").textContent = "No stocks match these filters.";
    updateSelectAllState();
    return;
  }
  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("board").classList.remove("hidden");
  data.forEach((s) => {
    const tr = document.createElement("tr");
    const checked = SELECTED.has(s.symbol) ? "checked" : "";
    tr.innerHTML = `
      <td class="rank-col"><input type="checkbox" class="row-select" data-symbol="${s.symbol}" ${checked} /></td>
      <td class="sector-col"><a href="stock.html?symbol=${s.symbol}" target="_blank" class="stock-link">${s.symbol}</a><div class="muted" style="font-weight:400; font-size:11px;">${s.name || ""}</div></td>
      <td>${s.basic_industry || `<span class="muted">n/a</span>`}</td>
      <td>${fmt(s.close)}</td>
      <td>${rsRatingCell(s.rs_rating)}</td>
      <td>${returnCell(s.return_1m)}</td>
      <td>${returnCell(s.return_3m)}</td>
      <td>${stackLadder(s.ema)}</td>
      <td>${fmt(s.pct_from_52wk_high, "%")}</td>
      <td>${fmt(s.pct_from_52wk_low, "%")}</td>
      <td>${fmt(s.avg_turnover_cr_30d)}</td>
      <td>${fmt(s.market_cap_cr)}</td>
    `;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".row-select").forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) SELECTED.add(cb.dataset.symbol);
      else SELECTED.delete(cb.dataset.symbol);
      updateSelectAllState();
    });
  });
  updateSelectAllState();
}

function toggleSelectAllShown(checked) {
  const shown = sortedData();
  shown.forEach(s => {
    if (checked) SELECTED.add(s.symbol);
    else SELECTED.delete(s.symbol);
  });
  renderResults();
}
document.getElementById("select-all").addEventListener("change", (e) => toggleSelectAllShown(e.target.checked));
document.getElementById("select-all-th").addEventListener("change", (e) => toggleSelectAllShown(e.target.checked));

function buildTradingViewText(mode) {
  const bySymbol = new Map(ALL_STOCKS.map(s => [s.symbol, s]));
  const selected = [...SELECTED].map(sym => bySymbol.get(sym)).filter(Boolean);

  if (mode === "flat") {
    return selected.map(s => `NSE:${s.symbol}`).join(",");
  }

  // Industry-wise, matching ChartsMaze's actual copy output: one
  // continuous comma-separated line, each group's header token
  // "###IndustryName(count)" inline alongside its symbols -- not on its
  // own line. Confirmed directly against ChartsMaze's own copy button.
  const groups = new Map(); // industry -> [symbol,...]
  selected.forEach(s => {
    const key = s.basic_industry || "Unclassified";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(`NSE:${s.symbol}`);
  });
  const sortedKeys = [...groups.keys()].sort((a, b) => groups.get(b).length - groups.get(a).length);
  const parts = [];
  sortedKeys.forEach(k => {
    const syms = groups.get(k);
    // Some industry names contain a literal comma (e.g. "Gems, Jewellery
    // And Watches") -- since this whole format uses commas as the field
    // separator, an unstripped comma inside the name splits it into an
    // extra bogus "symbol" token when pasted into TradingView. Only
    // affects this copied string -- the real industry name elsewhere on
    // the site (dropdown, table, modal) is untouched.
    const safeName = k.replace(/,/g, "");
    parts.push(`###${safeName}(${syms.length})`);
    parts.push(...syms);
  });
  return parts.join(",");
}

document.getElementById("copy-tv").addEventListener("click", async () => {
  if (!SELECTED.size) {
    document.getElementById("copy-status").textContent = "Select at least one stock first";
    setTimeout(() => { document.getElementById("copy-status").textContent = ""; }, 2500);
    return;
  }
  const mode = document.getElementById("copy-mode").value;
  const text = buildTradingViewText(mode);
  try {
    await navigator.clipboard.writeText(text);
    document.getElementById("copy-status").textContent = `Copied ${SELECTED.size} symbols`;
  } catch (err) {
    // Clipboard API can fail on non-HTTPS/older browsers -- fall back to a
    // manual-copy textarea rather than leaving the user with nothing.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      document.execCommand("copy");
      document.getElementById("copy-status").textContent = `Copied ${SELECTED.size} symbols`;
    } catch (err2) {
      document.getElementById("copy-status").textContent = "Copy failed -- select and copy manually";
    }
    document.body.removeChild(ta);
  }
  setTimeout(() => { document.getElementById("copy-status").textContent = ""; }, 3000);
});

document.getElementById("f-apply").addEventListener("click", () => {
  saveFiltersToStorage();
  applyFilters();
});
document.getElementById("f-reset").addEventListener("click", () => {
  document.querySelectorAll(".filter-field input").forEach(el => {
    if (el.disabled) return;
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  });
  try { localStorage.removeItem(FILTER_STORAGE_KEY); } catch (err) {}
  applyFilters();
});
document.getElementById("search-box").addEventListener("input", (e) => {
  SEARCH_TERM = e.target.value.trim();
  applyFilters();
});

async function load() {
  loadFiltersFromStorage();
  try {
    const res = await fetch(SCANNER_URL);
    ALL_STOCKS = await res.json();
    updateSortHeaderStyles();
    FILTERED = ALL_STOCKS.slice();
    applyFilters();
    const dates = ALL_STOCKS.map(s => s.last_date).filter(Boolean);
    document.getElementById("asof").textContent = dates.length ? `as of ${dates.sort().pop()}` : "";
  } catch (err) {
    document.getElementById("asof").textContent = "couldn't load data";
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("board").classList.add("hidden");
  }
}

load();
