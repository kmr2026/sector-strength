"""
Follow-up to find_new_sector_indices.py: lists EVERY index name containing
"DEFENCE" in the same recent ind_close_all file, since the first search
found "NIFTY INDIA DEFENCE EQUAL WEIGHT" but the constituent URL that
worked (ind_niftyindiadefence_list.csv) doesn't mention "equal weight" --
there may be two separate Defence indices, and we need to pair the right
name with the right URL before adding this to config.py.

Run: python check_defence_variants.py
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

d = dt.date(2026, 8, 28)  # the date find_new_sector_indices.py already confirmed has data
fname = f"ind_close_all_{d.strftime('%d%m%Y')}.csv"
url = f"https://archives.nseindia.com/content/indices/{fname}"
r = session.get(url, timeout=15)
df = pd.read_csv(io.StringIO(r.text))
df.columns = [c.strip() for c in df.columns]
name_col = next((c for c in df.columns if "index" in c.lower() and "name" in c.lower()), None)
close_col = next((c for c in df.columns if c.strip().lower() == "closing index value"), None)

matches = df[df[name_col].astype(str).str.upper().str.contains("DEFENCE", na=False)]
print(f"All index names containing 'DEFENCE' in {fname}:\n")
for _, row in matches.iterrows():
    print(f"  '{row[name_col]}'  (close: {row[close_col] if close_col else '?'})")
