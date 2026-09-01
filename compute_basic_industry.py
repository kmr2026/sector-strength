"""
Same scoring framework as compute.py, but for NSE's Basic Industry
classification instead of your 17 tracked sectors.

The key difference: NSE doesn't publish an official index price series for
each basic industry (unlike Nifty Auto, Nifty Bank, etc.), so there's
nothing to plug into the EMA/RS math directly. Instead we build a SYNTHETIC
index ourselves: an equal-weighted daily return average across that basic
industry's stocks, compounded into an index level. This is a legitimate,
standard technique (it's literally how many real equal-weight indices are
built) -- it's just NOT an NSE-published number, so the UI marks it as
synthetic.

Equal weighting (not market-cap weighting) is used because we don't have
free per-stock market-cap data -- every stock in the basic industry counts
the same in the synthetic index, same as breadth already does.

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
    pct_within_52wk_high_block, metric_delta_block,
)


def _build_synthetic_index(conn, symbols: list[str]) -> pd.Series:
    """Equal-weighted index level series, base 1000, from daily stock returns."""
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

    daily_returns = wide.pct_change()
    # average return across whichever stocks have a valid price both days
    avg_return = daily_returns.mean(axis=1, skipna=True)
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
            score = composite_score(ema, breadth, rs)

            n_with_data = breadth.get("n_stocks", 0) if breadth.get("available") else 0
            if max(len(symbols), n_with_data) < min_stocks:
                continue  # too few stocks for this to mean anything

            last_date = synthetic_series.index[-1].date().isoformat() if not synthetic_series.empty else None
            high52 = pct_within_52wk_high_block(conn, symbols)
            raw_rs = group_raw_rs_score(universe_scores, symbols)
            prelim.append({
                "industry": industry_name, "n_stocks_total": len(symbols), "score": score,
                "ema": ema, "breadth": breadth, "rs": rs, "symbols": symbols,
                "last_date": last_date, "high52": high52, "raw_rs": raw_rs,
            })

        ratings = rs_ratings_from_raw({r["industry"]: r["raw_rs"] for r in prelim})

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
