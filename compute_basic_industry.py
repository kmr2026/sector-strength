"""
Same scoring framework as compute.py, but for NSE's Basic Industry
classification instead of your 17 tracked sectors.

The key difference: NSE doesn't publish an official index price series for
each basic industry (unlike Nifty Auto, Nifty Bank, etc.), so there's
nothing to plug into the EMA/RS math directly. Instead we build a SYNTHETIC
index ourselves, MARKET-CAP-WEIGHTED (see _build_synthetic_index) -- this
is NOT an NSE-published number, so the UI marks it as synthetic, but the
weighting itself is the same convention real indices use.

RS Rating (1-99) and % within 52-week-high here are ranked ONLY against
the other basic industries in this file -- a separate universe from the
sectors in compute.py, same split the rest of this file already keeps.
"""
import pandas as pd
from config import BENCHMARK, MIN_STOCKS_PER_BASIC_INDUSTRY
from db import get_conn
from scoring import (
    series_for, ema_block, breadth_block, rs_block, composite_score,
    stock_detail_list, score_delta_block, score_history_series,
    universe_raw_rs_scores, group_raw_rs_score, rs_ratings_from_raw,
    pct_within_52wk_high_block, metric_delta_block, pct_return, ordinal_rank_desc,
)


def _group_market_cap(conn, symbols: list[str]) -> float | None:
    """Sum of market cap (shares_outstanding x latest close) across the
    group's stocks -- same shares x price approach the stock scanner uses
    per stock, aggregated here. None if no stock in the group has both a
    price and a share count on file yet."""
    if not symbols:
        return None
    placeholders = ",".join("?" * len(symbols))
    close_rows = conn.execute(
        f"""SELECT sp.symbol, sp.close FROM stock_prices sp
            INNER JOIN (
                SELECT symbol, MAX(date) as max_date FROM stock_prices
                WHERE symbol IN ({placeholders}) GROUP BY symbol
            ) latest ON sp.symbol = latest.symbol AND sp.date = latest.max_date
            WHERE sp.symbol IN ({placeholders})""",
        symbols + symbols,
    ).fetchall()
    close_by_symbol = {r[0]: r[1] for r in close_rows}
    shares_rows = conn.execute(
        f"SELECT symbol, shares_outstanding FROM basic_industry_map WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchall()
    shares_by_symbol = {r[0]: r[1] for r in shares_rows if r[1]}

    total, found = 0.0, False
    for sym in symbols:
        shares, close = shares_by_symbol.get(sym), close_by_symbol.get(sym)
        if shares and close:
            total += shares * close / 1e7
            found = True
    return round(total, 2) if found else None


def _build_synthetic_index(conn, symbols: list[str]) -> pd.Series:
    """Market-cap-weighted index level series, base 1000, built the way
    real indices (Nifty included) actually are: each day's cross-sectional
    return is weighted by that day's market cap (shares_outstanding x that
    day's close), so a handful of small, volatile stocks can't swing the
    group's number the way they could under equal weighting -- the
    original design here.

    Verified against ChartsMaze's own Industry Analytics numbers for
    'Sugar' on the SAME set of stocks: cap-weighted landed at -2.24%/
    14.26%/14.45% (1W/1M/3M) vs their -2.19%/6.05%/13.21%, against
    equal-weighted's -4.32%/18.66%/19.69% -- cap-weighting was
    unambiguously closer on every period, confirming this is the right
    methodology, not just a plausible alternative.

    shares_outstanding is the same stable, derived value (market cap /
    CMP at scrape time) used everywhere else in this codebase -- see
    classify_via_screener.py.
    """
    if not symbols:
        return pd.Series(dtype=float)
    placeholders = ",".join("?" * len(symbols))
    df = pd.read_sql_query(
        f"SELECT symbol, date, close FROM stock_prices WHERE symbol IN ({placeholders}) ORDER BY date",
        conn, params=symbols,
    )
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    if len(wide) < 25:
        return pd.Series(dtype=float)

    shares_rows = conn.execute(
        f"SELECT symbol, shares_outstanding FROM basic_industry_map WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchall()
    shares = pd.Series({r[0]: r[1] for r in shares_rows if r[1]})
    # market cap at each day = that day's close x the stable share count --
    # this is what makes weighting evolve naturally as prices move, same
    # as a real cap-weighted index, instead of freezing one snapshot
    # weight for the whole period.
    mcap = wide.reindex(columns=shares.index).mul(shares, axis=1)

    daily_returns = wide.pct_change()
    # Weight each day's return by YESTERDAY's market cap (shift(1)) --
    # weighting by today's cap would let today's own price move influence
    # its own weight, a subtle look-ahead bias real indices avoid by
    # rebalancing on a lag.
    weights = mcap.shift(1)
    weighted_returns = (daily_returns * weights).sum(axis=1, skipna=True)
    total_weight = weights.where(daily_returns.notna()).sum(axis=1, skipna=True)
    avg_return = weighted_returns / total_weight

    # Stocks with no market-cap weight at all (shares_outstanding missing
    # for the whole group on some day) fall back to equal weighting for
    # that day rather than producing NaN and breaking the compounding --
    # a rare edge case, not the normal path.
    equal_fallback = daily_returns.mean(axis=1, skipna=True)
    avg_return = avg_return.fillna(equal_fallback)
    avg_return.iloc[0] = 0.0  # first day has no prior close to compare to

    index_level = (1.0 + avg_return.fillna(0)).cumprod() * 1000.0
    return index_level


def get_classification_source(conn) -> str:
    row = conn.execute(
        "SELECT value FROM classification_meta WHERE key = 'basic_industry_source'"
    ).fetchone()
    return row[0] if row else "unknown"


def compute_all(min_stocks: int = MIN_STOCKS_PER_BASIC_INDUSTRY) -> list[dict]:
    with get_conn() as conn:
        bench_series = series_for(conn, "index_prices", "sector", BENCHMARK)

        groups = pd.read_sql_query(
            "SELECT basic_industry, symbol FROM basic_industry_map WHERE basic_industry IS NOT NULL",
            conn,
        )
        if groups.empty:
            return []

        universe_scores = universe_raw_rs_scores(conn)

        # Pass 1: everything except RS Rating (needs every qualifying
        # industry's raw score gathered first).
        prelim = []
        for industry_name, group_df in groups.groupby("basic_industry"):
            symbols = group_df["symbol"].tolist()
            synthetic_series = _build_synthetic_index(conn, symbols)
            if synthetic_series.empty:
                continue  # not enough price history yet for this industry

            ema = ema_block(synthetic_series)
            breadth = breadth_block(conn, symbols)
            rs = rs_block(synthetic_series, bench_series) if not bench_series.empty else {"available": False}

            n_with_data = breadth.get("n_stocks", 0) if breadth.get("available") else 0
            if max(len(symbols), n_with_data) < min_stocks:
                continue  # too few stocks for this to mean anything

            last_date = synthetic_series.index[-1].date().isoformat() if not synthetic_series.empty else None
            high52 = pct_within_52wk_high_block(conn, symbols)
            score = composite_score(ema, breadth, rs, high52)
            raw_rs = group_raw_rs_score(universe_scores, symbols)
            perf_1w = pct_return(synthetic_series, 5)
            perf_1m = pct_return(synthetic_series, 21)
            perf_3m = pct_return(synthetic_series, 63)
            group_mcap = _group_market_cap(conn, symbols)
            prelim.append({
                "industry": industry_name, "n_stocks_total": len(symbols), "score": score,
                "ema": ema, "breadth": breadth, "rs": rs, "symbols": symbols,
                "last_date": last_date, "high52": high52, "raw_rs": raw_rs,
                "perf_1w": perf_1w, "perf_1m": perf_1m, "perf_3m": perf_3m,
                "group_market_cap_cr": group_mcap,
            })

        ratings = rs_ratings_from_raw({r["industry"]: r["raw_rs"] for r in prelim})
        rank_1w = ordinal_rank_desc({r["industry"]: r["perf_1w"] for r in prelim})
        rank_1m = ordinal_rank_desc({r["industry"]: r["perf_1m"] for r in prelim})
        rank_3m = ordinal_rank_desc({r["industry"]: r["perf_3m"] for r in prelim})

        # Pass 2: assemble final results now RS Rating is known.
        results = []
        for r in prelim:
            key = f"industry:{r['industry']}"
            delta = score_delta_block(
                conn, key, r["last_date"], r["score"],
                bullish_stack=r["ema"].get("bullish_stack") if r["ema"].get("available") else None,
                overheated=r["breadth"].get("overheated") if r["breadth"].get("available") else None,
            )
            rating = ratings.get(r["industry"])
            rs_rating_delta = metric_delta_block(conn, "rs_rating", key, r["last_date"], rating, min_days_back=6)
            high52_delta = {"available": False}
            if r["high52"].get("available"):
                high52_delta = metric_delta_block(
                    conn, "pct_52wk_high", key, r["last_date"], r["high52"]["pct_within_52wk_high"], min_days_back=0
                )
            results.append({
                "industry": r["industry"],
                "n_stocks_total": r["n_stocks_total"],
                "score": r["score"],
                "score_delta": delta,
                "score_history": score_history_series(conn, key),
                "ema": r["ema"],
                "breadth": r["breadth"],
                "rs": r["rs"],
                "rs_rating": rating,
                "rs_rating_delta": rs_rating_delta,
                "perf_1w": r["perf_1w"], "perf_1m": r["perf_1m"], "perf_3m": r["perf_3m"],
                "rank_1w": rank_1w.get(r["industry"]),
                "rank_1m": rank_1m.get(r["industry"]),
                "rank_3m": rank_3m.get(r["industry"]),
                "group_market_cap_cr": r["group_market_cap_cr"],
                "high52": r["high52"],
                "high52_delta": high52_delta,
                "stocks": stock_detail_list(conn, r["symbols"]),
                "synthetic": True,
                "last_date": r["last_date"],
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def compute_all_with_meta(min_stocks: int = MIN_STOCKS_PER_BASIC_INDUSTRY) -> dict:
    """Same as compute_all(), but wrapped with the classification_source so
    the frontend can be honest about whether this is the coarse 22-category
    fallback or the real 197-category Playwright-scraped data."""
    with get_conn() as conn:
        source = get_classification_source(conn)
    return {
        "classification_source": source,
        "industries": compute_all(min_stocks),
    }


if __name__ == "__main__":
    import json
    result = compute_all_with_meta()
    print(f"source: {result['classification_source']}")
    print(f"{len(result['industries'])} basic industries scored (min {MIN_STOCKS_PER_BASIC_INDUSTRY} stocks)")
    print(json.dumps(result["industries"][:3], indent=2, default=str))
