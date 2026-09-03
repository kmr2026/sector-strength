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


def _compute_xp_score(rows: list[dict]) -> None:
    """Adds 'xp_score' to each row in place, via a disclosed (not
    reverse-engineered) formula shared by a trader for a similar
    "swing-friendly regime" indicator. Two explicit adaptations from the
    original spec, since it referenced inputs this project doesn't have
    an exact match for:

    - "4.5+ count" in the original Step 1 is treated as an advance/decline
      RATIO (100 x advancers / decliners), not a raw headcount -- matching
      how the source's own "4.5 r" column was described. A raw count
      doesn't carry the same "which side is winning" information a ratio
      does, so this reading is more internally consistent with the rest
      of the formula, but it's still an adaptation, not confirmed.
    - The formula's "10MA%"/"20MA%" are read as this project's own
      10EMA/21EMA breadth (no plain 20-day MA exists in this codebase
      today; 21EMA is the closest thing already computed).

    Must run on rows in CHRONOLOGICAL order (oldest first), across the
    FULL available history, not just the trailing display window -- XP
    depends on yesterday's own XP, so seeding it partway through recent
    history would start the recursion from an arbitrary, meaningless
    value. rows[i]['xp_score'] is set by mutating the same dicts the
    caller already holds references to.
    """
    import math
    z_state = None
    xp_prev = None
    for r in rows:
        ratio = r.get("adv_decl_ratio_4_5")
        pct10 = r.get("pct_above_10ema")
        pct21 = r.get("pct_above_21ema")
        dec_count = r.get("dec_4_5") or 1  # avoid log(0); a 0-decliner day is rare but real

        if ratio is None or ratio <= 0:
            r["xp_score"] = None
            continue
        z_state = ratio if z_state is None else (0.162 * ratio + 0.838 * z_state)

        if (xp_prev is None or pct10 is None or pct21 is None
                or not (0 < pct10 < 100) or not (0 < pct21 < 100) or z_state <= 0):
            xp = 15.0  # neutral seed for the first computable day only
        else:
            log_xp = (
                0.59 * math.log(xp_prev)
                + 0.47 * math.log(z_state)
                + 0.20 * math.log(pct10 / (100 - pct10))
                + 0.33
                - 0.07 * math.log(dec_count)
                - 0.08 * math.log(pct21 / (100 - pct21))
            )
            xp = math.exp(log_xp)
        r["xp_score"] = round(xp, 2)
        xp_prev = xp


def compute_all(lookback_days: int = 260) -> list[dict]:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT symbol, date, close, volume FROM stock_prices ORDER BY date",
            conn,
        )
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    vol_wide = df.pivot(index="date", columns="symbol", values="volume").sort_index()
    vol_wide = vol_wide.reindex(columns=wide.columns)  # guarantee identical column alignment to `wide`

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

    # 4.5% advance/decline counts -- inputs to the XP score (see
    # _compute_xp_score), kept separate from the 4%-threshold columns
    # above since XP's disclosed formula specifically uses 4.5%.
    adv_4_5 = ((daily_return >= 4.5) & has_return).sum(axis=1)
    dec_4_5 = ((daily_return <= -4.5) & has_return).sum(axis=1)

    # Up volume vs down volume: weight each stock's daily volume by
    # whether it closed up or down that day, rather than just counting
    # stocks -- catches a heavy-volume selloff in a few large names
    # hiding underneath a headline breadth number that still looks fine
    # because many small, thinly-traded stocks happened to close up.
    # Stocks with a flat (exactly 0%) or missing return contribute to
    # neither side, same as the 4%-threshold counts above only counting
    # stocks with a real return that day.
    up_mask = (daily_return > 0) & has_return
    down_mask = (daily_return < 0) & has_return
    up_volume = vol_wide.where(up_mask).sum(axis=1, skipna=True)
    down_volume = vol_wide.where(down_mask).sum(axis=1, skipna=True)
    total_volume = up_volume + down_volume
    up_volume_pct = (up_volume / total_volume.replace(0, pd.NA)) * 100

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
    # lookback_days) -- the XP score needs its own full history to
    # recursively "warm up" from, or seeding it partway through recent
    # history would start the recursion from an arbitrary value. Rows
    # built in chronological order here (ascending); re-sorted to
    # newest-first for display right before returning.
    all_rows = []
    for d in wide.index:
        nh, nl = int(new_highs.get(d, 0)), int(new_lows.get(d, 0))
        adv, dec = int(adv_4_5.get(d, 0)), int(dec_4_5.get(d, 0))
        ratio_4_5 = round(adv / dec * 100, 2) if dec > 0 else (round(adv * 100, 2) if adv > 0 else None)
        uv_pct = _r(up_volume_pct.get(d))
        # "90% Day" flag -- volume-only version of O'Neil's concept (real
        # definition also requires 90%+ of the day's total PRICE RANGE
        # moving the same direction, which this doesn't check -- so this
        # is a simplification, not the full authentic signal).
        day_type = None
        if uv_pct is not None:
            if uv_pct >= 90:
                day_type = "90% Up (vol)"
            elif uv_pct <= 10:
                day_type = "90% Down (vol)"
        all_rows.append({
            "date": d.date().isoformat(),
            "pct_above_10ema": _r(above_pct["10ema"].get(d)),
            "pct_above_21ema": _r(above_pct["21ema"].get(d)),
            "pct_above_50ema": _r(above_pct["50ema"].get(d)),
            "pct_above_200ema": _r(above_pct["200ema"].get(d)),
            "pct_4up": _r(pct_4up.get(d)),
            "pct_4down": _r(pct_4down.get(d)),
            "adv_4_5": adv,
            "dec_4_5": dec,
            "adv_decl_ratio_4_5": ratio_4_5,
            "up_volume_pct": uv_pct,
            "volume_day_type": day_type,
            "new_highs": nh,
            "new_lows": nl,
            "net_new_highs": nh - nl,
        })

    _compute_xp_score(all_rows)  # mutates each row in place, needs chronological order

    rows = all_rows[-lookback_days:]
    rows.sort(key=lambda r: r["date"], reverse=True)  # most recent first, matching the table's reading order
    return rows


if __name__ == "__main__":
    import json
    result = compute_all()
    print(f"{len(result)} days of market breadth history")
    if result:
        print(json.dumps(result[:3], indent=2, default=str))
