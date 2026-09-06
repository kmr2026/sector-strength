"""
Market-wide breadth history: % of the FULL stock universe above each EMA
(10/21/50/200) -- and, when the frontend's EMA/SMA toggle is set to SMA,
the parallel plain-moving-average version of the same 4 windows -- the
daily 4.5%-up vs 4.5%-down split (plus the derived MBI 4.5R ratio), and
new-52-week-highs vs new-52-week-lows -- one row per trading day, going
back as far as your stored history allows (roughly a year, growing over
time since nothing prunes old rows).

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
import math
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
    #
    # SMA breadth is the same idea computed against a plain rolling mean
    # instead of an EMA -- purely a display-layer alternate for the
    # Market Breadth tab's EMA/SMA toggle. Nothing else on the site (the
    # composite score, sector strength, scanner) ever reads the *sma
    # fields; scoring.py stays EMA-only regardless of what's toggled here.
    periods = {10: "10", 21: "21", 50: "50", 200: "200"}
    above_pct = {}
    for suffix, span in periods.items():
        valid = wide.notna().rolling(span, min_periods=span).sum() >= span
        denom = valid.sum(axis=1)

        ema = wide.ewm(span=span, adjust=False).mean()
        above_ema = (wide > ema) & valid
        above_pct[f"{suffix}ema"] = (above_ema.sum(axis=1) / denom.replace(0, pd.NA)) * 100

        sma = wide.rolling(span, min_periods=span).mean()
        above_sma = (wide > sma) & valid
        above_pct[f"{suffix}sma"] = (above_sma.sum(axis=1) / denom.replace(0, pd.NA)) * 100

    # 4.5% up / 4.5% down: daily simple return per stock, then % of that
    # day's tracked universe crossing +-4.5%, plus the raw counts behind
    # those percentages (needed for the MBI 4.5R ratio below -- counts,
    # not percentages, since down-count can be legitimately zero and the
    # ratio needs to detect that exactly, not a rounded-to-zero percent).
    daily_return = wide.pct_change() * 100
    has_return = daily_return.notna()
    denom_ret = has_return.sum(axis=1)
    count_up = ((daily_return >= 4.5) & has_return).sum(axis=1)
    count_down = ((daily_return <= -4.5) & has_return).sum(axis=1)
    pct_4up = count_up / denom_ret.replace(0, pd.NA) * 100
    pct_4down = count_down / denom_ret.replace(0, pd.NA) * 100

    # MBI 4.5R = (up-count / down-count) * 100, rounded UP to the next
    # whole number (so e.g. 199.6 becomes 200, landing cleanly in the
    # next color band rather than sitting on a fractional boundary).
    # down-count == 0 makes the ratio infinite -- handled explicitly
    # rather than dividing by zero: if any stocks moved up 4.5%+ that day
    # the ratio is unboundedly bullish (mbi_uncapped=True, displayed as
    # ">400" and colored orange); if NEITHER side had any qualifying
    # moves, there's no signal at all that day (mbi_ratio=None, "n/a").
    mbi_ratio, mbi_uncapped = {}, {}
    for d in wide.index:
        up, down = int(count_up.get(d, 0)), int(count_down.get(d, 0))
        if down > 0:
            mbi_ratio[d] = math.ceil((up / down) * 100)
            mbi_uncapped[d] = False
        elif up > 0:
            mbi_ratio[d] = None
            mbi_uncapped[d] = True
        else:
            mbi_ratio[d] = None
            mbi_uncapped[d] = False

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

    # Build rows across the FULL available date range (not yet sliced to
    # lookback_days) -- consistent with how every metric here is built:
    # more history in, richer rolling windows out.
    all_rows = []
    for d in wide.index:
        nh, nl = int(new_highs.get(d, 0)), int(new_lows.get(d, 0))
        all_rows.append({
            "date": d.date().isoformat(),
            "pct_above_10ema": _r(above_pct["10ema"].get(d)),
            "pct_above_21ema": _r(above_pct["21ema"].get(d)),
            "pct_above_50ema": _r(above_pct["50ema"].get(d)),
            "pct_above_200ema": _r(above_pct["200ema"].get(d)),
            "pct_above_10sma": _r(above_pct["10sma"].get(d)),
            "pct_above_21sma": _r(above_pct["21sma"].get(d)),
            "pct_above_50sma": _r(above_pct["50sma"].get(d)),
            "pct_above_200sma": _r(above_pct["200sma"].get(d)),
            "pct_4up": _r(pct_4up.get(d)),
            "pct_4down": _r(pct_4down.get(d)),
            "mbi_ratio": mbi_ratio.get(d),
            "mbi_uncapped": mbi_uncapped.get(d, False),
            "new_highs": nh,
            "new_lows": nl,
            "net_new_highs": nh - nl,
        })

    rows = all_rows[-lookback_days:]
    rows.sort(key=lambda r: r["date"], reverse=True)  # most recent first, matching the table's reading order
    return rows


if __name__ == "__main__":
    import json
    result = compute_all()
    print(f"{len(result)} days of market breadth history")
    if result:
        print(json.dumps(result[:3], indent=2, default=str))
