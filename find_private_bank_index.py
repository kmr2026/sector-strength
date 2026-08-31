"""
One-off helper: find the correct NIFTY PRIVATE BANK index name (as it
appears in NSE's daily ind_close_all_DDMMYYYY.csv) and the correct
constituent list URL, before adding it to config.py.

Run: python find_private_bank_index.py
"""
import io
import datetime as dt
import requests
import pandas as pd

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

session = requests.Session()
session.headers.update(HEADERS)
session.get("https://www.nseindia.com", timeout=10)

print("=== Searching recent ind_close_all files for 'PRIVATE BANK' ===")
found_names = set()
d = dt.date.today()
checked = 0
while checked < 10:
    d -= dt.timedelta(days=1)
    if d.weekday() >= 5:
        continue
    checked += 1
    fname = f"ind_close_all_{d.strftime('%d%m%Y')}.csv"
    url = f"https://archives.nseindia.com/content/indices/{fname}"
    r = session.get(url, timeout=15)
    if r.status_code != 200 or not r.text.strip():
        continue
    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        continue
    df.columns = [c.strip() for c in df.columns]
    name_col = next((c for c in df.columns if "index" in c.lower() and "name" in c.lower()), None)
    if not name_col:
        continue
    matches = df[df[name_col].astype(str).str.upper().str.contains("PRIVATE BANK", na=False)]
    if not matches.empty:
        for n in matches[name_col].tolist():
            found_names.add(n)
        print(f"  FOUND in {fname}: {sorted(found_names)}")
        break
    else:
        print(f"  {fname}: no match")

if not found_names:
    print("  No match found in the last 10 trading days.")

print("\n=== Testing candidate constituent list URLs ===")
candidates = [
    "https://archives.nseindia.com/content/indices/ind_niftyprivatebanklist.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_niftyprivatebank_list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty_privatebank_list.csv",
]
for url in candidates:
    r = session.get(url, timeout=15)
    mark = "OK" if r.status_code == 200 and "SYMBOL" in r.text.upper() else str(r.status_code)
    print(f"  [{mark}] {url}")

print("\nDone. Send me the FOUND index name(s) and which URL(s) showed [OK].")
