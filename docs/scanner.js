const SCANNER_URL = "data/stock_scanner.json";
// Industry-level breadth (>10MA, and its trend vs a week ago) -- the same
// numbers shown on the All Industries dashboard tab, computed from the
// FULL industry (every stock in it), not just whatever subset of it your
// scan filters happened to catch. Keyed by industry name, which comes
// from the same basic_industry_map source table compute_stock_scanner.py
// reads its own `basic_industry` field from -- so the names line up
// exactly, no fuzzy matching needed.
const INDUSTRIES_URL = "data/basic_industries.json";
let INDUSTRY_BREADTH_MAP = new Map(); // industry name -> breadth block

// Same idea, for NSE's real Sector tier (Financial Services, Healthcare,
// Consumer Discretionary...) -- Scan Summary's Sector mode groups by
// this same `sector` field, so it now has something real to look up
// too, instead of always showing n/a.
const SECTORS_BROAD_URL = "data/sectors_broad.json";
let SECTOR_BREADTH_MAP = new Map(); // sector name -> breadth block
const FILTER_STORAGE_KEY = "scannerFilters";
const PRESETS_STORAGE_KEY = "scannerPresets";

let ALL_STOCKS = [];
let FILTERED = [];
let SELECTED = new Set(); // symbols
let SEARCH_TERM = "";
let SORT_KEY = "turnover";
let SORT_DIR = "desc";

const FILTER_FIELD_IDS = [
  "f-ema-21", "f-ema-50", "f-ema-200",
  "f-high-max", "f-low-min",
  "f-price-min", "f-turnover-min", "f-rs-min",
  "f-mcap-min", "f-mcap-max",
  "f-return-period", "f-return-min", "f-return-max",
  "f-circuit-enable",
  "f-listing-months",
];

function captureFilterState() {
  const state = {};
  FILTER_FIELD_IDS.forEach(id => {
    const el = document.getElementById(id);
    state[id] = el.type === "checkbox" ? el.checked : el.value;
  });
  // Circuit band checkboxes share a class, not individual IDs -- stored
  // separately as the list of currently-checked band values.
  state["circuitBands"] = [...document.querySelectorAll(".f-circuit-band:checked")].map(cb => cb.value);
  return state;
}

function applyFilterState(state) {
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
  // The Return Range is now "on" whenever a min or max is set, so a saved
  // state that had it switched off must not keep stale numbers around
  // (they'd silently switch it back on).
  if ("f-return-enable" in state && !state["f-return-enable"]) {
    document.getElementById("f-return-min").value = "";
    document.getElementById("f-return-max").value = "";
  }
  refreshFilterUI();
}

function saveFiltersToStorage() {
  try {
    localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(captureFilterState()));
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
  applyFilterState(state);
}

function loadPresets() {
  try {
    const raw = localStorage.getItem(PRESETS_STORAGE_KEY);
    if (!raw) return { presets: {}, defaultName: null };
    const parsed = JSON.parse(raw);
    return { presets: parsed.presets || {}, defaultName: parsed.defaultName || null };
  } catch (err) {
    return { presets: {}, defaultName: null };
  }
}

function savePresetsToStorage(data) {
  try {
    localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(data));
  } catch (err) {
  }
}

function applyPreset(name) {
  const loaded = loadPresets();
  if (!loaded.presets[name]) return;
  applyFilterState(loaded.presets[name]);
  saveFiltersToStorage();
  applyFilters();
  document.querySelector("#preset-dropdown .dropdown-trigger").textContent = name;
}

function renderPresetDropdown() {
  const loaded = loadPresets();
  const names = Object.keys(loaded.presets).sort((a, b) => a.localeCompare(b));
  const container = document.getElementById("preset-options");
  container.innerHTML = "";
  if (!names.length) {
    const empty = document.createElement("div");
    empty.className = "preset-empty";
    empty.textContent = "No saved scanners yet";
    container.appendChild(empty);
    return;
  }
  names.forEach(function(name) {
    const isDefault = name === loaded.defaultName;

    const row = document.createElement("div");
    row.className = "preset-row";
    row.dataset.name = name; // safe regardless of what characters name contains -- no HTML parsing involved

    const label = document.createElement("span");
    label.className = "preset-name-label";
    label.textContent = name;

    const actions = document.createElement("span");
    actions.className = "preset-actions";

    const star = document.createElement("span");
    star.className = "preset-star" + (isDefault ? " active" : "");
    star.title = isDefault ? "Default -- click to unset" : "Set as default (auto-loads next time)";
    star.textContent = "\u2605";

    const del = document.createElement("span");
    del.className = "preset-delete";
    del.title = "Delete this saved scanner";
    del.textContent = "\u00d7";

    actions.appendChild(star);
    actions.appendChild(del);
    row.appendChild(label);
    row.appendChild(actions);
    container.appendChild(row);

    label.addEventListener("click", function() {
      applyPreset(name);
      closeAllMenus();
    });
    star.addEventListener("click", function(e) {
      e.stopPropagation();
      const data = loadPresets();
      data.defaultName = data.defaultName === name ? null : name;
      savePresetsToStorage(data);
      renderPresetDropdown();
    });
    del.addEventListener("click", function(e) {
      e.stopPropagation();
      if (!confirm("Delete saved scanner \"" + name + "\"?")) return;
      const data = loadPresets();
      delete data.presets[name];
      if (data.defaultName === name) data.defaultName = null;
      savePresetsToStorage(data);
      renderPresetDropdown();
      const trigger = document.querySelector("#preset-dropdown .dropdown-trigger");
      if (trigger.textContent === name) trigger.textContent = "Load scanner...";
    });
  });
}

document.getElementById("f-save-preset").addEventListener("click", function() {
  const name = prompt("Save current filters as:");
  if (!name || !name.trim()) return;
  const trimmed = name.trim();
  const data = loadPresets();
  data.presets[trimmed] = captureFilterState();
  savePresetsToStorage(data);
  renderPresetDropdown();
  document.querySelector("#preset-dropdown .dropdown-trigger").textContent = trimmed;
});

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
    rsMin: num("f-rs-min"),
    mcapMin: num("f-mcap-min"), mcapMax: num("f-mcap-max"),
    returnEnable: document.getElementById("f-return-enable").checked,
    returnPeriod: document.getElementById("f-return-period").value,
    returnMin: num("f-return-min"), returnMax: num("f-return-max"),
    circuitEnable: document.getElementById("f-circuit-enable").checked,
    circuitBands: [...document.querySelectorAll(".f-circuit-band:checked")].map(cb => parseInt(cb.value, 10)),
    listingMonths: num("f-listing-months"),
  };
}

function inRange(val, min, max) {
  if (val === null || val === undefined) return min === null && max === null;
  if (min !== null && val < min) return false;
  if (max !== null && val > max) return false;
  return true;
}

// True if one stock passes every active filter. Shared by applyFilters()
// (which builds the table) and the modal's live "N stocks match" counter.
function passesFilters(s, f) {
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
  // RS Rating (at least) -- a stock without a full year of history has
  // rs_rating = null and is excluded whenever this is set (no rating,
  // no evidence it qualifies).
  if (f.rsMin !== null && !(s.rs_rating !== null && s.rs_rating !== undefined && s.rs_rating >= f.rsMin)) return false;
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
  // Listed Within Last (months) -- a stock with no known listing_date
  // (not yet backfilled, or genuinely unavailable) is excluded rather
  // than passed through: unlike the EMA checks above, where "no data
  // yet" is expected for a young stock and shouldn't count against it,
  // here an unknown listing date means we can't confirm the stock
  // actually qualifies, so it doesn't get the benefit of the doubt.
  if (f.listingMonths !== null) {
    if (!s.listing_date) return false;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - f.listingMonths);
    if (new Date(s.listing_date) < cutoff) return false;
  }
  return true;
}

function applyFilters() {
  const f = readFilters();
  FILTERED = ALL_STOCKS.filter(s => passesFilters(s, f));
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
  refreshFilterUI();
  document.getElementById("filter-modal-overlay").classList.add("hidden");
});
document.getElementById("open-filters").addEventListener("click", () => {
  document.getElementById("filter-modal-overlay").classList.remove("hidden");
  refreshFilterUI();
});
document.getElementById("f-reset").addEventListener("click", () => {
  document.querySelectorAll(".filter-field-g input").forEach(el => {
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  });
  document.getElementById("f-return-period").value = "return_1m";
  refreshFilterUI();
  try { localStorage.removeItem(FILTER_STORAGE_KEY); } catch (err) {}
  applyFilters();
});
document.getElementById("search-box").addEventListener("input", (e) => {
  SEARCH_TERM = e.target.value.trim();
  applyFilters();
});

// ---------------------------------------------------------------------
// Filters modal UI. Every filter is optional: an empty field (or nothing
// toggled) means "not applied". The controls below are just a nicer skin
// over the same real inputs/checkboxes the rest of this file reads, so
// saved presets and applyFilters() are unchanged.
// ---------------------------------------------------------------------

// Return-range slider scale: evenly spaced stops, so 10% vs 25% is as easy
// to grab as 100% vs 500%. Dragging a handle to its end = no min / no max.
const RR_STOPS = [-50, 0, 10, 25, 50, 100, 200, 500];

function rrValueToPos(v) {
  const last = RR_STOPS.length - 1;
  if (v <= RR_STOPS[0]) return 0;
  if (v >= RR_STOPS[last]) return 100;
  for (let i = 0; i < last; i++) {
    if (v <= RR_STOPS[i + 1]) {
      return ((i + (v - RR_STOPS[i]) / (RR_STOPS[i + 1] - RR_STOPS[i])) / last) * 100;
    }
  }
  return 100;
}

function rrPosToValue(pos) {
  const last = RR_STOPS.length - 1;
  const x = (pos / 100) * last;
  const i = Math.min(Math.floor(x), last - 1);
  const v = RR_STOPS[i] + (x - i) * (RR_STOPS[i + 1] - RR_STOPS[i]);
  const a = Math.abs(v);
  const step = a < 10 ? 1 : a < 100 ? 5 : 10;
  return Math.round(v / step) * step;
}

function sameNum(a, b) {
  if (a === "" || b === "" || a === undefined || b === undefined) return (a || "") === (b || "");
  return parseFloat(a) === parseFloat(b);
}

function fieldIsActive(field) {
  const kind = field.dataset.filter;
  if (kind === "return") return document.getElementById("f-return-enable").checked;
  if (kind === "circuit") return document.getElementById("f-circuit-enable").checked;
  return [...field.querySelectorAll("input")].some(el =>
    el.type === "checkbox" ? el.checked : el.value !== ""
  );
}

function rrPos(id, emptyPos) {
  const v = document.getElementById(id).value;
  return v === "" ? emptyPos : rrValueToPos(parseFloat(v));
}

function refreshFilterUI() {
  const $ = id => document.getElementById(id);

  // Return range is on whenever a min or max is present.
  const rMin = $("f-return-min").value, rMax = $("f-return-max").value;
  $("f-return-enable").checked = rMin !== "" || rMax !== "";

  // Band chips only work while the master switch is on.
  const circuitOn = $("f-circuit-enable").checked;
  document.querySelectorAll(".f-circuit-band").forEach(cb => { cb.disabled = !circuitOn; });

  // Which filters are active.
  let active = 0;
  document.querySelectorAll("#filter-modal-overlay .filter-field-g[data-filter]").forEach(field => {
    const on = fieldIsActive(field);
    field.classList.toggle("is-active", on);
    if (on) active++;
  });
  $("f-active-count").textContent = active ? `${active} active` : "No filters active";

  // Quick-fill chips (RS rating, market cap min): highlighted when they match the box.
  document.querySelectorAll("[data-fill-target]").forEach(btn => {
    const input = $(btn.dataset.fillTarget);
    btn.classList.toggle("on", input.value !== "" && sameNum(input.value, btn.dataset.fillValue));
  });

  // Return-range chips + period tabs.
  document.querySelectorAll("[data-rr]").forEach(btn => {
    btn.classList.toggle("on", sameNum(rMin, btn.dataset.rrMin) && sameNum(rMax, btn.dataset.rrMax));
  });
  const period = $("f-return-period").value;
  document.querySelectorAll("[data-period]").forEach(btn => {
    btn.classList.toggle("on", btn.dataset.period === period);
  });

  // Return-range track: handles + fill follow the two boxes.
  const minPos = rrPos("f-return-min", 0), maxPos = rrPos("f-return-max", 100);
  const lo = Math.min(minPos, maxPos), hi = Math.max(minPos, maxPos);
  const fill = $("rr-fill");
  fill.style.left = lo + "%";
  fill.style.width = (hi - lo) + "%";
  const idle = rMin === "" && rMax === "";
  fill.classList.toggle("dim", idle);
  $("rr-h-min").style.left = minPos + "%";
  $("rr-h-max").style.left = maxPos + "%";
  $("rr-h-min").classList.toggle("dim", idle);
  $("rr-h-max").classList.toggle("dim", idle);
  $("rr-h-min").setAttribute("aria-valuetext", rMin === "" ? "No minimum" : `${rMin}%`);
  $("rr-h-max").setAttribute("aria-valuetext", rMax === "" ? "No maximum" : `${rMax}%`);

  // 52-week visual.
  const hi52 = $("f-high-max").value, lo52 = $("f-low-min").value;
  $("fp-zone").style.width = hi52 === "" ? "0%" : Math.max(0, Math.min(100, parseFloat(hi52))) + "%";
  $("fp-high-text").textContent = hi52 === "" ? "Any distance from high" : `within ${hi52}% of high`;
  $("fp-low-text").textContent = lo52 === "" ? "Any distance from low" : `at least ${lo52}% above low`;

  // Live match count (what Apply would show, ignoring the search box).
  if (ALL_STOCKS.length) {
    const f = readFilters();
    let n = 0;
    for (const s of ALL_STOCKS) if (passesFilters(s, f)) n++;
    $("f-match-count").textContent = n.toLocaleString();
    $("f-match-total").textContent = ALL_STOCKS.length.toLocaleString();
  }
}

function fireInput(el) {
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

(function initFilterModalUI() {
  const overlay = document.getElementById("filter-modal-overlay");
  overlay.addEventListener("input", refreshFilterUI);
  overlay.addEventListener("change", refreshFilterUI);

  // Small x on each simple field, shown only while it is active.
  overlay.querySelectorAll(".filter-field-g[data-filter] .field-head").forEach(head => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "field-clear";
    btn.title = "Clear this filter";
    btn.setAttribute("aria-label", "Clear this filter");
    btn.textContent = "\u00d7";
    btn.addEventListener("click", () => {
      head.closest(".filter-field-g").querySelectorAll("input").forEach(el => {
        if (el.type === "checkbox") el.checked = false;
        else el.value = "";
      });
      refreshFilterUI();
    });
    head.appendChild(btn);
  });

  // RS rating / market cap quick chips: click to fill, click again to clear.
  overlay.querySelectorAll("[data-fill-target]").forEach(btn => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.fillTarget);
      input.value = sameNum(input.value, btn.dataset.fillValue) && input.value !== "" ? "" : btn.dataset.fillValue;
      fireInput(input);
    });
  });

  // Return range presets ("Any" clears both boxes).
  overlay.querySelectorAll("[data-rr]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("f-return-min").value = btn.dataset.rrMin ?? "";
      document.getElementById("f-return-max").value = btn.dataset.rrMax ?? "";
      fireInput(document.getElementById("f-return-min"));
    });
  });

  // Return period tabs drive the (hidden) select the rest of the file reads.
  overlay.querySelectorAll("[data-period]").forEach(btn => {
    btn.addEventListener("click", () => {
      const sel = document.getElementById("f-return-period");
      sel.value = btn.dataset.period;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  // Draggable dual-handle track. The number boxes stay the source of truth.
  const track = document.getElementById("rr-track");
  const hMin = document.getElementById("rr-h-min");
  const hMax = document.getElementById("rr-h-max");
  const minEl = document.getElementById("f-return-min");
  const maxEl = document.getElementById("f-return-max");
  let dragging = null;

  function setFromPos(which, pos) {
    pos = Math.max(0, Math.min(100, pos));
    let el, open;
    if (which === "min") {
      pos = Math.min(pos, rrPos("f-return-max", 100));
      el = minEl; open = pos <= 0.4;
    } else {
      pos = Math.max(pos, rrPos("f-return-min", 0));
      el = maxEl; open = pos >= 99.6;
    }
    el.value = open ? "" : String(rrPosToValue(pos));
    fireInput(el);
  }
  function pctFromEvent(e) {
    const r = track.getBoundingClientRect();
    return r.width ? ((e.clientX - r.left) / r.width) * 100 : 0;
  }
  track.addEventListener("pointerdown", (e) => {
    const p = pctFromEvent(e);
    const dMin = Math.abs(p - rrPos("f-return-min", 0)), dMax = Math.abs(p - rrPos("f-return-max", 100));
    if (e.target === hMin) dragging = "min";
    else if (e.target === hMax) dragging = "max";
    else dragging = dMin < dMax ? "min" : dMax < dMin ? "max" : (p < rrPos("f-return-min", 0) ? "min" : "max");
    try { track.setPointerCapture(e.pointerId); } catch (err) {}
    (dragging === "min" ? hMin : hMax).focus();
    setFromPos(dragging, p);
    e.preventDefault();
  });
  track.addEventListener("pointermove", (e) => {
    if (dragging) setFromPos(dragging, pctFromEvent(e));
  });
  ["pointerup", "pointercancel"].forEach(t => track.addEventListener(t, () => { dragging = null; }));
  [[hMin, "min", "f-return-min", 0], [hMax, "max", "f-return-max", 100]].forEach(([h, which, id, empty]) => {
    h.addEventListener("keydown", (e) => {
      const dir = (e.key === "ArrowRight" || e.key === "ArrowUp") ? 1 : (e.key === "ArrowLeft" || e.key === "ArrowDown") ? -1 : 0;
      if (!dir) return;
      e.preventDefault();
      setFromPos(which, rrPos(id, empty) + dir * 2);
    });
  });
})();

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

let SUMMARY_MODE = "sector";     // "sector" | "industry"
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
  document.getElementById("summary-col-breadth").textContent = isSector ? "Sector Breadth >10MA" : "Industry Breadth >10MA";

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
    // Only Basic Industry mode's `category` (s.basic_industry) shares its
    // source table with basic_industries.json's `industry` field, so the
    // lookup is an exact match there. Sector mode's `category` (s.sector)
    // is NSE's Macro-Economic Sector tier, a DIFFERENT classification
    // from the 24 index-based Sectoral Indices (Bank, IT, Pharma...) that
    // basic_industries.json/leaderboard.json don't cover -- so it never
    // gets a real lookup here, rather than silently showing a wrong number.
    // Basic Industry mode's `category` (s.basic_industry) and Sector
    // mode's `category` (s.sector) each now have their own real,
    // separately-computed breadth map -- basic_industries.json and
    // sectors_broad.json respectively, both keyed by the exact same
    // classification names basic_industry_map itself uses, so both
    // lookups are exact matches, no fuzzy logic needed.
    let breadthCellHtml = `<span class="muted">n/a</span>`;
    let trendCellHtml = `<span class="muted">–</span>`;
    let breadthSortVal = -1;
    let trendSortVal = -999;
    const b = isSector ? SECTOR_BREADTH_MAP.get(category) : INDUSTRY_BREADTH_MAP.get(category);
    if (b && b.available) {
      const sampleCls = b.low_sample ? "n-stocks low-sample" : "n-stocks";
      const sampleTitle = b.low_sample ? `title="Only ${b.n_stocks} stocks -- read with more caution"` : "";
      breadthCellHtml = `<span class="breadth-val">${b.pct_above_10ma}%</span> <span class="${sampleCls}" ${sampleTitle}>(${b.n_stocks})</span>`;
      breadthSortVal = b.pct_above_10ma;
      if (b.pct_above_10ma_week_ago !== null && b.pct_above_10ma_week_ago !== undefined) {
        const diff = b.pct_above_10ma - b.pct_above_10ma_week_ago;
        trendSortVal = diff;
        if (diff > 1) trendCellHtml = `<span class="trend-up">▲ ${diff.toFixed(1)}pt</span>`;
        else if (diff < -1) trendCellHtml = `<span class="trend-down">▼ ${Math.abs(diff).toFixed(1)}pt</span>`;
        else trendCellHtml = `<span class="trend-flat">flat</span>`;
      }
    } else {
      const reason = isSector
        ? "No dashboard data for this sector (too few stocks with sector classification, or a name that didn't match)"
        : "No dashboard data for this industry (too few stocks with history, or a name that didn't match)";
      breadthCellHtml = `<span class="muted" title="${reason}">n/a</span>`;
    }
    return { category, count, pct, color, breadthCellHtml, trendCellHtml, breadthSortVal, trendSortVal };
  });
  if (SUMMARY_SORT_KEY === "breadth" || SUMMARY_SORT_KEY === "breadthTrend") {
    rows.sort((a, b) => {
      const cmp = SUMMARY_SORT_KEY === "breadth"
        ? a.breadthSortVal - b.breadthSortVal
        : a.trendSortVal - b.trendSortVal;
      return SUMMARY_SORT_DIR === "asc" ? cmp : -cmp;
    });
  }
  document.getElementById("summary-table-body").innerHTML = rows.length
    ? rows.map(r => `<tr><td><span class="swatch" style="background:${r.color}"></span>${r.category}</td><td>${r.count}</td><td>${r.pct.toFixed(1)}%</td><td>${r.breadthCellHtml}</td><td>${r.trendCellHtml}</td></tr>`).join("")
    : `<tr><td colspan="5" class="muted">No stocks match the current filters</td></tr>`;

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
  renderPresetDropdown();
  const { presets, defaultName } = loadPresets();
  if (defaultName && presets[defaultName]) {
    applyFilterState(presets[defaultName]);
    document.querySelector("#preset-dropdown .dropdown-trigger").textContent = defaultName;
  } else {
    loadFiltersFromStorage();
  }
  try {
    const [scannerRes, industriesRes, sectorsBroadRes] = await Promise.all([
      fetch(SCANNER_URL),
      fetch(INDUSTRIES_URL),
      fetch(SECTORS_BROAD_URL),
    ]);
    ALL_STOCKS = await scannerRes.json();
    // Best-effort: the Scan Summary's breadth columns just show "n/a" if
    // either of these fails to load, everything else on the page still works.
    try {
      const industriesData = await industriesRes.json();
      const list = industriesData.industries || [];
      INDUSTRY_BREADTH_MAP = new Map(list.map(ind => [ind.industry, ind.breadth]));
    } catch (industriesErr) {
      INDUSTRY_BREADTH_MAP = new Map();
    }
    try {
      const sectorsBroadData = await sectorsBroadRes.json();
      const list = sectorsBroadData.sectors || [];
      SECTOR_BREADTH_MAP = new Map(list.map(s => [s.sector, s.breadth]));
    } catch (sectorsErr) {
      SECTOR_BREADTH_MAP = new Map();
    }
    updateSortHeaderStyles();
    FILTERED = ALL_STOCKS.slice();
    applyFilters();
    refreshFilterUI();
    const dates = ALL_STOCKS.map(s => s.last_date).filter(Boolean);
    document.getElementById("asof").textContent = dates.length ? `as of ${dates.sort().pop()}` : "";
  } catch (err) {
    document.getElementById("asof").textContent = "couldn't load data";
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("board").classList.add("hidden");
  }
}

load();
