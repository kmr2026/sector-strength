"""
Follow-up to test_corporate_actions_curlcffi.py -- same fetch, but
filtered to ONLY bonus/split rows, so we can see NSE's real subject-line
wording before writing ratio-extraction logic.

Run locally (same folder, after the previous test already worked):
    python find_split_bonus_examples.py
"""
from datetime import datetime, timedelta
from curl_cffi import requests as cf_requests
import pandas as pd

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

today = datetime.today()
one_year_ago = today - timedelta(days=365)
from_date = one_year_ago.strftime("%d-%m-%Y")
to_date = today.strftime("%d-%m-%Y")

session = cf_requests.Session(impersonate="chrome")
session.headers.update(HEADERS)
session.get("https://www.nseindia.com", timeout=15)

url = "https://www.nseindia.com/api/corporates-corporateActions"
params = {"index": "equities", "from_date": from_date, "to_date": to_date}
resp = session.get(url, params=params, timeout=15)
records = resp.json()
records = records if isinstance(records, list) else records.get("data", [])
df = pd.DataFrame(records)

print(f"Total records: {len(df)}\n")

mask_bonus = df["subject"].str.contains("bonus", case=False, na=False)
mask_split = df["subject"].str.contains(
    "split|sub-division|subdivision", case=False, na=False, regex=True
)

print(f"=== BONUS rows ({mask_bonus.sum()}) ===")
for _, row in df[mask_bonus][["symbol", "comp", "exDate", "subject"]].iterrows():
    print(f"  {row['symbol']:<15} {row['exDate']:<12} {row['subject']}")

print(f"\n=== SPLIT rows ({mask_split.sum()}) ===")
for _, row in df[mask_split][["symbol", "comp", "exDate", "subject"]].iterrows():
    print(f"  {row['symbol']:<15} {row['exDate']:<12} {row['subject']}")

print(f"\n=== Unique subject PATTERNS for bonus (first word variations) ===")
print(df[mask_bonus]["subject"].unique()[:20])

print(f"\n=== Unique subject PATTERNS for split (first word variations) ===")
print(df[mask_split]["subject"].unique()[:20])
