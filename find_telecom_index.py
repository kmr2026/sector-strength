"""
One-off helper: find the correct NIFTY TELECOM(MUNICATIONS) index name (as
it appears in NSE's daily ind_close_all_DDMMYYYY.csv) and the correct
constituent list URL -- config.py currently has a placeholder guess for
both that's confirmed wrong (Telecom's EMA/RS show unavailable because no
index price data matches).

Run: python find_telecom_index.py
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

# --- Part 1: find the exact index name string in a recent ind_close_all file ---
print("=== Searching recent ind_close_all files for any 'TELECOM' index name ===")
found_name = None
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
    matches = df[df[name_col].astype(str).str.upper().str.contains("TELECOM", na=False)]
    if not matches.empty:
        found_name = matches[name_col].iloc[0]
        print(f"  FOUND in {fname}: '{found_name}'")
        break
    else:
        print(f"  {fname}: no TELECOM match")

if not found_name:
    print("  No match found in the last 10 trading days. The index may not "
          "be included in this daily file, or uses a name I'm not matching -- "
          "check the file manually if this comes up empty.")

# --- Part 2: find the correct constituent list URL ---
print("\n=== Testing candidate constituent list URLs ===")
candidates = [
    "https://www.niftyindices.com/IndexConstituent/ind_niftytelecom_list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_niftytelecommunication_list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_niftytelecommunications_list.csv",
    "https://archives.nseindia.com/content/indices/ind_niftytelecomlist.csv",
    "https://archives.nseindia.com/content/indices/ind_niftytelecommunicationslist.csv",
]
for url in candidates:
    r = session.get(url, timeout=15)
    mark = "OK" if r.status_code == 200 and "SYMBOL" in r.text.upper() else str(r.status_code)
    print(f"  [{mark}] {url}")

print("\nDone. Send me the FOUND index name (if any) and which URL(s) showed [OK].")
