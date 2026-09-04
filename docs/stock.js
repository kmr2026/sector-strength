const SCANNER_URL = "data/stock_scanner.json";

function stackLadder(ema) {
  if (!ema || !ema.available) return `<span class="muted">n/a</span>`;
  const bars = [
    ["21", ema.above_21],
    ["50", ema.above_50],
    ["200", ema.above_200],
  ];
  return bars.map(([label, on]) => {
    if (on === null || on === undefined) return `<div class="stack-bar" title="${label} EMA: no data"></div>`;
    return `<div class="stack-bar ${on ? "on" : "off"}" title="${label} EMA: ${on ? "above" : "below"}"></div>`;
  }).join("");
}

function ratingClass(rating) {
  if (rating === null || rating === undefined) return "score-low";
  if (rating >= 80) return "score-high";
  if (rating >= 50) return "score-mid";
  return "score-low";
}

function returnSpan(v, label) {
  if (v === null || v === undefined) return `<span>${label} <span class="muted">n/a</span></span>`;
  const cls = v > 0 ? "trend-up" : v < 0 ? "trend-down" : "";
  return `<span>${label} <b class="${cls}">${v > 0 ? "+" : ""}${v.toFixed(2)}%</b></span>`;
}

function rankSpan(v, label) {
  if (v === null || v === undefined) return `<span>${label} <span class="muted">n/a</span></span>`;
  return `<span>${label} <b>#${v}</b></span>`;
}

function fmtPrice(v) {
  return (v === null || v === undefined) ? "n/a" : `₹${v.toLocaleString()}`;
}

function initTradingViewChart(symbol) {
  if (typeof TradingView === "undefined") return; // tv.js failed to load -- fail quietly, rest of the page still works
  new TradingView.widget({
    width: "100%",
    height: "100%",
    symbol: `NSE:${symbol}`,
    interval: "D",
    timezone: "Asia/Kolkata",
    theme: "dark",
    style: "1",
    locale: "en",
    toolbar_bg: "#0c0f13",
    enable_publishing: false,
    hide_top_toolbar: false,
    allow_symbol_change: false,
    // 10/21/50 EMA overlaid on price, plus volume as a subplot below --
    // matches the same EMA periods used everywhere else on this site.
    // If these don't render correctly, "MAExp@tv-basicstudies" is the
    // one piece of this config that's convention rather than something
    // independently verified against current TradingView docs.
    studies: [
      { id: "MAExp@tv-basicstudies", inputs: { length: 10 } },
      { id: "MAExp@tv-basicstudies", inputs: { length: 21 } },
      { id: "MAExp@tv-basicstudies", inputs: { length: 50 } },
      "Volume@tv-basicstudies",
    ],
    container_id: "tv-chart-container",
  });
}

async function load() {
  const params = new URLSearchParams(window.location.search);
  const symbol = (params.get("symbol") || "").toUpperCase().trim();

  if (!symbol) {
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("empty-state").querySelector("p").textContent =
      "No stock specified -- open this page via a stock link, e.g. stock.html?symbol=SSWL";
    return;
  }

  // Called AFTER the rest of the fetch below, not here -- the container
  // sits inside #sd-content, which starts hidden (display:none) until
  // the page's own data finishes loading. Initializing the widget while
  // its container has zero size makes TradingView's own sizing detection
  // fail silently, so this has to wait until #sd-content is visible.

  let stocks;
  try {
    const res = await fetch(SCANNER_URL);
    stocks = await res.json();
  } catch (err) {
    document.getElementById("empty-state").classList.remove("hidden");
    document.getElementById("empty-state").querySelector("p").textContent = "Couldn't load stock data.";
    return;
  }

  const s = stocks.find(x => x.symbol === symbol);
  if (!s) {
    document.getElementById("empty-state").classList.remove("hidden");
    return;
  }

  document.title = `${s.symbol} - Stock Detail`;
  document.getElementById("stock-header").innerHTML = `${s.symbol}<span>DETAIL</span>`;
  document.getElementById("sd-symbol").textContent = s.symbol;
  document.getElementById("sd-name").textContent = s.name || "";
  document.getElementById("sd-industry-link").textContent = s.basic_industry || "Unclassified";
  document.getElementById("sd-industry-link").href = s.basic_industry
    ? `index.html?industry=${encodeURIComponent(s.basic_industry)}`
    : `index.html`;

  document.getElementById("sd-price").textContent = fmtPrice(s.close);
  document.getElementById("sd-rs-rating").innerHTML = (s.rs_rating !== null && s.rs_rating !== undefined)
    ? `<span class="score-badge ${ratingClass(s.rs_rating)}" style="font-size:16px; padding:3px 10px;">${s.rs_rating}</span>`
    : `<span class="muted">n/a</span>`;
  document.getElementById("sd-mcap").textContent = (s.market_cap_cr !== null && s.market_cap_cr !== undefined)
    ? `₹${s.market_cap_cr.toLocaleString()} Cr` : "n/a";

  document.getElementById("sd-returns").innerHTML = [
    returnSpan(s.return_1d, "1D"),
    returnSpan(s.return_1w, "1W"),
    returnSpan(s.return_1m, "1M"),
    returnSpan(s.return_3m, "3M"),
  ].join("");

  document.getElementById("sd-52-high").innerHTML = (s.high_52wk !== null && s.high_52wk !== undefined)
    ? `${fmtPrice(s.high_52wk)} <span class="muted" style="font-size:12px;">(${s.pct_from_52wk_high}% away)</span>`
    : "n/a";
  document.getElementById("sd-52-low").innerHTML = (s.low_52wk !== null && s.low_52wk !== undefined)
    ? `${fmtPrice(s.low_52wk)} <span class="trend-up" style="font-size:12px;">(${s.pct_from_52wk_low}% up)</span>`
    : "n/a";

  document.getElementById("sd-ema-ladder").innerHTML = stackLadder(s.ema);
  document.getElementById("sd-ema-caption").textContent =
    (s.ema && s.ema.available) ? (s.ema.bullish_stack ? "Bullish stack" : "Above/below 21 / 50 / 200 EMA") : "Not enough history yet";

  const turnover = (s.avg_turnover_cr_30d !== null && s.avg_turnover_cr_30d !== undefined) ? `₹${s.avg_turnover_cr_30d} Cr` : "n/a";
  const adr = (s.adr_pct_20d !== null && s.adr_pct_20d !== undefined) ? `${s.adr_pct_20d}%` : "n/a";
  document.getElementById("sd-turnover-adr").innerHTML = `${turnover} <span class="muted" style="font-size:12px;">/ ${adr}</span>`;

  document.getElementById("sd-industry-rank-label").textContent = s.basic_industry || "Unclassified";
  document.getElementById("sd-industry-rank").innerHTML = [
    rankSpan(s.industry_rank_1w, "1W"),
    rankSpan(s.industry_rank_1m, "1M"),
    rankSpan(s.industry_rank_3m, "3M"),
  ].join("");

  document.getElementById("sd-content").classList.remove("hidden");
  initTradingViewChart(symbol);
  document.getElementById("asof").textContent = s.last_date ? `as of ${s.last_date}` : "";
}

load();
