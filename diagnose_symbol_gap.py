"""
One-off diagnostic -- does NOT touch your database.
Run from the same folder as fetch_data.py:

    python diagnose_symbol_gap.py MTARTECH 2026-07-15

Checks whether NSE's raw bhavcopy file for that date actually contains a
row for that symbol, and if so, prints it raw -- so we can see whether
the row exists but fails to parse (a code bug) or genuinely isn't in
NSE's file that day (something on NSE's/the company's side).
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
    if len(sys.argv) < 3:
        print("Usage: python diagnose_symbol_gap.py SYMBOL YYYY-MM-DD")
        sys.exit(1)

    symbol = sys.argv[1].strip().upper()
    date = dt.date.fromisoformat(sys.argv[2])
    fname = f"sec_bhavdata_full_{date.strftime('%d%m%Y')}.csv"
    url = f"{NSE_BASE}/products/content/{fname}"

    session = requests.Session()
    session.headers.update(HEADERS)
    print(f"Fetching {url} ...")
    r = session.get(url, timeout=20)
    print(f"status={r.status_code}, len={len(r.text)}")
    if r.status_code != 200 or not r.text.strip():
        print("Couldn't fetch the file -- try a different date (check it's not a holiday).")
        return

    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    sym_col = next((c for c in df.columns if c.strip().upper() == "SYMBOL"), None)

    print(f"\nTotal rows in file: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    # Exact match
    exact = df[df[sym_col].astype(str).str.strip() == symbol]
    print(f"\nExact match for '{symbol}': {len(exact)} row(s)")
    if not exact.empty:
        print(exact.to_string(index=False))

    # Fuzzy match, in case of a trailing space, case difference, or renamed symbol
    fuzzy = df[df[sym_col].astype(str).str.strip().str.upper().str.contains(symbol[:5], na=False)]
    print(f"\nRows where symbol contains '{symbol[:5]}': {len(fuzzy)} row(s)")
    if not fuzzy.empty:
        print(fuzzy[[sym_col]].to_string(index=False))


if __name__ == "__main__":
    main()
