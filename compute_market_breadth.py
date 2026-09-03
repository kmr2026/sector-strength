"""
Market-wide breadth history: % of the FULL stock universe above each EMA
(10/21/50/200), the daily 4%-up vs 4%-down split, and new-52-week-highs
vs new-52-week-lows -- one row per trading day, going back as far as your
stored history allows (roughly a year, growing over time since nothing
prunes old rows).

Different in kind from every other compute_*.py in this project: those
all answer "how does this group look TODAY." This answers "how has the
WHOLE MARKET looked, day by day" -- powers the Market Breadth tab
(docs/breadth.html), which shows a scrollable history table, not a
single snapshot.

Deliberately vectorized across the full date x symbol price matrix
(pandas .ewm()/.rolling() applied column-wise) rather than looping over
each day individually -- every metric here is just a column-wise rolling
calculation compared against that day's close, so there's no benefit to
a per-day loop and it would be far slower across ~250+ days x ~2,900
stocks.
"""
import pandas as pd
from db import get_conn


def _r(v):
    if v is None or pd.isna(v):
        return None
    return round(float(v), 2)


def compute_all(lookback_days: int = 260) -> list[dict]:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT symbol, date, close FROM stock_prices ORDER BY date",
            conn,
        )
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()

    # EMA breadth: % of stocks (with a full, real EMA window that day)
    # trading above each EMA. ewm(adjust=False) matches the same EMA
    # convention used everywhere else on this site (ema_block in
    # scoring.py). A stock without `span` days of history yet is left OUT
    # of that EMA's count entirely rather than being marked "below" --
    # same "n/a beats a fabricated number" rule the rest of this project
    # already follows for young stocks.
    ema_periods = {"10ema": 10, "21ema": 21, "50ema": 50, "200ema": 200}
    above_pct = {}
    for label, span in ema_periods.items():
        ema = wide.ewm(span=span, adjust=False).mean()
        valid = wide.notna().rolling(span, min_periods=span).sum() >= span
        above = (wide > ema) & valid
        denom = valid.sum(axis=1)
        above_pct[label] = (above.sum(axis=1) / denom.replace(0, pd.NA)) * 100

    # 4% up / 4% down: daily simple return per stock, then % of that
    # day's tracked universe crossing +-4%.
    daily_return = wide.pct_change() * 100
    has_return = daily_return.notna()
    denom_ret = has_return.sum(axis=1)
    pct_4up = ((daily_return >= 4) & has_return).sum(axis=1) / denom_ret.replace(0, pd.NA) * 100
    pct_4down = ((daily_return <= -4) & has_return).sum(axis=1) / denom_ret.replace(0, pd.NA) * 100

    # New 52-week highs/lows: trailing 252-trading-day window INCLUDING
    # today -- same convention as pct_from_52wk_high/low elsewhere on
    # this site. A stock "makes a new high" on any day its close equals
    # that trailing max, which can only be true on the day it actually
    # sets one.
    window = 252
    roll_max = wide.rolling(window, min_periods=10).max()
    roll_min = wide.rolling(window, min_periods=10).min()
    is_new_high = wide.ge(roll_max) & wide.notna()
    is_new_low = wide.le(roll_min) & wide.notna()
    new_highs = is_new_high.sum(axis=1)
    new_lows = is_new_low.sum(axis=1)

    dates = wide.index[-lookback_days:]
    rows = []
    for d in dates:
        nh, nl = int(new_highs.get(d, 0)), int(new_lows.get(d, 0))
        rows.append({
            "date": d.date().isoformat(),
            "pct_above_10ema": _r(above_pct["10ema"].get(d)),
            "pct_above_21ema": _r(above_pct["21ema"].get(d)),
            "pct_above_50ema": _r(above_pct["50ema"].get(d)),
            "pct_above_200ema": _r(above_pct["200ema"].get(d)),
            "pct_4up": _r(pct_4up.get(d)),
            "pct_4down": _r(pct_4down.get(d)),
            "new_highs": nh,
            "new_lows": nl,
            "net_new_highs": nh - nl,
        })
    rows.sort(key=lambda r: r["date"], reverse=True)  # most recent first, matching the table's reading order
    return rows


if __name__ == "__main__":
    import json
    result = compute_all()
    print(f"{len(result)} days of market breadth history")
    if result:
        print(json.dumps(result[:3], indent=2, default=str))
