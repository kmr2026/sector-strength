const SCANNER_URL = "data/stock_scanner.json";

let ALL_STOCKS = [];
let SELECTED_INDUSTRY = null;
let CURRENT_INDUSTRIES = []; // last computed, sorted industry rows

const PERIOD_FIELD = { "1d": "return_1d", "1w": "return_1w", "1m": "return_1m" };

function num(id) {
  const v = document.getElementById(id).value.trim();
  return v === "" ? null : parseFloat(v);
}

function readFilters() {
  return {
    period: document.getElementById("f-period").value,
    mcapMin: num("f-mcap-min"),
    returnMin: num("f-return-min"),
    minCount: num("f-min-count"),
  };
}

function applyFilters() {
  const f = readFilters();
  const field = PERIOD_FIELD[f.period];

  // "Qualifying" = passes market cap + return thresholds for the chosen
  // period -- independent of the per-industry minimum-count filter,
  // which only decides which industries get a BAR on the left, not which
  // stocks show up in the flat "Overall Top Performers" list.
  const qualifying = ALL_STOCKS.filter(s => {
    const ret = s[field];
    if (ret === null || ret === undefined) return false;
    if (f.mcapMin !== null && !(s.market_cap_cr >= f.mcapMin)) return false;
    if (f.returnMin !== null && !(ret >= f.returnMin)) return false;
    return true;
  });

  // Total stock count per industry across the FULL universe (not just
  // qualifying stocks) -- this is the denominator for "X% of this
  // industry's stocks are gainers today."
  const totalByIndustry = new Map();
  ALL_STOCKS.forEach(s => {
    const key = s.basic_industry || "Unclassified";
    totalByIndustry.set(key, (totalByIndustry.get(key) || 0) + 1);
  });

  const groups = new Map(); // industry -> [stock,...]
  qualifying.forEach(s => {
    const key = s.basic_industry || "Unclassified";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  });

  let industries = [...groups.entries()]
    .filter(([, stocks]) => f.minCount === null || stocks.length >= f.minCount)
    .map(([name, stocks]) => {
      const barValue = Math.max(...stocks.map(s => s[field]));
      const total = totalByIndustry.get(name) || stocks.length;
      return {
        name,
        stocks: stocks.slice().sort((a, b) => b[field] - a[field]),
        barValue,
        pctOfTotal: Math.round((stocks.length / total) * 1000) / 10,
      };
    });
  industries.sort((a, b) => b.barValue - a.barValue);

  CURRENT_INDUSTRIES = industries;
  document.getElementById("tg-layout").classList.remove("hidden");
  document.getElementById("empty-state").classList.add("hidden");
  renderBars(industries);
  renderOverallTable(qualifying, field);

  if (!industries.length) {
    SELECTED_INDUSTRY = null;
    renderIndustryTable(null, field);
    return;
  }
  // Keep the current selection if it's still present after re-filtering,
  // otherwise default back to the top industry.
  const stillThere = industries.find(i => i.name === SELECTED_INDUSTRY);
  selectIndustry(stillThere ? stillThere.name : industries[0].name, field);
}

function fmtReturn(v) {
  return (v === null || v === undefined) ? "n/a" : `${v.toFixed(2)}`;
}

function renderBars(industries) {
  const el = document.getElementById("tg-bars");
  if (!industries.length) {
    el.innerHTML = `<p class="muted">No industries have ${document.getElementById("f-min-count").value}+ stocks meeting these filters -- try lowering "No. of stocks in Industry". Individual gainers may still be listed on the right.</p>`;
    return;
  }
  const maxVal = industries[0].barValue;
  el.innerHTML = industries.map(ind => {
    const widthPct = maxVal > 0 ? Math.max(8, (ind.barValue / maxVal) * 100) : 8;
    const selected = ind.name === SELECTED_INDUSTRY ? "selected" : "";
    return `
      <div class="tg-bar-row ${selected}" data-industry="${ind.name.replace(/"/g, "&quot;")}">
        <div class="tg-bar-track">
          <div class="tg-bar-fill" style="width:${widthPct}%">${ind.name}(${ind.pctOfTotal}%)</div>
        </div>
      </div>
    `;
  }).join("");
  el.querySelectorAll(".tg-bar-row").forEach(row => {
    row.addEventListener("click", () => {
      const f = readFilters();
      selectIndustry(row.dataset.industry, PERIOD_FIELD[f.period]);
    });
  });
}

function renderOverallTable(qualifying, field) {
  const sorted = qualifying.slice().sort((a, b) => b[field] - a[field]);
  const tbody = document.getElementById("tg-overall-body");
  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="2" class="muted">No stocks match these filters</td></tr>`;
    return;
  }
  tbody.innerHTML = sorted.map(s => `
    <tr>
      <td class="sector-col">${s.symbol}</td>
      <td>${fmtReturn(s[field])}</td>
    </tr>
  `).join("");
}

function selectIndustry(name, field) {
  SELECTED_INDUSTRY = name;
  document.getElementById("tg-selected-industry").textContent = name;
  document.querySelectorAll(".tg-bar-row").forEach(row => {
    row.classList.toggle("selected", row.dataset.industry === name);
  });
  const ind = CURRENT_INDUSTRIES.find(i => i.name === name);
  renderIndustryTable(ind, field);
}

function renderIndustryTable(ind, field) {
  const tbody = document.getElementById("tg-industry-body");
  if (!ind || !ind.stocks.length) {
    tbody.innerHTML = `<tr><td colspan="2" class="muted">No stocks to show</td></tr>`;
    return;
  }
  tbody.innerHTML = ind.stocks.map(s => `
    <tr>
      <td class="sector-col">${s.symbol}</td>
      <td>${fmtReturn(s[field])}</td>
    </tr>
  `).join("");
}

document.getElementById("f-apply").addEventListener("click", applyFilters);

async function load() {
  try {
    const res = await fetch(SCANNER_URL);
    ALL_STOCKS = await res.json();
    applyFilters();
    const dates = ALL_STOCKS.map(s => s.last_date).filter(Boolean);
    document.getElementById("asof").textContent = dates.length ? `as of ${dates.sort().pop()}` : "";
  } catch (err) {
    document.getElementById("asof").textContent = "couldn't load data";
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("tg-layout").classList.add("hidden");
  }
}

load();
