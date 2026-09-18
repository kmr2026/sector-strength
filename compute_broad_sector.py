"""
Breadth (>10MA, and its trend vs a week ago) for NSE's real Sector tier
(Financial Services, Healthcare, Consumer Discretionary...) -- the
`sector` column in basic_industry_map, populated by
classify_via_screener.py's breadcrumb parsing.

Deliberately NOT the full compute_basic_industry.py treatment (no score,
no EMA, no synthetic index, no RS Rating) -- the Scanner's Scan Summary
only ever displays breadth + trend for this grouping, and every one of
those other numbers would need its own synthetic index built and
maintained for a grouping nothing else on the site currently shows. If a
real use for the rest of that apparatus comes up later, it's a natural
extension of this file -- not built speculatively now.

This `sector` tier is DISTINCT from the 16 tracked Sectoral Indices in
compute.py (Nifty Auto, Nifty Bank, etc.) -- same word, different
classification, kept deliberately separate everywhere else in this
codebase (see compute_stock_scanner.py's get_symbol_metadata
docstring). This file scores the tier the Scanner's Scan Summary
"Sector" mode groups by; compute.py scores the index-based one the
Sectoral Indices dashboard tab shows.
"""
from config import MIN_STOCKS_PER_BASIC_INDUSTRY
from db import get_conn
from scoring import breadth_block

import pandas as pd


def compute_all(min_stocks: int = MIN_STOCKS_PER_BASIC_INDUSTRY) -> list[dict]:
    with get_conn() as conn:
        groups = pd.read_sql_query(
            "SELECT sector, symbol FROM basic_industry_map WHERE sector IS NOT NULL",
            conn,
        )
        if groups.empty:
            return []

        results = []
        for sector_name, group_df in groups.groupby("sector"):
            symbols = group_df["symbol"].tolist()
            breadth = breadth_block(conn, symbols)
            n_with_data = breadth.get("n_stocks", 0) if breadth.get("available") else 0
            if max(len(symbols), n_with_data) < min_stocks:
                continue  # too few stocks for a breadth reading to mean anything
            results.append({
                "sector": sector_name,
                "n_stocks_total": len(symbols),
                "breadth": breadth,
            })

    results.sort(key=lambda r: (r["breadth"].get("pct_above_10ma") or -1), reverse=True)
    return results


if __name__ == "__main__":
    import json
    result = compute_all()
    print(f"{len(result)} sectors scored (min {MIN_STOCKS_PER_BASIC_INDUSTRY} stocks)")
    print(json.dumps(result[:3], indent=2, default=str))
