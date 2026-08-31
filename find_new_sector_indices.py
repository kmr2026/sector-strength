"""
One-off helper: find the correct index names (as they appear in NSE's
daily ind_close_all_DDMMYYYY.csv) and constituent list URLs for the 6 new
sectors, all in one run -- same verify-before-adding approach that fixed
Telecom, just batched instead of one-by-one.

Run: python find_new_sector_indices.py
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

# --- Part 1: find exact index names in a recent ind_close_all file -------
KEYWORDS = {
    "Cement": "CEMENT",
    "Capital Goods": "CAPITAL GOODS",
    "Defence": "DEFENCE",
    "Power": "POWER",
    "NBFC": "NBFC",
    "Insurance": "INSURANCE",
}

print("=== Searching a recent ind_close_all file for all 6 index names ===")
found = {}
d = dt.date.today()
checked = 0
while checked < 10 and len(found) < len(KEYWORDS):
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
    all_names = df[name_col].astype(str).str.upper().tolist()
    for label, kw in KEYWORDS.items():
        if label in found:
            continue
        matches = [n for n in all_names if kw in n]
        if matches:
            found[label] = matches[0]
            print(f"  {label}: FOUND '{matches[0]}' (in {fname})")

for label in KEYWORDS:
    if label not in found:
        print(f"  {label}: NOT FOUND in last {checked} trading days")

# --- Part 2: test candidate constituent URLs for each ---------------------
print("\n=== Testing candidate constituent list URLs ===")

CANDIDATES = {
    "Cement": [
        "https://archives.nseindia.com/content/indices/ind_niftycementlist.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftycement_list.csv",
    ],
    "Capital Goods": [
        "https://archives.nseindia.com/content/indices/ind_niftycapitalgoodslist.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftycapitalgoods_list.csv",
    ],
    "Defence": [
        "https://www.niftyindices.com/IndexConstituent/ind_niftyindiadefence_list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftyindefence_list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftydefence_list.csv",
        "https://archives.nseindia.com/content/indices/ind_niftyindiadefencelist.csv",
    ],
    "Power": [
        "https://archives.nseindia.com/content/indices/ind_niftypowerlist.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftypower_list.csv",
    ],
    "NBFC": [
        "https://archives.nseindia.com/content/indices/ind_niftynbfclist.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftynbfc_list.csv",
    ],
    "Insurance": [
        "https://archives.nseindia.com/content/indices/ind_niftyinsurancelist.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftyinsurance_list.csv",
    ],
}

for label, urls in CANDIDATES.items():
    print(f"\n{label}:")
    for url in urls:
        r = session.get(url, timeout=15)
        mark = "OK" if r.status_code == 200 and "SYMBOL" in r.text.upper() else str(r.status_code)
        print(f"  [{mark}] {url}")

print("\nDone. Send me the FOUND index names and which URL(s) showed [OK] for each.")
