"""
The actual EMA / breadth / RS / composite-score math, shared by:
  - compute.py                  (your 17 tracked sectors, real NSE index prices)
  - compute_basic_industry.py   (basic industries, synthetic indices)

Keeping this in one place means both views score things exactly the same
way -- no drift between the two.

Table creation for score_history / regime_history lives centrally in
db.py's init_db() now, not here -- this file just reads/writes to them,
assuming init_db() has already been run (fetch_data.py does this at the
start of every run).
"""
import pandas as pd
from config import EXTENDED_FROM_21EMA_PCT, LOW_SAMPLE_THRESHOLD, OVERHEATED_BREADTH_PCT


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
    """Classifies an index (meant for the Nifty 50 benchmark, or the
    Mid/Smallcap 400 second regime benchmark) into a Bullish / Mixed /
    Bearish regime using the same ema_block() math used everywhere else,
    so this never drifts from the per-sector logic.

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
    ma21 = wide.rolling(21).mean()
    above10 = (wide > ma10)
    above21 = (wide > ma21)

    def pct_above(above_df, row_idx):
        row = above_df.iloc[row_idx].dropna()
        if row.empty:
            return None
        return round(row.mean() * 100, 1)

    latest_pct = pct_above(above10, -1)
    week_ago_idx = -6 if len(wide) >= 6 else 0
    week_ago_pct = pct_above(above10, week_ago_idx)
    latest_pct_21 = pct_above(above21, -1) if len(wide) >= 21 else None
    week_ago_pct_21 = pct_above(above21, week_ago_idx) if len(wide) >= 21 else None

    n_stocks = int(above10.iloc[-1].notna().sum())

    return {
        "available": latest_pct is not None,
        "pct_above_10ma": latest_pct,
        "pct_above_10ma_week_ago": week_ago_pct,
        "breadth_rising": bool(latest_pct is not None and week_ago_pct is not None and latest_pct > week_ago_pct),
        "pct_above_21ma": latest_pct_21,
        "pct_above_21ma_week_ago": week_ago_pct_21,
        "breadth_21_rising": bool(latest_pct_21 is not None and week_ago_pct_21 is not None and latest_pct_21 > week_ago_pct_21),
        "overheated": bool(latest_pct_21 is not None and latest_pct_21 >= OVERHEATED_BREADTH_PCT),
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
    price data, and if so whether it's above its own 10-day AND 21-day MA,
    plus its latest close. The 10-day flag is what breadth_block() counts
    internally; 21-day is added so the UI can distinguish "cooling off but
    still above its medium-term trend" from "broken on both timeframes" --
    not just a flat above/below split."""
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
            {"symbol": s, "name": names.get(s, s), "has_data": False, "above_10ma": None, "above_21ma": None, "close": None}
            for s in symbols
        ]

    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    ma10 = wide.rolling(10).mean()
    ma21 = wide.rolling(21).mean()
    above10 = wide > ma10
    above21 = wide > ma21
    have_data = set(wide.columns)

    out = []
    for s in symbols:
        if s not in have_data:
            out.append({"symbol": s, "name": names.get(s, s), "has_data": False, "above_10ma": None, "above_21ma": None, "close": None})
            continue
        closes = wide[s].dropna()
        aboves10 = above10[s].dropna()
        aboves21 = above21[s].dropna()
        out.append({
            "symbol": s,
            "name": names.get(s, s),
            "has_data": True,
            "above_10ma": bool(aboves10.iloc[-1]) if not aboves10.empty else None,
            "above_21ma": bool(aboves21.iloc[-1]) if not aboves21.empty else None,
            "close": round(float(closes.iloc[-1]), 2) if not closes.empty else None,
        })
    # priority: has data > above 10MA > above 21MA > symbol, so the
    # strongest stocks (green) sort first, then the "cooling off" ones
    # (orange), then broken ones (red), then no-data stocks last
    out.sort(key=lambda r: (not r["has_data"], not (r["above_10ma"] or False), not (r["above_21ma"] or False), r["symbol"]))
    return out


def score_delta_block(conn, key: str, date: str | None, score: int,
                       bullish_stack: bool | None = None, overheated: bool | None = None) -> dict:
    """Reads the most recent PRIOR score (and bullish_stack/overheated
    state) for this key (sector/industry) and records today's for next
    time. One call does both, so callers just pass in what they already
    have (key, the data's own last_date -- not wall-clock today, so a
    rerun on the same trading day is a no-op rather than faking a delta
    -- the freshly computed score, and the two flip-worth-flagging flags).

    *_changed is True/False only when we actually know the prior value;
    None means "unknown" (e.g. the very first run after this field was
    added, when older rows predate it) -- deliberately not reported as a
    flip just because the column used to be empty.

    Assumes score_history (with bullish_stack/overheated columns) already
    exists -- db.py's init_db() guarantees this, including migrating
    databases created before those columns existed.
    """
    if not date:
        return {"available": False}
    row = conn.execute(
        "SELECT date, score, bullish_stack, overheated FROM score_history "
        "WHERE key = ? AND date < ? ORDER BY date DESC LIMIT 1",
        (key, date),
    ).fetchone()
    conn.execute(
        "INSERT INTO score_history (key, date, score, bullish_stack, overheated) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(key, date) DO UPDATE SET score = excluded.score, "
        "bullish_stack = excluded.bullish_stack, overheated = excluded.overheated",
        (key, date, score, bullish_stack, overheated),
    )
    if row is None:
        return {"available": False}
    prev_date, prev_score, prev_bullish_stack, prev_overheated = row

    def _changed(new, old):
        if new is None or old is None:
            return None
        return bool(new) != bool(old)

    return {
        "available": True,
        "delta": score - prev_score,
        "prev_score": prev_score,
        "prev_date": prev_date,
        "bullish_stack_changed": _changed(bullish_stack, prev_bullish_stack),
        "overheated_changed": _changed(overheated, prev_overheated),
    }


def regime_delta_block(conn, key: str, date: str | None, state: str | None) -> dict:
    """Same idea as score_delta_block but for a regime's Bullish/Mixed/
    Bearish state string (used for the Nifty 50 / MIDSMALL400 banners) --
    a separate small table since a state string isn't a score.

    Returns 'delta_available' (not 'available') deliberately -- the
    caller merges this dict into regime_block()'s own output via
    dict.update(), and regime_block() already uses 'available' to mean
    something different (whether the regime itself could be computed).
    Reusing that name would silently overwrite it.

    Assumes regime_history already exists -- db.py's init_db() guarantees
    this.
    """
    if not date or not state:
        return {"delta_available": False}
    row = conn.execute(
        "SELECT date, state FROM regime_history WHERE key = ? AND date < ? ORDER BY date DESC LIMIT 1",
        (key, date),
    ).fetchone()
    conn.execute(
        "INSERT INTO regime_history (key, date, state) VALUES (?, ?, ?) "
        "ON CONFLICT(key, date) DO UPDATE SET state = excluded.state",
        (key, date, state),
    )
    if row is None:
        return {"delta_available": False}
    prev_date, prev_state = row
    return {"delta_available": True, "changed": state != prev_state, "prev_state": prev_state, "prev_date": prev_date}


def score_history_series(conn, key: str, limit: int = 60) -> list[int]:
    """Chronological list of this key's recent recorded scores, for a
    sparkline -- same shape as rs_block()'s 'history' list."""
    rows = conn.execute(
        "SELECT score FROM score_history WHERE key = ? ORDER BY date DESC LIMIT ?",
        (key, limit),
    ).fetchall()
    return [r[0] for r in reversed(rows)]


def pct_return(series: pd.Series, days: int) -> float | None:
    """Simple % price change over the trailing N trading days -- lighter
    weight than RS Rating's 253-day requirement, so young stocks/industries
    that can't get an RS Rating yet can often still show a period return.
    Shared by the stock scanner (per-stock 1M/3M) and the basic-industry
    view (per-industry 1W/1M/3M, off the synthetic index)."""
    if len(series) < days + 1:
        return None
    last = series.iloc[-1]
    base = series.iloc[-1 - days]
    if not base:
        return None
    return round((last - base) / base * 100, 2)


def ordinal_rank_desc(values_by_key: dict) -> dict:
    """Ranks a {key: value} dict by value descending -- 1 = highest value,
    matching the plain 'Rank 1, 2, 3...' convention (not a 1-99 percentile
    like RS Rating). Keys with a None value are left out of the ranking
    entirely rather than being pushed to the bottom, since 'no data' isn't
    the same claim as 'worst performer'."""
    ranked_keys = sorted(
        (k for k, v in values_by_key.items() if v is not None),
        key=lambda k: values_by_key[k],
        reverse=True,
    )
    return {k: i + 1 for i, k in enumerate(ranked_keys)}


def stock_raw_rs_score(series: pd.Series) -> float | None:
    """Weighted price-performance score behind an RS Rating, in the style
    widely used to approximate MarketSmith/IBD's methodology (not
    officially published by them): 40% * 3-month return + 20% * 6-month +
    20% * 9-month + 20% * 12-month, so the most recent quarter counts
    double each of the other three. Each period is approximated as
    N*21 trading days back. Returns None without a full ~12 months
    (252 trading days) of history -- a partial score would silently
    understate a young listing's momentum rather than being absent.
    """
    if len(series) < 253:
        return None
    last = series.iloc[-1]

    def pct(days_back: int) -> float | None:
        idx = -1 - days_back
        if -idx > len(series):
            return None
        base = series.iloc[idx]
        if not base:
            return None
        return (last - base) / base * 100

    p3, p6, p9, p12 = pct(63), pct(126), pct(189), pct(252)
    if None in (p3, p6, p9, p12):
        return None
    return 0.4 * p3 + 0.2 * p6 + 0.2 * p9 + 0.2 * p12


def universe_raw_rs_scores(conn) -> dict:
    """Raw RS score for every symbol in stock_prices with enough history,
    computed once per run and shared across every sector/industry group
    rather than re-querying per group -- this is the single most
    expensive step RS Rating adds, so it only happens once."""
    df = pd.read_sql_query("SELECT symbol, date, close FROM stock_prices ORDER BY date", conn)
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    scores = {}
    for symbol, g in df.groupby("symbol"):
        s = g.set_index("date")["close"].sort_index()
        raw = stock_raw_rs_score(s)
        if raw is not None:
            scores[symbol] = raw
    return scores


def group_raw_rs_score(universe_scores: dict, symbols: list[str]) -> float | None:
    """A group's (sector/industry) raw RS score: the average of its
    constituent stocks' raw scores (only ones with a computable score).
    Averaging RAW scores here -- and percentile-ranking once at the group
    level via rs_ratings_from_raw() -- avoids the distortion of averaging
    already-percentile-ranked numbers."""
    vals = [universe_scores[s] for s in symbols if s in universe_scores]
    if not vals:
        return None
    return sum(vals) / len(vals)


def rs_ratings_from_raw(raw_by_key: dict) -> dict:
    """Percentile-ranks a {key: raw_group_score} dict onto MarketSmith's
    1-99 scale (99 = best), ranking each group against every other group
    passed in -- so sectors are ranked against sectors, and basic
    industries against basic industries, as two separate universes,
    matching how compute.py/compute_basic_industry.py already keep those
    two views separate everywhere else."""
    keys = [k for k, v in raw_by_key.items() if v is not None]
    n = len(keys)
    if n == 0:
        return {}
    sorted_vals = sorted(raw_by_key[k] for k in keys)
    ratings = {}
    for k in keys:
        v = raw_by_key[k]
        below = sum(1 for x in sorted_vals if x < v)
        pct = below / n
        ratings[k] = max(1, min(99, round(pct * 98) + 1))
    return ratings


def pct_within_52wk_high_block(conn, symbols: list[str], band_pct: float = 5.0) -> dict:
    """% of the group's stocks currently trading within band_pct% of
    their own trailing 52-week (252 trading day) high. Distinct from the
    10MA/21MA breadth columns -- a stock can be above its 21MA in a clean
    uptrend while still being well off its 52wk high, so this isolates
    the narrower set actually pushing into new-high territory, which is
    a more direct leadership/EP-breakout signal."""
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
    window = wide.tail(min(len(wide), 252))
    high_52wk = window.max()
    latest = wide.iloc[-1]
    within = {}
    for s in wide.columns:
        h, c = high_52wk.get(s), latest.get(s)
        if pd.isna(h) or pd.isna(c) or not h:
            continue
        within[s] = bool((h - c) / h * 100 <= band_pct)
    n_stocks = len(within)
    if n_stocks == 0:
        return {"available": False}
    pct = round(sum(within.values()) / n_stocks * 100, 1)
    return {"available": True, "pct_within_52wk_high": pct, "n_stocks": n_stocks, "band_pct": band_pct}


def metric_delta_block(conn, metric: str, key: str, date: str | None, value, min_days_back: int = 0) -> dict:
    """Generic day-over-day / N-day-back delta tracker for any numeric
    per-key metric, backed by the shared metric_history table -- one row
    per (metric, key, date) -- so RS Rating and % within 52wk high don't
    each need their own dedicated table. Mirrors score_delta_block()'s
    'read the prior value, then record today's' pattern.

    min_days_back=0 compares to whatever the immediately prior run
    recorded -- effectively "yesterday", since this pipeline runs once a
    day. A larger value (e.g. 6) skips same-week noise for a real
    week-ago comparison, matching how breadth's own week-ago columns
    already work.
    """
    if date is None or value is None:
        return {"available": False}
    import datetime as _dt
    cutoff = (_dt.date.fromisoformat(date) - _dt.timedelta(days=min_days_back)).isoformat()
    row = conn.execute(
        "SELECT date, value FROM metric_history WHERE metric = ? AND key = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (metric, key, cutoff),
    ).fetchone()
    conn.execute(
        "INSERT INTO metric_history (metric, key, date, value) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(metric, key, date) DO UPDATE SET value = excluded.value",
        (metric, key, date, value),
    )
    if row is None:
        return {"available": False}
    prev_date, prev_value = row
    diff = round(value - prev_value, 2)
    return {
        "available": True,
        "delta": diff,
        "prev_value": prev_value,
        "prev_date": prev_date,
        "direction": "up" if diff > 0 else ("down" if diff < 0 else "flat"),
    }


def composite_score(ema: dict, breadth: dict, rs: dict) -> int:
    """Simple, transparent point system -- add up what's true. Max 100.

    Breadth is scored on the 21-day MA (not 10-day) to match the EMA
    block's own 21/50/200 lens -- 10MA breadth stays on the dashboard as
    a faster, unscored early-warning column, but a score built partly on
    a 10-day window and partly on a 21/50/200-day one was internally
    inconsistent. RS carries more weight than before (up to 25 vs 15)
    since it's the most direct "is this actually beating the market"
    signal -- offset by trimming breadth's ceiling so the total still
    caps at 100 (EMA 50 + breadth 25 + RS 25).
    """
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
        pct = breadth.get("pct_above_21ma") or 0
        score += round(pct / 100 * 20)
        if breadth.get("breadth_21_rising"):
            score += 5
    if rs.get("available"):
        if rs.get("rs_above_ema"):
            score += 15
        if rs.get("rs_rising_1w"):
            score += 10
    return max(0, min(100, score))
