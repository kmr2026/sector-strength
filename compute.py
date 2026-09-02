"""
Scores your 17 tracked sectors using their real, official NSE index prices.
Breadth is measured ONLY over each sector's official narrow index
constituents (the actual stocks that are members of that index) -- not
widened to the broader Total Market universe. That broader view now lives
in the "All Industries" tab (compute_basic_industry.py), which is the
right place for it; this tab stays true to "what's actually in the index."

RS Rating (1-99) and % within 52-week-high are ranked ONLY against the
other sectors in this file, as their own universe -- separate from the
basic-industry universe in compute_basic_industry.py, same split the rest
of this file already keeps.

See scoring.py for the actual EMA/breadth/RS/score/RS-Rating math (shared
with compute_basic_industry.py).
"""
from config import SECTORS, BENCHMARK, MIDSMALL_INDEX, SMALLCAP_INDEX
from db import get_conn
from scoring import (
    series_for, ema_block, breadth_block, rs_block, regime_block, composite_score,
    stock_detail_list, score_delta_block, regime_delta_block, score_history_series,
    universe_raw_rs_scores, group_raw_rs_score, rs_ratings_from_raw,
    pct_within_52wk_high_block, metric_delta_block,
)


def compute_all() -> dict:
    with get_conn() as conn:
        bench_series = series_for(conn, "index_prices", "sector", BENCHMARK)
        regime = regime_block(bench_series) if not bench_series.empty else {"available": False}
        midsmall_series = series_for(conn, "index_prices", "sector", MIDSMALL_INDEX)
        regime_midsmall = regime_block(midsmall_series) if not midsmall_series.empty else {"available": False}
        smallcap_series = series_for(conn, "index_prices", "sector", SMALLCAP_INDEX)
        regime_smallcap = regime_block(smallcap_series) if not smallcap_series.empty else {"available": False}

        nifty_last_date = bench_series.index[-1].date().isoformat() if not bench_series.empty else None
        regime.update(regime_delta_block(conn, f"regime:{BENCHMARK}", nifty_last_date, regime.get("state")))
        midsmall_last_date = midsmall_series.index[-1].date().isoformat() if not midsmall_series.empty else None
        regime_midsmall.update(regime_delta_block(conn, f"regime:{MIDSMALL_INDEX}", midsmall_last_date, regime_midsmall.get("state")))
        smallcap_last_date = smallcap_series.index[-1].date().isoformat() if not smallcap_series.empty else None
        regime_smallcap.update(regime_delta_block(conn, f"regime:{SMALLCAP_INDEX}", smallcap_last_date, regime_smallcap.get("state")))

        # Computed once per run, shared by every sector below -- this is
        # the expensive step RS Rating adds (full-universe price scan).
        universe_scores = universe_raw_rs_scores(conn)

        # Pass 1: everything except RS Rating -- RS Rating needs every
        # sector's raw score gathered first so they can all be
        # percentile-ranked against each other in one shot.
        prelim = []
        for sector_name, (index_name, _) in SECTORS.items():
            sector_series = series_for(conn, "index_prices", "sector", index_name)
            symbols = [
                row[0] for row in conn.execute(
                    "SELECT symbol FROM sector_constituents WHERE sector = ?", (sector_name,)
                ).fetchall()
            ]
            ema = ema_block(sector_series)
            breadth = breadth_block(conn, symbols)
            rs = rs_block(sector_series, bench_series) if not bench_series.empty else {"available": False}
            score = composite_score(ema, breadth, rs)
            last_date = sector_series.index[-1].date().isoformat() if not sector_series.empty else None
            high52 = pct_within_52wk_high_block(conn, symbols)
            raw_rs = group_raw_rs_score(universe_scores, symbols)
            prelim.append({
                "sector": sector_name, "index_name": index_name, "score": score,
                "ema": ema, "breadth": breadth, "rs": rs, "symbols": symbols,
                "last_date": last_date, "high52": high52, "raw_rs": raw_rs,
            })

        ratings = rs_ratings_from_raw({r["sector"]: r["raw_rs"] for r in prelim})

        # Pass 2: RS Rating is known now -- finalize deltas and assemble
        # each sector's full result.
        results = []
        for r in prelim:
            key = f"sector:{r['sector']}"
            delta = score_delta_block(
                conn, key, r["last_date"], r["score"],
                bullish_stack=r["ema"].get("bullish_stack") if r["ema"].get("available") else None,
                overheated=r["breadth"].get("overheated") if r["breadth"].get("available") else None,
            )
            rating = ratings.get(r["sector"])
            rs_rating_delta = metric_delta_block(conn, "rs_rating", key, r["last_date"], rating, min_days_back=6)
            high52_delta = {"available": False}
            if r["high52"].get("available"):
                high52_delta = metric_delta_block(
                    conn, "pct_52wk_high", key, r["last_date"], r["high52"]["pct_within_52wk_high"], min_days_back=0
                )
            results.append({
                "sector": r["sector"],
                "index_name": r["index_name"],
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
                "last_date": r["last_date"],
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"regime": regime, "regime_midsmall": regime_midsmall, "regime_smallcap": regime_smallcap, "sectors": results}


if __name__ == "__main__":
    import json
    print(json.dumps(compute_all(), indent=2, default=str))
