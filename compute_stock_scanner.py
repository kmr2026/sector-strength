"""
Per-stock scanner data -- computes EMA position, RS Rating, distance from
52-week high/low, 20-day ADR%, and 30-day average turnover for every NSE
stock with enough history.

Unlike compute.py/compute_basic_industry.py (which score SECTORS/
INDUSTRIES by aggregating many stocks into one group row), this scores
INDIVIDUAL STOCKS directly -- one row per symbol. Powers the stock
scanner UI (docs/scanner.html), a free alternative to paid scanners like
ChartsMaze's custom-scanner.

RS Rating here is percentile-ranked against the FULL stock universe (not
a sector/industry subset) -- reuses rs_ratings_from_raw() from scoring.py
on the same raw per-stock scores compute.py/compute_basic_industry.py
already use for their group-level RS Ratings, so a stock's number here is
directly comparable to how it contributes to its sector's/industry's own
RS Rating.
"""
import pandas as pd
from db import get_conn
from scoring import ema_block, universe_raw_rs_scores, rs_ratings_from_raw, pct_return


def _stock_52wk_block(series: pd.Series) -> dict:
    if len(series) < 10:
        return {"available": False}
    window = series.tail(min(len(series), 252))
    high, low, last = window.max(), window.min(), series.iloc[-1]
    if not high or not low:
        return {"available": False}
    return {
        "available": True,
        "high_52wk": round(float(high), 2),
        "low_52wk": round(float(low), 2),
        "pct_from_high": round((high - last) / high * 100, 2),
        "pct_from_low": round((last - low) / low * 100, 2),
    }


def _adr_pct(high_s: pd.Series, low_s: pd.Series, days: int = 20) -> float | None:
    """Average Daily Range %, ChartsMaze-style: mean of (high-low)/low*100
    over the trailing N days -- a volatility measure, not a directional one."""
    joined = pd.concat([high_s, low_s], axis=1, join="inner").dropna()
    joined.columns = ["high", "low"]
    if len(joined) < days:
        return None
    recent = joined.tail(days)
    valid = recent[recent["low"] > 0]
    if valid.empty:
        return None
    daily_range_pct = (valid["high"] - valid["low"]) / valid["low"] * 100
    return round(float(daily_range_pct.mean()), 2)


def _avg_turnover_cr(close_s: pd.Series, vol_s: pd.Series, days: int = 30) -> float | None:
    """Average daily (price x volume) over the trailing N days, in crores --
    ChartsMaze's liquidity filter equivalent."""
    joined = pd.concat([close_s, vol_s], axis=1, join="inner").dropna()
    joined.columns = ["close", "volume"]
    if len(joined) < days:
        return None
    recent = joined.tail(days)
    turnover = (recent["close"] * recent["volume"]).mean()
    return round(float(turnover) / 1e7, 2)  # rupees -> crores


def get_symbol_metadata(conn) -> dict:
    """symbol -> {name, basic_industry, sector, shares_outstanding}, best-effort
    from basic_industry_map. shares_outstanding is the stable, derived
    share count (see classify_via_screener.py) -- market cap itself is
    computed fresh below from this x TODAY's close, not read as a stored
    snapshot, so it never goes stale as the price moves.

    `sector` is NSE's official classification tier (Macro-Economic Sector ->
    Sector -> Industry -> Basic Industry) -- classify_industries.py has
    always captured it alongside basic_industry, it just never made it into
    this export before. Distinct from the index-based Sectoral Indices tab
    on the home page (Nifty Auto, Nifty Bank, etc.) -- same word, different
    grouping, kept separate on purpose."""
    rows = conn.execute(
        "SELECT symbol, company_name, basic_industry, sector, shares_outstanding, listing_date FROM basic_industry_map"
    ).fetchall()
    return {r[0]: {"name": r[1] or r[0], "basic_industry": r[2], "sector": r[3], "shares_outstanding": r[4], "listing_date": r[5]} for r in rows}


def get_circuit_bands(conn) -> dict:
    """symbol -> assigned circuit band (2/5/10/20), from NSE's own daily
    price-bands file (see fetch_data.py's update_circuit_bands). A
    symbol with no entry is F&O-eligible and has no fixed band -- callers
    should treat a missing key as 'no band', not as band 0."""
    rows = conn.execute("SELECT symbol, band FROM circuit_bands").fetchall()
    return {r[0]: r[1] for r in rows}


def compute_all() -> list[dict]:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT symbol, date, close, high, low, volume FROM stock_prices ORDER BY date",
            conn,
        )
        if df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"])

        # A symbol whose price data stopped updating a while ago (delisted,
        # suspended, renamed -- NSE just silently stops including it in the
        # daily bhavcopy) still sits in stock_prices with its last real
        # date frozen in the past. Left in, its 52wk-high/low, EMA, and
        # turnover all get computed off that stale "last" row as if it
        # were current -- producing exactly the kind of nonsense numbers
        # (hundreds-of-percent-from-low, huge turnover) that don't
        # actually reflect anything tradeable today. A stock genuinely
        # trading has a last date within a few sessions of the most
        # recent date anywhere in the table; anything older than that
        # (10 calendar days -- enough slack for a long weekend/holiday
        # run without falsely dropping active stocks) is excluded here,
        # once, rather than silently poisoning every metric downstream.
        global_max_date = df["date"].max()
        stale_cutoff = global_max_date - pd.Timedelta(days=10)
        last_date_by_symbol = df.groupby("symbol")["date"].max()
        active_symbols = set(last_date_by_symbol[last_date_by_symbol >= stale_cutoff].index)
        df = df[df["symbol"].isin(active_symbols)]

        meta = get_symbol_metadata(conn)
        circuit_bands = get_circuit_bands(conn)

        # Same raw-score computation compute.py/compute_basic_industry.py
        # use for their group-level RS Ratings -- ranked here against the
        # FULL universe instead of averaged into a group first.
        universe_scores = universe_raw_rs_scores(conn)
        ratings = rs_ratings_from_raw(universe_scores)

        results = []
        for symbol, g in df.groupby("symbol"):
            g = g.sort_values("date")
            idx = g["date"]
            close_s = pd.Series(g["close"].values, index=idx)
            high_s = pd.Series(g["high"].values, index=idx)
            low_s = pd.Series(g["low"].values, index=idx)
            vol_s = pd.Series(g["volume"].values, index=idx)

            ema = ema_block(close_s)
            wk52 = _stock_52wk_block(close_s)
            adr = _adr_pct(high_s, low_s)
            turnover = _avg_turnover_cr(close_s, vol_s)
            return_1d = pct_return(close_s, 1)
            return_1w = pct_return(close_s, 5)
            return_1m = pct_return(close_s, 21)
            return_3m = pct_return(close_s, 63)
            return_6m = pct_return(close_s, 126)
            return_1y = pct_return(close_s, 252)
            info = meta.get(symbol, {})
            last_close = round(float(close_s.iloc[-1]), 2)
            shares = info.get("shares_outstanding")
            # Market cap computed fresh here, every run, from the STABLE
            # share count x TODAY's close -- not a stored snapshot, so it
            # tracks the current price automatically instead of going
            # stale between classify_via_screener.py runs.
            market_cap_cr = round(shares * last_close / 1e7, 2) if shares else None

            results.append({
                "symbol": symbol,
                "name": info.get("name", symbol),
                "basic_industry": info.get("basic_industry"),
                "sector": info.get("sector"),
                "listing_date": info.get("listing_date"),
                "market_cap_cr": market_cap_cr,
                "close": last_close,
                "last_date": g["date"].iloc[-1].date().isoformat(),
                "ema": ema,
                "rs_rating": ratings.get(symbol),
                "return_1d": return_1d,
                "return_1w": return_1w,
                "return_1m": return_1m,
                "return_3m": return_3m,
                "return_6m": return_6m,
                "return_1y": return_1y,
                "circuit_band": circuit_bands.get(symbol),
                "pct_from_52wk_high": wk52.get("pct_from_high") if wk52.get("available") else None,
                "pct_from_52wk_low": wk52.get("pct_from_low") if wk52.get("available") else None,
                "high_52wk": wk52.get("high_52wk") if wk52.get("available") else None,
                "low_52wk": wk52.get("low_52wk") if wk52.get("available") else None,
                "adr_pct_20d": adr,
                "avg_turnover_cr_30d": turnover,
            })

    results.sort(key=lambda r: r["rs_rating"] if r["rs_rating"] is not None else -1, reverse=True)
    return results


if __name__ == "__main__":
    import json
    result = compute_all()
    print(f"{len(result)} stocks scanned")
    print(json.dumps(result[:3], indent=2, default=str))
