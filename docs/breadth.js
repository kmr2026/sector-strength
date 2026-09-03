const BREADTH_URL = "data/market_breadth.json";
const SCANNER_URL = "data/stock_scanner.json";

function pctCell(v) {
  return (v === null || v === undefined) ? `<span class="muted">n/a</span>` : `${v}%`;
}

function netCell(v) {
  const cls = v > 0 ? "trend-up" : v < 0 ? "trend-down" : "";
  const sign = v > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${v}</span>`;
}

function renderTables(rows) {
  document.getElementById("mb-ema-body").innerHTML = rows.map(r => `
    <tr>
      <td>${r.date}</td>
      <td>${pctCell(r.pct_above_10ema)}</td>
      <td>${pctCell(r.pct_above_21ema)}</td>
      <td>${pctCell(r.pct_above_50ema)}</td>
      <td>${pctCell(r.pct_above_200ema)}</td>
    </tr>
  `).join("");

  document.getElementById("mb-4pct-body").innerHTML = rows.map(r => `
    <tr>
      <td>${r.date}</td>
      <td class="trend-up">${pctCell(r.pct_4up)}</td>
      <td class="trend-down">${pctCell(r.pct_4down)}</td>
    </tr>
  `).join("");

  document.getElementById("mb-highslows-body").innerHTML = rows.map(r => `
    <tr>
      <td>${r.date}</td>
      <td class="trend-up">${r.new_highs}</td>
      <td class="trend-down">${r.new_lows}</td>
      <td>${netCell(r.net_new_highs)}</td>
    </tr>
  `).join("");
}

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

    document.getElementById("mb-layout").classList.remove("hidden");
    document.getElementById("mb-universe-count").textContent = `(${stocks.length} stocks)`;
    renderTables(rows);
    document.getElementById("asof").textContent = `as of ${rows[0].date}`;
  } catch (err) {
    document.getElementById("asof").textContent = "couldn't load data";
    document.getElementById("empty-state").classList.remove("hidden");
  }
}

load();
