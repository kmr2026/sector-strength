"""
Scores your 16 tracked sectors using their real, official NSE index prices.
Breadth is measured ONLY over each sector's official narrow index
constituents (the actual stocks that are members of that index) -- not
widened to the broader Total Market universe. That broader view now lives
in the "All Industries" tab (compute_basic_industry.py), which is the
right place for it; this tab stays true to "what's actually in the index."

See scoring.py for the actual EMA/breadth/RS/score math (shared with
compute_basic_industry.py).
"""
from config import SECTORS, BENCHMARK, MIDSMALL_INDEX
from db import get_conn
from scoring import series_for, ema_block, breadth_block, rs_block, regime_block, composite_score, stock_detail_list, score_delta_block, regime_delta_block, score_history_series


def compute_all() -> dict:
    results = []
    with get_conn() as conn:
        bench_series = series_for(conn, "index_prices", "sector", BENCHMARK)
        regime = regime_block(bench_series) if not bench_series.empty else {"available": False}
        midsmall_series = series_for(conn, "index_prices", "sector", MIDSMALL_INDEX)
        regime_midsmall = regime_block(midsmall_series) if not midsmall_series.empty else {"available": False}

        nifty_last_date = bench_series.index[-1].date().isoformat() if not bench_series.empty else None
        regime.update(regime_delta_block(conn, f"regime:{BENCHMARK}", nifty_last_date, regime.get("state")))
        midsmall_last_date = midsmall_series.index[-1].date().isoformat() if not midsmall_series.empty else None
        regime_midsmall.update(regime_delta_block(conn, f"regime:{MIDSMALL_INDEX}", midsmall_last_date, regime_midsmall.get("state")))

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
            key = f"sector:{sector_name}"
            delta = score_delta_block(
                conn, key, last_date, score,
                bullish_stack=ema.get("bullish_stack") if ema.get("available") else None,
                overheated=breadth.get("overheated") if breadth.get("available") else None,
            )
            results.append({
                "sector": sector_name,
                "index_name": index_name,
                "score": score,
                "score_delta": delta,
                "score_history": score_history_series(conn, key),
                "ema": ema,
                "breadth": breadth,
                "rs": rs,
                "stocks": stock_detail_list(conn, symbols),
                "last_date": last_date,
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"regime": regime, "regime_midsmall": regime_midsmall, "sectors": results}


if __name__ == "__main__":
    import json
    print(json.dumps(compute_all(), indent=2, default=str))
