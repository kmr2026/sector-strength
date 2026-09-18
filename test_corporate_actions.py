"""
One-off test: confirm india-corp-actions can pull a full YEAR of PAST
corporate actions from NSE (not just upcoming ones -- its default window
is 90 days forward, built for a "what's coming up" calendar, and it's
untested whether NSE's live API will actually serve a year of history
if we just push from_date back).

Run locally (needs your real internet access, not this sandbox):
    pip install india-corp-actions
    python test_corporate_actions.py

Prints:
  - How many records came back for a 1-year lookback
  - The actual earliest/latest ex-dates in the response (to see if NSE
    is silently truncating the window rather than erroring)
  - A few sample records, so we can see the field names/shapes for real
  - Specifically checks for RELIANCE and TCS, which both had known
    splits/bonuses in recent years -- if those show up correctly, that's
    a strong real-world sanity check
"""
from datetime import datetime, timedelta
from india_corp_actions import IndiaCorpActions

client = IndiaCorpActions()

today = datetime.today()
one_year_ago = today - timedelta(days=365)

from_date = one_year_ago.strftime("%d-%m-%Y")
to_date = today.strftime("%d-%m-%Y")

print(f"Requesting corporate actions from {from_date} to {to_date} ...\n")

try:
    df = client.get_actions_df(from_date=from_date, to_date=to_date, source="NSE")
except Exception as e:
    print(f"FAILED with exception: {e}")
    raise SystemExit(1)

if df is None or len(df) == 0:
    print("Got ZERO records back. Either the window isn't supported going "
          "this far back, or something else broke. Try shrinking the "
          "window (e.g. 90 days) to see if that at least works.")
    raise SystemExit(0)

print(f"Got {len(df)} total records.\n")
print("Columns:", list(df.columns))
print()

if "ex_date" in df.columns:
    date_col = "ex_date"
elif "exDate" in df.columns:
    date_col = "exDate"
else:
    date_col = [c for c in df.columns if "date" in c.lower()][0]

parsed_dates = pd = __import__("pandas").to_datetime(df[date_col], dayfirst=True, errors="coerce").dropna()
if len(parsed_dates):
    print(f"Earliest ex-date in response: {parsed_dates.min().date()}")
    print(f"Latest ex-date in response:   {parsed_dates.max().date()}")
    span_days = (parsed_dates.max() - parsed_dates.min()).days
    print(f"Actual span covered: {span_days} days (we asked for ~365)\n")
else:
    print("Couldn't parse any dates from the date column -- check raw output below.\n")

print("=== First 10 records (raw) ===")
print(df.head(10).to_string())
print()

print("=== Checking known splits/bonuses for RELIANCE and TCS ===")
for sym in ["RELIANCE", "TCS"]:
    sub = df[df.get("symbol", df.get("Symbol", "")) == sym] if "symbol" in df.columns or "Symbol" in df.columns else df[df.astype(str).apply(lambda r: sym in r.values, axis=1)]
    print(f"\n{sym}: {len(sub)} record(s) found")
    if len(sub):
        print(sub.to_string())

print("\n=== Bonus/split-specific filter ===")
try:
    splits_df = client.get_splits()
    bonus_df = client.get_bonus()
    print(f"get_splits() [upcoming only, default window]: {len(splits_df)} records")
    print(f"get_bonus() [upcoming only, default window]: {len(bonus_df)} records")
    print("(these use the package's default forward-looking window -- just "
          "confirming the type-filtering methods work at all)")
except Exception as e:
    print(f"get_splits()/get_bonus() failed: {e}")
