const BREADTH_URL = "data/market_breadth.json";
const SCANNER_URL = "data/stock_scanner.json";

let ROWS = [];
const SORT = {
  ema: { key: "date", dir: "desc" },
  pct4: { key: "date", dir: "desc" },
  highslow: { key: "date", dir: "desc" },
};

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  const day = d.getDate();
  const month = d.toLocaleString("en-US", { month: "short" });
  const year = String(d.getFullYear()).slice(-2);
  const suffix = (day % 10 === 1 && day !== 11) ? "st"
    : (day % 10 === 2 && day !== 12) ? "nd"
    : (day % 10 === 3 && day !== 13) ? "rd"
    : "th";
  return `${day}${suffix} ${month}'${year}`;
}

function numCell(v) {
  return (v === null || v === undefined) ? `<span class="muted">n/a</span>` : `${v}`;
}

function emaCell(v, colClass) {
  if (v === null || v === undefined) return `<span class="muted">n/a</span>`;
  return `<span class="mb-cell ${colClass}">${v}</span>`;
}

function netCell(v) {
  const cls = v > 0 ? "trend-up" : v < 0 ? "trend-down" : "";
  const sign = v > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${v}</span>`;
}

function sortedRows(tableKey) {
  const { key, dir } = SORT[tableKey];
  const arr = ROWS.slice();
  arr.sort((a, b) => {
    let va = a[key], vb = b[key];
    if (key === "date") { va = a.date; vb = b.date; } // ISO strings sort correctly as-is
    else { va = va ?? -Infinity; vb = vb ?? -Infinity; }
    const cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return dir === "asc" ? cmp : -cmp;
  });
  return arr;
}

function updateSortHeaders(tableKey) {
  document.querySelectorAll(`th.sortable[data-table="${tableKey}"]`).forEach(th => {
    const key = th.dataset.sort;
    const active = key === SORT[tableKey].key;
    th.classList.toggle("sort-active", active);
    const existing = th.querySelector(".sort-arrow");
    if (existing) existing.remove();
    if (active) {
      const arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      arrow.textContent = SORT[tableKey].dir === "asc" ? "▲" : "▼";
      th.appendChild(arrow);
    }
  });
}

function renderTables() {
  const emaRows = sortedRows("ema");
  document.getElementById("mb-ema-body").innerHTML = emaRows.map(r => `
    <tr>
      <td>${formatDate(r.date)}</td>
      <td>${emaCell(r.pct_above_10ema, "mb-col-10ema")}</td>
      <td>${emaCell(r.pct_above_21ema, "mb-col-21ema")}</td>
      <td>${emaCell(r.pct_above_50ema, "mb-col-50ema")}</td>
      <td>${emaCell(r.pct_above_200ema, "mb-col-200ema")}</td>
    </tr>
  `).join("");

  const pct4Rows = sortedRows("pct4");
  document.getElementById("mb-4pct-body").innerHTML = pct4Rows.map(r => `
    <tr>
      <td>${formatDate(r.date)}</td>
      <td class="trend-up">${numCell(r.pct_4up)}</td>
      <td class="trend-down">${numCell(r.pct_4down)}</td>
    </tr>
  `).join("");

  const hlRows = sortedRows("highslow");
  document.getElementById("mb-highslows-body").innerHTML = hlRows.map(r => `
    <tr>
      <td>${formatDate(r.date)}</td>
      <td class="trend-up">${r.new_highs}</td>
      <td class="trend-down">${r.new_lows}</td>
      <td>${netCell(r.net_new_highs)}</td>
    </tr>
  `).join("");
}

document.querySelectorAll("th.sortable").forEach(th => {
  th.addEventListener("click", () => {
    const tableKey = th.dataset.table;
    const key = th.dataset.sort;
    if (SORT[tableKey].key === key) {
      SORT[tableKey].dir = SORT[tableKey].dir === "asc" ? "desc" : "asc";
    } else {
      SORT[tableKey].key = key;
      SORT[tableKey].dir = key === "date" ? "desc" : "desc";
    }
    updateSortHeaders(tableKey);
    renderTables();
  });
});

async function load() {
  try {
    const [breadthRes, scannerRes] = await Promise.all([
      fetch(BREADTH_URL),
      fetch(SCANNER_URL),
    ]);
    const rows = await breadthRes.json();
    const stocks = await scannerRes.json();

    if (!rows.length) {
      document.getElementById("empty-state").classList.remove("hidden");
      return;
    }

    ROWS = rows;
    document.getElementById("mb-layout").classList.remove("hidden");
    document.getElementById("mb-universe-count").textContent = `(${stocks.length} stocks)`;
    ["ema", "pct4", "highslow"].forEach(updateSortHeaders);
    renderTables();
    document.getElementById("asof").textContent = `as of ${formatDate(rows[0].date)}`;
  } catch (err) {
    document.getElementById("asof").textContent = "couldn't load data";
    document.getElementById("empty-state").classList.remove("hidden");
  }
}

load();
