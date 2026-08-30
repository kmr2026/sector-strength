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
  const val = `<span class="breadth-val">${breadth.pct_above_10ma}%</span> <span class="muted">(${breadth.n_stocks})</span>`;
  let trend = `<span class="trend-flat">flat</span>`;
  if (breadth.pct_above_10ma_week_ago !== null) {
    const diff = breadth.pct_above_10ma - breadth.pct_above_10ma_week_ago;
    if (diff > 1) trend = `<span class="trend-up">▲ ${diff.toFixed(1)}pt</span>`;
    else if (diff < -1) trend = `<span class="trend-down">▼ ${Math.abs(diff).toFixed(1)}pt</span>`;
  }
  return { val, trend };
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

function renderBoard(data) {
  const tbody = document.getElementById("board-body");
  tbody.innerHTML = "";
  document.getElementById("name-col-header").textContent =
    CURRENT_VIEW === "sectors" ? "Sector" : "Basic Industry";

  if (!data.length && SEARCH_TERM) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="7" class="no-results">No matches for "${SEARCH_TERM}"</td>`;
    tbody.appendChild(tr);
    return;
  }

  data.forEach((row, i) => {
    const breadth = breadthCell(row.breadth);
    const tr = document.createElement("tr");
    const nameLabel = rowName(row);
    tr.innerHTML = `
      <td class="rank-col" data-label="#">${i + 1}</td>
      <td class="sector-col" data-label="Name">${nameLabel}</td>
      <td data-label="Score"><span class="score-badge ${scoreClass(row.score)}">${row.score}</span></td>
      <td data-label="EMA Stack">${stackLadder(row.ema)}</td>
      <td data-label="Breadth">${breadth.val}</td>
      <td data-label="Trend">${breadth.trend}</td>
      <td data-label="RS">${rsCell(row.rs)}</td>
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
  const cls = stock.above_10ma ? "stock-above" : "stock-below";
  const arrow = stock.above_10ma ? "▲" : "▼";
  return `<div class="stock-chip ${cls}" title="${stock.name} — ₹${stock.close}">${arrow} ${stock.symbol}</div>`;
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
    detailItem("Last Data Date", row.last_date || "—"),
    detailItem("Price vs 21 EMA", e.available ? `${e.pct_above_21}%` : "n/a"),
    detailItem("Bullish Stack", e.available ? (e.bullish_stack ? "Yes" : "No") : "n/a"),
    detailItem("Breadth (>10MA)", b.available ? `${b.pct_above_10ma}% of ${b.n_stocks}` : "n/a"),
    detailItem("Breadth 1wk ago", b.available && b.pct_above_10ma_week_ago !== null ? `${b.pct_above_10ma_week_ago}%` : "n/a"),
    detailItem("RS Ratio", rs.available ? rs.rs_ratio : "n/a"),
    detailItem("RS vs Nifty", rs.available ? (rs.rs_rising_1w ? "Rising" : "Falling") : "n/a"),
  ];
  if (CURRENT_VIEW === "industries") {
    const withData = b.available ? b.n_stocks : 0;
    items.push(detailItem("NSE Stocks Used", `${withData} of ${row.n_stocks_total} classified`));
  }
  grid.innerHTML = items.join("");

  const canvas = document.getElementById("rs-chart");
  drawSparkline(canvas, rs.available ? rs.history : []);

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

function applyView(view, raw) {
  const infoIcon = document.getElementById("info-icon");
  if (view === "sectors") {
    infoIcon.classList.add("hidden");
    showData(raw);
    return;
  }
  // industries view: raw is { classification_source, industries }
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
