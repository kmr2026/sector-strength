"""
The actual EMA / breadth / RS / composite-score math, shared by:
  - compute.py           (your 16 tracked sectors, real NSE index prices)
  - compute_basic_industry.py  (197 basic industries, synthetic indices)

Keeping this in one place means both views score things exactly the same
way -- no drift between the two.
"""
import pandas as pd
from config import EXTENDED_FROM_21EMA_PCT


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

    return {
        "available": latest_pct is not None,
        "pct_above_10ma": latest_pct,
        "pct_above_10ma_week_ago": week_ago_pct,
        "breadth_rising": bool(latest_pct is not None and week_ago_pct is not None and latest_pct > week_ago_pct),
        "n_stocks": int(above.iloc[-1].notna().sum()),
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
