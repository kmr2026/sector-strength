const SCANNER_URL = "data/stock_scanner.json";

let ALL_STOCKS = [];
let FILTERED = [];
let SELECTED = new Set(); // symbols
let SEARCH_TERM = "";
let SORT_KEY = "turnover";
let SORT_DIR = "desc";

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
    highMin: num("f-high-min"), highMax: num("f-high-max"),
    lowMin: num("f-low-min"), lowMax: num("f-low-max"),
    priceMin: num("f-price-min"), priceMax: num("f-price-max"),
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
    if (f.ema21 && !(s.ema && s.ema.available && s.ema.above_21)) return false;
    if (f.ema50 && !(s.ema && s.ema.available && s.ema.above_50)) return false;
    if (f.ema200 && !(s.ema && s.ema.available && s.ema.above_200)) return false;
    if (!inRange(s.pct_from_52wk_high, f.highMin, f.highMax)) return false;
    if (!inRange(s.pct_from_52wk_low, f.lowMin, f.lowMax)) return false;
    if (!inRange(s.close, f.priceMin, f.priceMax)) return false;
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
      <td class="sector-col">${s.symbol}<div class="muted" style="font-weight:400; font-size:11px;">${s.name || ""}</div></td>
      <td>${s.basic_industry || `<span class="muted">n/a</span>`}</td>
      <td>${fmt(s.close)}</td>
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

function buildTradingViewText() {
  const bySymbol = new Map(ALL_STOCKS.map(s => [s.symbol, s]));
  const selected = [...SELECTED].map(sym => bySymbol.get(sym)).filter(Boolean);
  const groups = new Map(); // industry -> [symbol,...]
  selected.forEach(s => {
    const key = s.basic_industry || "Unclassified";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(`NSE:${s.symbol}`);
  });
  const sortedKeys = [...groups.keys()].sort();
  return sortedKeys.map(k => `###${k}\n${groups.get(k).join(",")}`).join("\n");
}

document.getElementById("copy-tv").addEventListener("click", async () => {
  if (!SELECTED.size) {
    document.getElementById("copy-status").textContent = "Select at least one stock first";
    setTimeout(() => { document.getElementById("copy-status").textContent = ""; }, 2500);
    return;
  }
  const text = buildTradingViewText();
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

document.getElementById("f-apply").addEventListener("click", applyFilters);
document.getElementById("f-reset").addEventListener("click", () => {
  document.querySelectorAll(".filter-field input").forEach(el => {
    if (el.disabled) return;
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  });
  applyFilters();
});
document.getElementById("search-box").addEventListener("input", (e) => {
  SEARCH_TERM = e.target.value.trim();
  applyFilters();
});

async function load() {
  try {
    const res = await fetch(SCANNER_URL);
    ALL_STOCKS = await res.json();
    updateSortHeaderStyles();
    FILTERED = ALL_STOCKS.slice();
    renderResults();
    const dates = ALL_STOCKS.map(s => s.last_date).filter(Boolean);
    document.getElementById("asof").textContent = dates.length ? `as of ${dates.sort().pop()}` : "";
  } catch (err) {
    document.getElementById("asof").textContent = "couldn't load data";
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("board").classList.add("hidden");
  }
}

load();
