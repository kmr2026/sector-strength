"""
One-off diagnostic -- does NOT touch your database.
Run from the same folder as fetch_data.py:

    python check_bhavcopy_breakdown.py 2026-09-01

Shows how many rows fall under each SERIES code, and how many UNIQUE
symbols actually exist under EQ+BE (the real tradeable-equity count your
scanner cares about) -- vs. the raw row count, which includes government
securities, other series, and repeat rows for the same company.
"""
import sys
import datetime as dt
import requests
import io
import pandas as pd

from config import NSE_BASE

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_bhavcopy_breakdown.py YYYY-MM-DD")
        sys.exit(1)

    date = dt.date.fromisoformat(sys.argv[1])
    fname = f"sec_bhavdata_full_{date.strftime('%d%m%Y')}.csv"
    url = f"{NSE_BASE}/products/content/{fname}"

    session = requests.Session()
    session.headers.update(HEADERS)
    r = session.get(url, timeout=20)
    if r.status_code != 200 or not r.text.strip():
        print(f"Couldn't fetch: status={r.status_code}")
        return

    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    sym_col = next((c for c in df.columns if c.strip().upper() == "SYMBOL"), None)
    series_col = next((c for c in df.columns if c.strip().upper() == "SERIES"), None)
    df[series_col] = df[series_col].astype(str).str.strip()
    df[sym_col] = df[sym_col].astype(str).str.strip()

    print(f"Total rows: {len(df)}")
    print(f"Total UNIQUE symbols (any series): {df[sym_col].nunique()}")
    print()
    print("Rows per series:")
    print(df[series_col].value_counts().to_string())
    print()

    eq_be = df[df[series_col].isin(["EQ", "BE"])]
    print(f"Rows under EQ or BE: {len(eq_be)}")
    print(f"UNIQUE symbols under EQ or BE: {eq_be[sym_col].nunique()}")
    dupes = eq_be[sym_col].value_counts()
    dupes = dupes[dupes > 1]
    print(f"Symbols appearing more than once under EQ/BE combined (shouldn't normally happen, worth checking if >0): {len(dupes)}")
    if len(dupes):
        print(dupes.head(10).to_string())


if __name__ == "__main__":
    main()
