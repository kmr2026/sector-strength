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
from config import SECTORS, BENCHMARK
from db import get_conn
from scoring import series_for, ema_block, breadth_block, rs_block, regime_block, composite_score, stock_detail_list, score_delta_block


def compute_all() -> dict:
    results = []
    with get_conn() as conn:
        bench_series = series_for(conn, "index_prices", "sector", BENCHMARK)
        regime = regime_block(bench_series) if not bench_series.empty else {"available": False}
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
            delta = score_delta_block(conn, f"sector:{sector_name}", last_date, score)
            results.append({
                "sector": sector_name,
                "index_name": index_name,
                "score": score,
                "score_delta": delta,
                "ema": ema,
                "breadth": breadth,
                "rs": rs,
                "stocks": stock_detail_list(conn, symbols),
                "last_date": last_date,
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"regime": regime, "sectors": results}


if __name__ == "__main__":
    import json
    print(json.dumps(compute_all(), indent=2, default=str))
