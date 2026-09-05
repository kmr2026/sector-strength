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
  "f-return-period", "f-return-min", "f-return-max",
  "f-circuit-enable",
];

function saveFiltersToStorage() {
  const state = {};
  FILTER_FIELD_IDS.forEach(id => {
    const el = document.getElementById(id);
    state[id] = el.type === "checkbox" ? el.checked : el.value;
  });
  // Circuit band checkboxes share a class, not individual IDs -- stored
  // separately as the list of currently-checked band values.
  state["circuitBands"] = [...document.querySelectorAll(".f-circuit-band:checked")].map(cb => cb.value);
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
  if (Array.isArray(state.circuitBands)) {
    document.querySelectorAll(".f-circuit-band").forEach(cb => {
      cb.checked = state.circuitBands.includes(cb.value);
    });
  }
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
    returnEnable: document.getElementById("f-return-enable").checked,
    returnPeriod: document.getElementById("f-return-period").value,
    returnMin: num("f-return-min"), returnMax: num("f-return-max"),
    circuitEnable: document.getElementById("f-circuit-enable").checked,
    circuitBands: [...document.querySelectorAll(".f-circuit-band:checked")].map(cb => parseInt(cb.value, 10)),
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
    // Return Range% -- only applies at all if its own checkbox is
    // checked, not just because a min/max happens to be typed in (those
    // boxes stay disabled until the checkbox is on, but this guards it
    // explicitly regardless).
    if (f.returnEnable && !inRange(s[f.returnPeriod], f.returnMin, f.returnMax)) return false;
    // Exclude Circuit Stocks -- excludes by the stock's currently
    // ASSIGNED band (2/5/10%), not by whether it's actually locked at
    // that limit today. A stock with no assigned band (F&O-eligible) is
    // never excluded by this filter, regardless of which boxes are checked.
    if (f.circuitEnable && f.circuitBands.length && s.circuit_band !== null && s.circuit_band !== undefined
        && f.circuitBands.includes(s.circuit_band)) return false;
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
  document.getElementById("select-all-th").checked = allSelected;
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

async function copyText(text, count) {
  try {
    await navigator.clipboard.writeText(text);
    document.getElementById("copy-status").textContent = `Copied ${count} symbols`;
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
      document.getElementById("copy-status").textContent = `Copied ${count} symbols`;
    } catch (err2) {
      document.getElementById("copy-status").textContent = "Copy failed -- select and copy manually";
    }
    document.body.removeChild(ta);
  }
  setTimeout(() => { document.getElementById("copy-status").textContent = ""; }, 3000);
}

function flashNoSelection() {
  document.getElementById("copy-status").textContent = "Select at least one stock first";
  setTimeout(() => { document.getElementById("copy-status").textContent = ""; }, 2500);
}

function closeAllMenus() {
  document.getElementById("copy-menu").classList.remove("open");
  document.getElementById("batches-submenu").classList.remove("open");
  document.querySelectorAll(".dropdown-trigger.open").forEach(t => t.classList.remove("open"));
  document.querySelectorAll(".dropdown-options.open").forEach(o => o.classList.remove("open"));
}

document.querySelector("#open-copy > svg").addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = document.getElementById("copy-menu");
  const willOpen = !menu.classList.contains("open");
  closeAllMenus();
  if (willOpen) menu.classList.add("open");
});

document.getElementById("copy-flat").addEventListener("click", () => {
  if (!SELECTED.size) { flashNoSelection(); return; }
  copyText(buildTradingViewText("flat"), SELECTED.size);
  closeAllMenus();
});

document.getElementById("copy-industry").addEventListener("click", () => {
  if (!SELECTED.size) { flashNoSelection(); return; }
  copyText(buildTradingViewText("industry"), SELECTED.size);
  closeAllMenus();
});

function populateBatchesSubmenu() {
  const submenu = document.getElementById("batches-submenu");
  const total = SELECTED.size;
  if (total === 0) {
    submenu.innerHTML = `<div class="batches-submenu-item muted">No stocks selected</div>`;
    return;
  }
  const symbolsInOrder = [...SELECTED];
  const batchCount = Math.ceil(total / 30);
  let html = "";
  for (let i = 0; i < batchCount; i++) {
    const start = i * 30;
    const end = Math.min((i + 1) * 30, total);
    html += `<div class="batches-submenu-item" data-start="${start}" data-end="${end}">${start + 1}-${end}</div>`;
  }
  submenu.innerHTML = html;
  submenu.querySelectorAll(".batches-submenu-item[data-start]").forEach(item => {
    item.addEventListener("click", () => {
      const start = parseInt(item.dataset.start, 10);
      const end = parseInt(item.dataset.end, 10);
      const slice = symbolsInOrder.slice(start, end);
      const text = slice.map(sym => `NSE:${sym}`).join(",");
      copyText(text, slice.length);
      closeAllMenus();
    });
  });
}

document.getElementById("copy-batches-trigger").addEventListener("click", (e) => {
  e.stopPropagation();
  const submenu = document.getElementById("batches-submenu");
  const willOpen = !submenu.classList.contains("open");
  submenu.classList.remove("open");
  if (willOpen) {
    populateBatchesSubmenu();
    submenu.classList.add("open");
  }
});

document.getElementById("f-apply").addEventListener("click", () => {
  saveFiltersToStorage();
  applyFilters();
  document.getElementById("filter-modal-overlay").classList.add("hidden");
});
document.getElementById("close-filters").addEventListener("click", () => {
  // Discard unsaved edits -- restore inputs to whatever was last actually
  // applied, rather than leaving half-typed values sitting in the form
  // for next time the modal opens.
  loadFiltersFromStorage();
  syncCircuitBandToggle();
  syncReturnRangeToggle();
  syncEmaDropdownLabel();
  syncCircuitDropdownLabel();
  document.getElementById("filter-modal-overlay").classList.add("hidden");
});
document.getElementById("open-filters").addEventListener("click", () => {
  document.getElementById("filter-modal-overlay").classList.remove("hidden");
});
document.getElementById("f-reset").addEventListener("click", () => {
  document.querySelectorAll(".filter-field-g input").forEach(el => {
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  });
  document.getElementById("f-return-period").value = "return_1m";
  syncCircuitBandToggle();
  syncReturnRangeToggle();
  syncEmaDropdownLabel();
  syncCircuitDropdownLabel();
  try { localStorage.removeItem(FILTER_STORAGE_KEY); } catch (err) {}
  applyFilters();
});
document.getElementById("search-box").addEventListener("input", (e) => {
  SEARCH_TERM = e.target.value.trim();
  applyFilters();
});

function syncCircuitBandToggle() {
  const enabled = document.getElementById("f-circuit-enable").checked;
  document.querySelectorAll(".f-circuit-band").forEach(cb => { cb.disabled = !enabled; });
}
document.getElementById("f-circuit-enable").addEventListener("change", syncCircuitBandToggle);

function syncReturnRangeToggle() {
  const enabled = document.getElementById("f-return-enable").checked;
  document.getElementById("f-return-period").disabled = !enabled;
  document.getElementById("f-return-min").disabled = !enabled;
  document.getElementById("f-return-max").disabled = !enabled;
}
document.getElementById("f-return-enable").addEventListener("change", syncReturnRangeToggle);

function syncEmaDropdownLabel() {
  const selected = [];
  if (document.getElementById("f-ema-21").checked) selected.push("21");
  if (document.getElementById("f-ema-50").checked) selected.push("50");
  if (document.getElementById("f-ema-200").checked) selected.push("200");
  document.querySelector('#ema-dropdown .dropdown-trigger').textContent =
    selected.length ? `${selected.join(", ")} EMA` : "Any EMA";
}
["f-ema-21", "f-ema-50", "f-ema-200"].forEach(id => {
  document.getElementById(id).addEventListener("change", syncEmaDropdownLabel);
});

function syncCircuitDropdownLabel() {
  const selected = [...document.querySelectorAll(".f-circuit-band:checked")].map(cb => cb.value);
  document.querySelector('#circuit-dropdown .dropdown-trigger').textContent =
    selected.length ? `${selected.join("%, ")}% Circuit` : "Select band(s)";
}
document.querySelectorAll(".f-circuit-band").forEach(cb => {
  cb.addEventListener("change", syncCircuitDropdownLabel);
});

// Dropdown open/close -- clicking a trigger opens its own options panel
// (closing any other open one first); clicking anywhere truly outside a
// dropdown/menu closes everything. Checkbox clicks INSIDE an open panel
// don't close it, since they're not "outside" clicks.
document.querySelectorAll(".dropdown-trigger").forEach(trigger => {
  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    const targetId = trigger.dataset.target;
    const isOpen = trigger.classList.contains("open");
    closeAllMenus();
    if (!isOpen) {
      trigger.classList.add("open");
      document.getElementById(targetId).classList.add("open");
    }
  });
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".dropdown-select") && !e.target.closest("#open-copy")) {
    closeAllMenus();
  }
});

const SUMMARY_COLORS = [
  "#3fb950", "#d29922", "#4f8ef7", "#e05fa0", "#7c5cf7", "#f85149", "#2dd4bf", "#eab308",
  "#8b5cf6", "#22c55e", "#f472b6", "#38bdf8", "#fb923c", "#a3e635", "#c084fc",
];
const SUMMARY_OTHER_COLOR = "#7c8797";

let SUMMARY_MODE = "industry";   // "industry" | "sector"
let SUMMARY_SORT_KEY = "count";  // "count" | "pct"
let SUMMARY_SORT_DIR = "desc";

function summaryGroupKey(s) {
  if (SUMMARY_MODE === "sector") return s.sector || "Unclassified";
  return s.basic_industry || "Unclassified";
}

function updateSummarySortHeaderStyles() {
  document.querySelectorAll(".summary-sortable").forEach(th => {
    const key = th.dataset.sort;
    th.classList.toggle("sort-active", key === SUMMARY_SORT_KEY);
    const existing = th.querySelector(".sort-arrow");
    if (existing) existing.remove();
    if (key === SUMMARY_SORT_KEY) {
      const arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      arrow.textContent = SUMMARY_SORT_DIR === "asc" ? "▲" : "▼";
      th.appendChild(arrow);
    }
  });
}

function renderScanSummary() {
  const total = FILTERED.length;
  document.getElementById("summary-total").textContent = total;

  const isSector = SUMMARY_MODE === "sector";
  document.getElementById("summary-col-label").textContent = isSector ? "Sector" : "Basic Industry";
  document.getElementById("summary-col-pct").textContent = isSector ? "% of Sector" : "% of Industry";

  const counts = new Map(); // category -> count among FILTERED
  FILTERED.forEach(s => {
    const key = summaryGroupKey(s);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const categoryTotals = new Map(); // category -> count across the FULL universe
  ALL_STOCKS.forEach(s => {
    const key = summaryGroupKey(s);
    categoryTotals.set(key, (categoryTotals.get(key) || 0) + 1);
  });

  // Pie order is always by raw count, descending -- this decides which
  // categories get their own slice/color and which fall into "Other".
  // Table order (below) is independent and follows whatever column the
  // user has sorted by, so re-sorting the table never reshuffles colors.
  const byCountDesc = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  // Basic Industry has 100+ categories -- cap the pie at 15 slices so it
  // stays readable, and bucket the rest into "Other". Sector has only
  // ~13 categories total, so the cap never actually bites and every
  // sector gets its own slice, matching ChartsMaze.
  const pieCap = isSector ? byCountDesc.length : 15;
  const pieTop = byCountDesc.slice(0, pieCap);
  const pieRest = byCountDesc.slice(pieCap);
  const pieRestSum = pieRest.reduce((acc, [, c]) => acc + c, 0);

  const colorMap = new Map();
  pieTop.forEach(([category], i) => colorMap.set(category, SUMMARY_COLORS[i % SUMMARY_COLORS.length]));

  let cursor = 0;
  const gradientParts = [];
  pieTop.forEach(([category, count]) => {
    const pct = total > 0 ? (count / total) * 100 : 0;
    gradientParts.push(`${colorMap.get(category)} ${cursor}% ${cursor + pct}%`);
    cursor += pct;
  });
  if (pieRest.length && pieRestSum > 0) {
    const pct = total > 0 ? (pieRestSum / total) * 100 : 0;
    gradientParts.push(`${SUMMARY_OTHER_COLOR} ${cursor}% ${cursor + pct}%`);
    cursor += pct;
  }
  document.getElementById("summary-donut").style.background =
    gradientParts.length ? `conic-gradient(${gradientParts.join(", ")})` : "var(--panel-2)";

  // Table always lists every category (scrollable), independent of the
  // pie's top-15 cap -- sorted by whichever column the user picked.
  const tableRows = [...counts.entries()].map(([category, count]) => {
    const categoryTotal = categoryTotals.get(category) || count;
    const pct = categoryTotal > 0 ? (count / categoryTotal) * 100 : 0;
    return { category, count, pct };
  });
  tableRows.sort((a, b) => {
    const va = SUMMARY_SORT_KEY === "pct" ? a.pct : a.count;
    const vb = SUMMARY_SORT_KEY === "pct" ? b.pct : b.count;
    const cmp = va - vb;
    return SUMMARY_SORT_DIR === "asc" ? cmp : -cmp;
  });

  const rows = tableRows.map(({ category, count, pct }) => {
    const color = colorMap.get(category) || SUMMARY_OTHER_COLOR;
    return `<tr><td><span class="swatch" style="background:${color}"></span>${category}</td><td>${count}</td><td>${pct.toFixed(1)}%</td></tr>`;
  });
  document.getElementById("summary-table-body").innerHTML =
    rows.length ? rows.join("") : `<tr><td colspan="3" class="muted">No stocks match the current filters</td></tr>`;

  updateSummarySortHeaderStyles();
}

document.querySelectorAll("#summary-mode-toggle .mode-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("active")) return;
    document.querySelectorAll("#summary-mode-toggle .mode-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    SUMMARY_MODE = btn.dataset.mode;
    renderScanSummary();
  });
});

document.querySelectorAll(".summary-sortable").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (key === SUMMARY_SORT_KEY) SUMMARY_SORT_DIR = SUMMARY_SORT_DIR === "asc" ? "desc" : "asc";
    else { SUMMARY_SORT_KEY = key; SUMMARY_SORT_DIR = "desc"; }
    renderScanSummary();
  });
});

document.getElementById("open-summary").addEventListener("click", () => {
  renderScanSummary();
  document.getElementById("summary-modal-overlay").classList.remove("hidden");
});
document.getElementById("close-summary").addEventListener("click", () => {
  document.getElementById("summary-modal-overlay").classList.add("hidden");
});

async function load() {
  loadFiltersFromStorage();
  // A restored "enabled" state from localStorage needs its sub-controls
  // un-disabled to match -- these two run the same sync the change
  // listeners above do, just once on load.
  syncCircuitBandToggle();
  syncReturnRangeToggle();
  syncEmaDropdownLabel();
  syncCircuitDropdownLabel();
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
