const SECTORS_URL = "data/leaderboard.json";
const INDUSTRIES_URL = "data/basic_industries.json";

let CURRENT_VIEW = "sectors";
let CACHE = { sectors: null, industries: null };
let CURRENT_DATA = [];
let SORT_KEY = "score";
let SORT_DIR = "desc"; // "asc" | "desc"
let SEARCH_TERM = "";

function scoreClass(score) {
  if (score >= 65) return "score-high";
  if (score >= 40) return "score-mid";
  return "score-low";
}

function scoreDeltaHtml(delta) {
  if (!delta || !delta.available) return "";
  const d = delta.delta;
  if (d > 0) return `<span class="score-delta up">▲${d}</span>`;
  if (d < 0) return `<span class="score-delta down">▼${Math.abs(d)}</span>`;
  return `<span class="score-delta flat">–</span>`;
}

function stackLadder(ema) {
  if (!ema.available) return `<span class="muted">n/a</span>`;
  const bars = [
    ["21", ema.above_21],
    ["50", ema.above_50],
    ["200", ema.above_200],
  ];
  const html = bars.map(([label, on]) => {
    if (on === null || on === undefined) return `<div class="stack-bar" title="${label} EMA: no data"></div>`;
    return `<div class="stack-bar ${on ? "on" : "off"}" title="${label} EMA: ${on ? "above" : "below"}"></div>`;
  }).join("");
  const extendedTag = ema.extended ? `<span class="extended-flag">EXT</span>` : "";
  return `<div class="stack-ladder">${html}</div>${extendedTag}`;
}

function breadthCell(breadth) {
  if (!breadth.available) return { val: `<span class="muted">n/a</span>`, trend: "" };
  const countCls = breadth.low_sample ? "n-stocks low-sample" : "n-stocks";
  const countTitle = breadth.low_sample ? `title="Only ${breadth.n_stocks} stocks -- fewer than usual, read this one with more caution"` : "";
  const val = `<span class="breadth-val">${breadth.pct_above_10ma}%</span> <span class="${countCls}" ${countTitle}>(${breadth.n_stocks})</span>`;
  let trend = `<span class="trend-flat">flat</span>`;
  if (breadth.pct_above_10ma_week_ago !== null) {
    const diff = breadth.pct_above_10ma - breadth.pct_above_10ma_week_ago;
    if (diff > 1) trend = `<span class="trend-up">▲ ${diff.toFixed(1)}pt</span>`;
    else if (diff < -1) trend = `<span class="trend-down">▼ ${Math.abs(diff).toFixed(1)}pt</span>`;
  }
  return { val, trend };
}

function breadth21Cell(breadth) {
  if (!breadth.available || breadth.pct_above_21ma === null || breadth.pct_above_21ma === undefined) {
    return { val: `<span class="muted">n/a</span>`, trend: "" };
  }
  const valCls = breadth.overheated ? "breadth-val overheated" : "breadth-val";
  const valTitle = breadth.overheated
    ? `title="${breadth.pct_above_21ma}% of stocks already above their 21MA -- this move may be crowded/late"`
    : "";
  const val = `<span class="${valCls}" ${valTitle}>${breadth.pct_above_21ma}%</span> <span class="n-stocks">(${breadth.n_stocks})</span>`;
  let trend = `<span class="trend-flat">flat</span>`;
  if (breadth.pct_above_21ma_week_ago !== null && breadth.pct_above_21ma_week_ago !== undefined) {
    const diff = breadth.pct_above_21ma - breadth.pct_above_21ma_week_ago;
    if (diff > 1) trend = `<span class="trend-up">▲ ${diff.toFixed(1)}pt</span>`;
    else if (diff < -1) trend = `<span class="trend-down">▼ ${Math.abs(diff).toFixed(1)}pt</span>`;
  }
  return { val, trend };
}

function metricDeltaHtml(delta) {
  if (!delta || !delta.available) return "";
  const d = delta.delta;
  if (d > 0) return `<span class="score-delta up">▲${d}</span>`;
  if (d < 0) return `<span class="score-delta down">▼${Math.abs(d)}</span>`;
  return `<span class="score-delta flat">–</span>`;
}

function high52Cell(high52) {
  if (!high52 || !high52.available) return `<span class="muted">n/a</span>`;
  return `<span class="breadth-val">${high52.pct_within_52wk_high}%</span> <span class="n-stocks">(${high52.n_stocks})</span>`;
}

function rsRatingCell(rating) {
  if (rating === null || rating === undefined) return `<span class="muted">n/a</span>`;
  const cls = rating >= 80 ? "score-high" : rating >= 50 ? "score-mid" : "score-low";
  return `<span class="score-badge ${cls}">${rating}</span>`;
}

function rsCell(rs) {
  if (!rs.available) return `<span class="rs-na">n/a</span>`;
  const good = rs.rs_above_ema && rs.rs_rising_1w;
  const bad = !rs.rs_above_ema && !rs.rs_rising_1w;
  const cls = good ? "rs-good" : bad ? "rs-bad" : "rs-na";
  const label = good ? "Leading" : bad ? "Lagging" : "Mixed";
  return `<span class="rs-tag ${cls}">${label}</span>`;
}

function rowName(row) {
  return CURRENT_VIEW === "sectors" ? row.sector : row.industry;
}

// --- Sorting ---------------------------------------------------------

function sortValue(row, key) {
  const e = row.ema, b = row.breadth, rs = row.rs;
  switch (key) {
    case "name":
      return rowName(row).toLowerCase();
    case "score":
      return row.score;
    case "ema": {
      if (!e.available) return -1;
      const count = [e.above_21, e.above_50, e.above_200].filter(Boolean).length;
      return count + (e.bullish_stack ? 0.5 : 0);
    }
    case "breadth":
      return b.available ? b.pct_above_10ma : -1;
    case "breadthTrend":
      if (!b.available || b.pct_above_10ma_week_ago === null) return -999;
      return b.pct_above_10ma - b.pct_above_10ma_week_ago;
    case "breadth21":
      return (b.available && b.pct_above_21ma !== null && b.pct_above_21ma !== undefined) ? b.pct_above_21ma : -1;
    case "breadth21Trend":
      if (!b.available || b.pct_above_21ma_week_ago === null || b.pct_above_21ma_week_ago === undefined) return -999;
      return b.pct_above_21ma - b.pct_above_21ma_week_ago;
    case "high52":
      return (row.high52 && row.high52.available) ? row.high52.pct_within_52wk_high : -1;
    case "rsRating":
      return (row.rs_rating !== null && row.rs_rating !== undefined) ? row.rs_rating : -1;
    case "rs": {
      if (!rs.available) return -1;
      if (rs.rs_above_ema && rs.rs_rising_1w) return 2;
      if (!rs.rs_above_ema && !rs.rs_rising_1w) return 0;
      return 1;
    }
    default:
      return 0;
  }
}

function filteredData() {
  if (!SEARCH_TERM) return CURRENT_DATA.slice();
  const q = SEARCH_TERM.toLowerCase();
  return CURRENT_DATA.filter(row => rowName(row).toLowerCase().includes(q));
}

function sortedData() {
  const arr = filteredData();
  arr.sort((a, b) => {
    const va = sortValue(a, SORT_KEY);
    const vb = sortValue(b, SORT_KEY);
    let cmp;
    if (typeof va === "string") cmp = va.localeCompare(vb);
    else cmp = va - vb;
    return SORT_DIR === "asc" ? cmp : -cmp;
  });
  return arr;
}

function updateSortHeaderStyles() {
  document.querySelectorAll("th.sortable").forEach(th => {
    const key = th.dataset.sort;
    th.classList.toggle("sort-active", key === SORT_KEY);
    const existingArrow = th.querySelector(".sort-arrow");
    if (existingArrow) existingArrow.remove();
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
    if (key === SORT_KEY) {
      SORT_DIR = SORT_DIR === "asc" ? "desc" : "asc";
    } else {
      SORT_KEY = key;
      SORT_DIR = "desc";
    }
    updateSortHeaderStyles();
    renderBoard(sortedData());
  });
});

// --- Rendering ---------------------------------------------------------

function changedTodayBadge(row) {
  const delta = row.score_delta;
  if (!delta || !delta.available) return "";
  const badges = [];
  if (delta.bullish_stack_changed === true) {
    const nowBullish = row.ema && row.ema.bullish_stack;
    badges.push(nowBullish
      ? `<span class="change-badge change-good">stack turned bullish</span>`
      : `<span class="change-badge change-bad">stack turned bearish</span>`);
  }
  // Only flag overheating turning ON -- turning off is "back to normal",
  // not something that needs your attention the way a fresh crowding
  // signal does.
  if (delta.overheated_changed === true && row.breadth && row.breadth.overheated) {
    badges.push(`<span class="change-badge change-warn">overheated</span>`);
  }
  return badges.join("");
}

function renderBoard(data) {
  const tbody = document.getElementById("board-body");
  tbody.innerHTML = "";
  document.getElementById("name-col-header").textContent =
    CURRENT_VIEW === "sectors" ? "Sector" : "Basic Industry";

  if (!data.length && SEARCH_TERM) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="11" class="no-results">No matches for "${SEARCH_TERM}"</td>`;
    tbody.appendChild(tr);
    return;
  }

  data.forEach((row, i) => {
    const breadth = breadthCell(row.breadth);
    const breadth21 = breadth21Cell(row.breadth);
    const tr = document.createElement("tr");
    const nameLabel = rowName(row);
    tr.innerHTML = `
      <td class="rank-col" data-label="#">${i + 1}</td>
      <td class="sector-col" data-label="Name">${nameLabel}${changedTodayBadge(row)}</td>
      <td data-label="Score"><span class="score-badge ${scoreClass(row.score)}">${row.score}</span>${scoreDeltaHtml(row.score_delta)}</td>
      <td data-label="EMA Stack">${stackLadder(row.ema)}</td>
      <td data-label="Breadth">${breadth.val}</td>
      <td data-label="Trend">${breadth.trend}</td>
      <td data-label="Breadth 21">${breadth21.val}</td>
      <td data-label="Trend 21">${breadth21.trend}</td>
      <td data-label="% Near 52wk High">${high52Cell(row.high52)}${metricDeltaHtml(row.high52_delta)}</td>
      <td data-label="RS Rating">${rsRatingCell(row.rs_rating)}${metricDeltaHtml(row.rs_rating_delta)}</td>
      <td data-label="RS vs Nifty">${rsCell(row.rs)}</td>
    `;
    tr.addEventListener("click", () => openDetail(row));
    tbody.appendChild(tr);
  });
}

function drawSparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!values || values.length < 2) {
    ctx.fillStyle = "#7c8797";
    ctx.font = "12px monospace";
    ctx.fillText("Not enough history yet", 12, h / 2);
    return;
  }
  const min = Math.min(...values), max = Math.max(...values);
  const pad = 10;
  const range = (max - min) || 1;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  const rising = values[values.length - 1] >= values[0];
  ctx.strokeStyle = rising ? "#3fb950" : "#f85149";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function stockChip(stock) {
  if (!stock.has_data) {
    return `<div class="stock-chip stock-nodata" title="${stock.name} — no NSE price data available">${stock.symbol}</div>`;
  }
  let cls, arrow, statusNote;
  if (stock.above_10ma) {
    cls = "stock-above"; arrow = "▲"; statusNote = "above 10MA and 21MA";
  } else if (stock.above_21ma) {
    cls = "stock-cooling"; arrow = "▼"; statusNote = "below 10MA, still above 21MA";
  } else {
    cls = "stock-below"; arrow = "▼"; statusNote = "below 10MA and 21MA";
  }
  return `<div class="stock-chip ${cls}" title="${stock.name} — ₹${stock.close} — ${statusNote}">${arrow} ${stock.symbol}</div>`;
}

function stockGridHtml(stocks) {
  if (!stocks || !stocks.length) return `<span class="muted">No stock list available</span>`;
  return stocks.map(stockChip).join("");
}

function detailItem(label, value) {
  return `<div class="detail-item"><div class="label">${label}</div><div class="value">${value}</div></div>`;
}

function openDetail(row) {
  const title = CURRENT_VIEW === "sectors"
    ? `${row.sector} — ${row.index_name}`
    : `${row.industry}${row.synthetic ? " (synthetic index)" : ""}`;
  document.getElementById("detail-title").textContent = title;
  const grid = document.getElementById("detail-grid");
  const e = row.ema, b = row.breadth, rs = row.rs;
  const items = [
    detailItem("Composite Score", row.score),
    detailItem("Score vs Last Session", row.score_delta && row.score_delta.available
      ? `${row.score_delta.delta > 0 ? "+" : ""}${row.score_delta.delta} (was ${row.score_delta.prev_score} on ${row.score_delta.prev_date})`
      : "n/a (first session)"),
    detailItem("Last Data Date", row.last_date || "—"),
    detailItem("Price vs 21 EMA", e.available ? `${e.pct_above_21}%` : "n/a"),
    detailItem("Bullish Stack", e.available ? (e.bullish_stack ? "Yes" : "No") : "n/a"),
    detailItem("Breadth (>10MA)", b.available ? `${b.pct_above_10ma}% of ${b.n_stocks}` : "n/a"),
    detailItem("Breadth 1wk ago", b.available && b.pct_above_10ma_week_ago !== null ? `${b.pct_above_10ma_week_ago}%` : "n/a"),
    detailItem("RS Ratio", rs.available ? rs.rs_ratio : "n/a"),
    detailItem("RS vs Nifty", rs.available ? (rs.rs_rising_1w ? "Rising" : "Falling") : "n/a"),
    detailItem("RS Rating (1-99)", (row.rs_rating !== null && row.rs_rating !== undefined)
      ? `${row.rs_rating}${row.rs_rating_delta && row.rs_rating_delta.available ? ` (was ${row.rs_rating_delta.prev_value} on ${row.rs_rating_delta.prev_date})` : ""}`
      : "n/a"),
    detailItem("% Near 52wk High (within 5%)", row.high52 && row.high52.available
      ? `${row.high52.pct_within_52wk_high}% of ${row.high52.n_stocks}${row.high52_delta && row.high52_delta.available ? ` (was ${row.high52_delta.prev_value}% on ${row.high52_delta.prev_date})` : ""}`
      : "n/a"),
  ];
  if (CURRENT_VIEW === "industries") {
    const withData = b.available ? b.n_stocks : 0;
    items.push(detailItem("NSE Stocks Used", `${withData} of ${row.n_stocks_total} classified`));
  }
  grid.innerHTML = items.join("");

  const canvas = document.getElementById("rs-chart");
  drawSparkline(canvas, rs.available ? rs.history : []);

  const scoreCanvas = document.getElementById("score-chart");
  drawSparkline(scoreCanvas, row.score_history || []);

  const stocks = row.stocks || [];
  document.getElementById("stock-count").textContent = stocks.length;
  document.getElementById("stock-grid").innerHTML = stockGridHtml(stocks);

  document.getElementById("detail-panel").classList.remove("hidden");
}

document.getElementById("close-detail").addEventListener("click", () => {
  document.getElementById("detail-panel").classList.add("hidden");
});
document.getElementById("detail-panel").addEventListener("click", (e) => {
  if (e.target.id === "detail-panel") e.target.classList.add("hidden");
});

function showData(data) {
  CURRENT_DATA = data;
  if (!data.length) {
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("board").classList.add("hidden");
    document.getElementById("asof").textContent = "no data";
    return;
  }
  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("board").classList.remove("hidden");
  updateSortHeaderStyles();
  renderBoard(sortedData());
  const dates = data.map(r => r.last_date).filter(Boolean);
  document.getElementById("asof").textContent = dates.length ? `as of ${dates.sort().pop()}` : "";
}

async function loadView(view) {
  CURRENT_VIEW = view;
  SEARCH_TERM = "";
  document.getElementById("search-box").value = "";
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === view));

  const cacheKey = view === "sectors" ? "sectors" : "industries";
  if (CACHE[cacheKey]) {
    applyView(view, CACHE[cacheKey]);
    return;
  }
  const url = view === "sectors" ? SECTORS_URL : INDUSTRIES_URL;
  try {
    const res = await fetch(url);
    const raw = await res.json();
    CACHE[cacheKey] = raw;
    applyView(view, raw);
  } catch (err) {
    document.getElementById("asof").textContent = `couldn't load ${url}`;
    document.getElementById("info-icon").classList.add("hidden");
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("board").classList.add("hidden");
  }
}

function renderRegimeBanner(elId, label, regime) {
  const el = document.getElementById(elId);
  if (!regime || !regime.available) {
    el.classList.add("hidden");
    return;
  }
  const cls = regime.state === "Bullish" ? "regime-bullish"
    : regime.state === "Bearish" ? "regime-bearish"
    : "regime-mixed";
  el.className = `regime-banner ${cls}`;
  const changedNote = regime.changed ? ` <span class="regime-changed">(changed today, was ${regime.prev_state})</span>` : "";
  el.innerHTML = `
    <div class="regime-title">${label}: ${regime.state}${changedNote}</div>
    <div class="regime-subtitle">${regime.subtitle}</div>
  `;
  el.classList.remove("hidden");
}

function applyView(view, raw) {
  const infoIcon = document.getElementById("info-icon");
  if (view === "sectors") {
    infoIcon.classList.add("hidden");
    renderRegimeBanner("regime-banner-nifty", "Nifty 50", raw.regime);
    renderRegimeBanner("regime-banner-midsmall", "Mid/Smallcap 400", raw.regime_midsmall);
    const sectors = raw.sectors || [];
    document.getElementById("sectors-tab").textContent = `Sectors (${sectors.length})`;
    showData(sectors);
    return;
  }
  // industries view: raw is { classification_source, industries } -- no
  // regime banners here, the sectors tab already showed them and the
  // regimes don't change between tabs.
  document.getElementById("regime-banner-nifty").classList.add("hidden");
  document.getElementById("regime-banner-midsmall").classList.add("hidden");
  infoIcon.classList.remove("hidden");
  showData(raw.industries || []);
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => loadView(tab.dataset.view));
});

document.getElementById("search-box").addEventListener("input", (e) => {
  SEARCH_TERM = e.target.value.trim();
  renderBoard(sortedData());
});

loadView("sectors");
