"""
One-off diagnostic: find exactly which stocks flip between "above 200EMA"
and "above 200SMA" on the most recent day, and print enough about each one
to spot whether it's a real market-structure quirk or a data problem.

Run this from your project folder (where db.py and stock_prices live):
    python diagnose_200_divergence.py

Doesn't touch any files -- read-only, just prints to the console.
"""
import pandas as pd
from db import get_conn

SPAN = 200

with get_conn() as conn:
    df = pd.read_sql_query(
        "SELECT symbol, date, close FROM stock_prices ORDER BY date",
        conn,
    )
df["date"] = pd.to_datetime(df["date"])
wide = df.pivot(index="date", columns="symbol", values="close").sort_index()

print(f"Total dates in DB: {len(wide)}  (earliest: {wide.index[0].date()}, latest: {wide.index[-1].date()})")
print(f"Total symbols: {wide.shape[1]}")
print()

valid = wide.notna().rolling(SPAN, min_periods=SPAN).sum() >= SPAN
ema = wide.ewm(span=SPAN, adjust=False).mean()
sma = wide.rolling(SPAN, min_periods=SPAN).mean()

last_day = wide.index[-1]
valid_today = valid.loc[last_day]
n_valid = int(valid_today.sum())
print(f"Stocks with a full {SPAN}-day history as of {last_day.date()}: {n_valid} / {wide.shape[1]}")

price_today = wide.loc[last_day]
ema_today = ema.loc[last_day]
sma_today = sma.loc[last_day]

above_ema = (price_today > ema_today) & valid_today
above_sma = (price_today > sma_today) & valid_today

n_above_ema = int(above_ema.sum())
n_above_sma = int(above_sma.sum())
print(f"Above 200EMA: {n_above_ema} ({n_above_ema/n_valid*100:.2f}%)")
print(f"Above 200SMA: {n_above_sma} ({n_above_sma/n_valid*100:.2f}%)")
print()

# The stocks that disagree between the two metrics -- this is the group to inspect
flip_above_sma_only = valid_today & (price_today > sma_today) & ~(price_today > ema_today)
flip_above_ema_only = valid_today & (price_today > ema_today) & ~(price_today > sma_today)

print(f"Stocks above SMA but NOT above EMA (pulling SMA% up): {int(flip_above_sma_only.sum())}")
print(f"Stocks above EMA but NOT above SMA (pulling EMA% up): {int(flip_above_ema_only.sum())}")
print()

flip_symbols = wide.columns[flip_above_sma_only]
print(f"--- Sample of stocks above-SMA-only (first 15 of {len(flip_symbols)}) ---")
print(f"{'symbol':<12} {'price':>10} {'ema200':>10} {'sma200':>10} {'ema-sma gap':>12} {'hist_min':>10} {'hist_max':>10}")
for sym in flip_symbols[:15]:
    hist = wide[sym].tail(SPAN)
    print(f"{sym:<12} {price_today[sym]:>10.2f} {ema_today[sym]:>10.2f} {sma_today[sym]:>10.2f} "
          f"{ema_today[sym]-sma_today[sym]:>12.2f} {hist.min():>10.2f} {hist.max():>10.2f}")

print()
print("--- Distribution check: how many rows does each of these symbols actually have ---")
print("(if a symbol's total real row count is barely >= 200, it's right at the edge of")
print(" having 'enough' history -- worth knowing since it affects EMA warm-up)")
for sym in flip_symbols[:15]:
    real_rows = wide[sym].notna().sum()
    print(f"{sym:<12} total real rows: {real_rows}")
