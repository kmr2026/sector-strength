"""
Same test as before, but using curl_cffi instead of plain requests --
curl_cffi impersonates a real Chrome TLS/JA3 handshake, which is what
NSE's Akamai protection actually checks (plain `requests`, even with
perfect headers, still has a Python/OpenSSL TLS fingerprint underneath
that gets blocked).

Run locally:
    pip install curl_cffi pandas
    python test_corporate_actions_curlcffi.py
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

# impersonate="chrome" makes curl_cffi present a real Chrome TLS fingerprint
session = cf_requests.Session(impersonate="chrome")
session.headers.update(HEADERS)

print("Warming up session against homepage...")
home = session.get("https://www.nseindia.com", timeout=15)
print(f"  homepage status: {home.status_code}")
print(f"  cookies received: {list(session.cookies.keys())}\n")

if home.status_code != 200:
    print("Homepage still blocked even with curl_cffi -- something else is "
          "going on (maybe IP-based rate limiting, not just TLS fingerprint). "
          "Stop here and let's rethink.")
    raise SystemExit(1)

url = "https://www.nseindia.com/api/corporates-corporateActions"
params = {"index": "equities", "from_date": from_date, "to_date": to_date}

print(f"Requesting {url}")
print(f"  params: {params}\n")

resp = session.get(url, params=params, timeout=15)
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('Content-Type')}")

if resp.status_code != 200:
    print(f"First 300 chars of response: {resp.text[:300]!r}")
    raise SystemExit(1)

try:
    data = resp.json()
except Exception as e:
    print(f"Response wasn't valid JSON: {e}")
    print(f"First 300 chars: {resp.text[:300]!r}")
    raise SystemExit(1)

records = data if isinstance(data, list) else data.get("data", [])
print(f"\nGot {len(records)} records.\n")

if not records:
    print("Zero records -- either the date window isn't honored this far "
          "back, or the symbol/index filter is wrong. Try a 90-day window "
          "next to isolate which.")
    raise SystemExit(0)

df = pd.DataFrame(records)
print("Columns:", list(df.columns))
print()

date_col = next((c for c in df.columns if "date" in c.lower() or "dt" in c.lower()), None)
if date_col:
    parsed = pd.to_datetime(df[date_col], dayfirst=True, errors="coerce").dropna()
    if len(parsed):
        print(f"Earliest date ({date_col}): {parsed.min().date()}")
        print(f"Latest date ({date_col}):   {parsed.max().date()}")
        print(f"Span covered: {(parsed.max() - parsed.min()).days} days (asked for ~365)\n")

print("=== First 10 records ===")
print(df.head(10).to_string())

print("\n=== RELIANCE / TCS check ===")
sym_col = next((c for c in df.columns if c.lower() == "symbol"), None)
if sym_col:
    for sym in ["RELIANCE", "TCS"]:
        sub = df[df[sym_col] == sym]
        print(f"\n{sym}: {len(sub)} record(s)")
        if len(sub):
            print(sub.to_string())
