"""
The actual EMA / breadth / RS / composite-score math, shared by:
  - compute.py           (your 16 tracked sectors, real NSE index prices)
  - compute_basic_industry.py  (197 basic industries, synthetic indices)

Keeping this in one place means both views score things exactly the same
way -- no drift between the two.
"""
import pandas as pd
from config import EXTENDED_FROM_21EMA_PCT, LOW_SAMPLE_THRESHOLD


def series_for(conn, table: str, key_col: str, key_val: str) -> pd.Series:
    df = pd.read_sql_query(
        f"SELECT date, close FROM {table} WHERE {key_col} = ? ORDER BY date",
        conn, params=(key_val,),
    )
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"]


def ema_block(series: pd.Series) -> dict:
    if len(series) < 25:
        return {"available": False}
    ema21 = series.ewm(span=21, adjust=False).mean()
    ema50 = series.ewm(span=50, adjust=False).mean() if len(series) >= 55 else None
    ema200 = series.ewm(span=200, adjust=False).mean() if len(series) >= 205 else None

    last_price = series.iloc[-1]
    last_21 = ema21.iloc[-1]
    slope21 = last_21 - ema21.iloc[-6] if len(ema21) > 6 else 0

    out = {
        "available": True,
        "price": round(last_price, 2),
        "ema21": round(last_21, 2),
        "above_21": bool(last_price > last_21),
        "ema21_rising": bool(slope21 > 0),
        "pct_above_21": round((last_price - last_21) / last_21 * 100, 2),
        "extended": bool(abs((last_price - last_21) / last_21 * 100) > EXTENDED_FROM_21EMA_PCT),
    }
    if ema50 is not None:
        last_50 = ema50.iloc[-1]
        out.update({"ema50": round(last_50, 2), "above_50": bool(last_price > last_50)})
    else:
        out.update({"ema50": None, "above_50": None})

    if ema200 is not None:
        last_200 = ema200.iloc[-1]
        out.update({"ema200": round(last_200, 2), "above_200": bool(last_price > last_200)})
    else:
        out.update({"ema200": None, "above_200": None})

    stack_bits = [out["above_21"]]
    if out["above_50"] is not None:
        stack_bits.append(out["above_50"])
        stack_bits.append(bool(last_21 > last_50))
    if out["above_200"] is not None:
        stack_bits.append(out["above_200"])
        if out["ema50"] is not None:
            stack_bits.append(bool(last_50 > last_200))
    out["bullish_stack"] = bool(all(stack_bits)) if stack_bits else False
    return out


_MIXED_NOTES = {
    ("21", "50"): "early recovery -- long-term trend not yet reclaimed",
    ("21",): "choppy -- short-term bounce inside a longer downtrend",
}


def _join_labels(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def regime_block(series: pd.Series) -> dict:
    """Classifies an index (meant for the Nifty 50 benchmark) into a
    Bullish / Mixed / Bearish regime using the same ema_block() math
    used everywhere else, so this never drifts from the per-sector logic.

    Unlike a fixed 3-bucket label, the "Mixed" subtitle is assembled from
    exactly which EMAs are above/below -- "above 21 and 50, below 200" is
    a materially different situation from "above 21 only, below 50 and
    200", and collapsing both into one generic "Mixed" string would hide
    that difference.
    """
    ema = ema_block(series)
    if not ema.get("available"):
        return {"available": False}

    above, below = [], []
    for label, key in [("21", "above_21"), ("50", "above_50"), ("200", "above_200")]:
        val = ema.get(key)
        if val is None:
            continue
        (above if val else below).append(label)

    if not above and not below:
        return {"available": False}

    if not below:
        state = "Bullish"
        stack_note = "bullish stack intact" if ema.get("bullish_stack") else "stack not fully aligned"
        rising_note = "21 EMA rising" if ema.get("ema21_rising") else "21 EMA flattening"
        subtitle = f"Above 21/50/200 EMA -- {stack_note} -- {rising_note}"
    elif not above:
        state = "Bearish"
        subtitle = "Below 21/50/200 EMA"
    else:
        state = "Mixed"
        above_txt = f"above {_join_labels(above)} EMA"
        below_txt = f"below {_join_labels(below)} EMA"
        subtitle = f"{above_txt}, {below_txt}"
        note = _MIXED_NOTES.get(tuple(above))
        if note:
            subtitle += f" ({note})"

    return {
        "available": True,
        "state": state,
        "subtitle": subtitle,
        "price": ema.get("price"),
        "above_21": ema.get("above_21"),
        "above_50": ema.get("above_50"),
        "above_200": ema.get("above_200"),
        "bullish_stack": ema.get("bullish_stack"),
    }


def breadth_block(conn, symbols: list[str]) -> dict:
    if not symbols:
        return {"available": False}
    placeholders = ",".join("?" * len(symbols))
    df = pd.read_sql_query(
        f"SELECT symbol, date, close FROM stock_prices WHERE symbol IN ({placeholders}) ORDER BY date",
        conn, params=symbols,
    )
    if df.empty:
        return {"available": False}
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    if len(wide) < 10:
        return {"available": False}

    ma10 = wide.rolling(10).mean()
    above = (wide > ma10)

    def pct_above(row_idx):
        row = above.iloc[row_idx].dropna()
        if row.empty:
            return None
        return round(row.mean() * 100, 1)

    latest_pct = pct_above(-1)
    week_ago_idx = -6 if len(wide) >= 6 else 0
    week_ago_pct = pct_above(week_ago_idx)

    n_stocks = int(above.iloc[-1].notna().sum())
    return {
        "available": latest_pct is not None,
        "pct_above_10ma": latest_pct,
        "pct_above_10ma_week_ago": week_ago_pct,
        "breadth_rising": bool(latest_pct is not None and week_ago_pct is not None and latest_pct > week_ago_pct),
        "n_stocks": n_stocks,
        "low_sample": bool(n_stocks < LOW_SAMPLE_THRESHOLD),
    }


def rs_block(target_series: pd.Series, bench_series: pd.Series) -> dict:
    joined = pd.concat([target_series, bench_series], axis=1, join="inner")
    joined.columns = ["target", "bench"]
    if len(joined) < 25:
        return {"available": False}
    ratio = joined["target"] / joined["bench"]
    ratio_ema = ratio.ewm(span=21, adjust=False).mean()
    latest = ratio.iloc[-1]
    latest_ema = ratio_ema.iloc[-1]
    week_ago = ratio.iloc[-6] if len(ratio) >= 6 else ratio.iloc[0]
    return {
        "available": True,
        "rs_ratio": round(latest, 4),
        "rs_above_ema": bool(latest > latest_ema),
        "rs_rising_1w": bool(latest > week_ago),
        "history": [round(v, 4) for v in ratio.tail(60).tolist()],
    }


def get_company_names(conn, symbols: list[str]) -> dict:
    """Best-effort symbol -> company_name lookup from basic_industry_map."""
    if not symbols:
        return {}
    placeholders = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"SELECT symbol, company_name FROM basic_industry_map WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchall()
    return {sym: name for sym, name in rows if name}


def stock_detail_list(conn, symbols: list[str]) -> list[dict]:
    """Per-stock breakdown for a sector/industry: whether each symbol has
    price data, and if so whether it's above its own 10-day MA and its
    latest close. This is exactly what breadth_block() already counts
    internally -- surfaced here so the UI can show names instead of a
    bare total that doesn't match the math underneath it."""
    if not symbols:
        return []
    names = get_company_names(conn, symbols)
    placeholders = ",".join("?" * len(symbols))
    df = pd.read_sql_query(
        f"SELECT symbol, date, close FROM stock_prices WHERE symbol IN ({placeholders}) ORDER BY date",
        conn, params=symbols,
    )
    if df.empty:
        return [
            {"symbol": s, "name": names.get(s, s), "has_data": False, "above_10ma": None, "close": None}
            for s in symbols
        ]

    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    ma10 = wide.rolling(10).mean()
    above = wide > ma10
    have_data = set(wide.columns)

    out = []
    for s in symbols:
        if s not in have_data:
            out.append({"symbol": s, "name": names.get(s, s), "has_data": False, "above_10ma": None, "close": None})
            continue
        closes = wide[s].dropna()
        aboves = above[s].dropna()
        out.append({
            "symbol": s,
            "name": names.get(s, s),
            "has_data": True,
            "above_10ma": bool(aboves.iloc[-1]) if not aboves.empty else None,
            "close": round(float(closes.iloc[-1]), 2) if not closes.empty else None,
        })
    # stocks with data first (above-10MA ones first within that), no-data stocks last
    out.sort(key=lambda r: (not r["has_data"], not (r["above_10ma"] or False), r["symbol"]))
    return out


def composite_score(ema: dict, breadth: dict, rs: dict) -> int:
    """Simple, transparent point system -- add up what's true. Max 100."""
    score = 0
    if ema.get("available"):
        if ema.get("above_21"):
            score += 10
        if ema.get("above_50"):
            score += 10
        if ema.get("above_200"):
            score += 10
        if ema.get("bullish_stack"):
            score += 15
        if ema.get("ema21_rising"):
            score += 5
        if ema.get("extended"):
            score -= 10
    if breadth.get("available"):
        pct = breadth.get("pct_above_10ma") or 0
        score += round(pct / 100 * 25)
        if breadth.get("breadth_rising"):
            score += 10
    if rs.get("available"):
        if rs.get("rs_above_ema"):
            score += 10
        if rs.get("rs_rising_1w"):
            score += 5
    return max(0, min(100, score))
