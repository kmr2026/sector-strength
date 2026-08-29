"""
One-off check: confirm the Nifty Total Market constituent file works and
show what Industry labels it actually uses, so we can map them to our
sector buckets correctly.

Run: python inspect_total_market.py
"""
import io
import requests
import pandas as pd

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

URL = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"

session = requests.Session()
session.headers.update(HEADERS)
session.get("https://www.nseindia.com", timeout=10)

r = session.get(URL, timeout=20)
print(f"status: {r.status_code}, bytes: {len(r.content)}")

if r.status_code == 200:
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    print("\ncolumns:", list(df.columns))
    print(f"\ntotal rows: {len(df)}")
    industry_col = next((c for c in df.columns if "industry" in c.lower()), None)
    if industry_col:
        print(f"\nunique values in '{industry_col}' ({df[industry_col].nunique()}):")
        for val, count in df[industry_col].value_counts().items():
            print(f"  {val}: {count}")
    else:
        print("\n[warn] no Industry column found -- check column names above")
