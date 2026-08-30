"""
audit_listing_status.py
------------------------
Purpose: figure out, for every symbol in your basic_industry_map table,
whether it's genuinely missing from your price data because it's not a
normal NSE mainboard stock (BSE-only, SME board, trade-to-trade / BE-BZ
series, illiquid) -- or whether it SHOULD have price data and your
fetch pipeline just missed it (a real bug).

Run this on your own machine (not in a sandbox) since it needs to reach
nseindia.com, which blocks non-browser-like requests without a proper
session/headers.

Usage:
    pip install requests

    # Option A: let the script fetch the lists itself (works most of the time,
    # but NSE's bot-detection sometimes blocks scripted requests with a 403):
    python audit_listing_status.py --db sector_strength.db

    # Option B (more reliable): download the two files yourself in your
    # browser first, then point the script at the local files --
    #   https://www.nseindia.com/market-data/securities-available-for-trading
    #   -> click "Securities available for Equity segment (.csv)"
    #   -> click "Securities available for trading in SME (.csv)"
    python audit_listing_status.py --db sector_strength.db ^
        --equity-csv EQUITY_L.csv --sme-csv SME_EQUITY_L.csv

Output:
    1. A new table `listing_audit` written into your sqlite db, with one
       row per classified symbol.
    2. A console summary of counts by category.
    3. A CSV file `pipeline_bugs.csv` listing ONLY the symbols that are
       confirmed NSE mainboard (EQ/BE/BZ) but have zero price rows --
       these are your real pipeline misses, ordered by industry.
"""

import argparse
import csv
import io
import sqlite3
import sys
import time

import requests

NSE_HOME = "https://www.nseindia.com"
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SME_EQUITY_L_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


FULL_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def get_nse_session() -> requests.Session:
    """NSE blocks bare requests; you first need to hit the homepage to
    pick up cookies, then the archive endpoints will usually respond
    normally. This sometimes still gets a 403 depending on IP/network --
    if so, use --equity-csv / --sme-csv with manually downloaded files
    instead (see the usage note at the top of this file)."""
    s = requests.Session()
    s.headers.update(FULL_BROWSER_HEADERS)
    resp = s.get(NSE_HOME, timeout=15)
    resp.raise_for_status()
    time.sleep(1)
    # a second, lighter hit warms up additional cookies some endpoints check
    s.get(f"{NSE_HOME}/market-data/securities-available-for-trading", timeout=15)
    time.sleep(1)
    return s


def parse_csv_text(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    # NSE csv headers have leading spaces, e.g. " SERIES" -- normalize them
    rows = []
    for row in reader:
        rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return rows


def fetch_csv(session: requests.Session, url: str) -> list[dict]:
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    return parse_csv_text(resp.text)


def load_local_csv(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return parse_csv_text(f.read())


def build_mainboard_lookup(rows: list[dict]) -> dict:
    """symbol -> series (EQ, BE, BZ, BT, etc.)"""
    lookup = {}
    for row in rows:
        sym = row.get("SYMBOL")
        series = row.get("SERIES")
        if sym:
            lookup[sym] = series
    return lookup


def build_sme_lookup(rows: list[dict]) -> set:
    """SME csv column name for symbol can vary; try common variants."""
    symbols = set()
    if not rows:
        return symbols
    sample = rows[0]
    sym_col = None
    for candidate in ("SYMBOL", "Symbol", "SME SYMBOL"):
        if candidate in sample:
            sym_col = candidate
            break
    if sym_col is None:
        # fall back to first column
        sym_col = list(sample.keys())[0]
    for row in rows:
        v = row.get(sym_col)
        if v:
            symbols.add(v.strip())
    return symbols


def classify(symbol: str, mainboard: dict, sme: set) -> str:
    if symbol in mainboard:
        series = mainboard[symbol]
        return f"NSE_{series}"  # e.g. NSE_EQ, NSE_BE, NSE_BZ
    if symbol in sme:
        return "NSE_SME"
    return "NOT_ON_NSE"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="sector_strength.db", help="path to sector_strength.db")
    parser.add_argument("--equity-csv", default=None,
                         help="path to a manually downloaded EQUITY_L.csv (bypasses live fetch)")
    parser.add_argument("--sme-csv", default=None,
                         help="path to a manually downloaded SME_EQUITY_L.csv (bypasses live fetch)")
    args = parser.parse_args()

    if args.equity_csv:
        print(f"Loading mainboard list from local file: {args.equity_csv}")
        mainboard_rows = load_local_csv(args.equity_csv)
        print(f"  {len(mainboard_rows)} rows")
        sme_rows = []
        if args.sme_csv:
            print(f"Loading SME list from local file: {args.sme_csv}")
            sme_rows = load_local_csv(args.sme_csv)
            print(f"  {len(sme_rows)} rows")
        else:
            print("  No --sme-csv given, continuing without SME classification.")
    else:
        print("Connecting to NSE and downloading official lists...")
        try:
            session = get_nse_session()
            mainboard_rows = fetch_csv(session, EQUITY_L_URL)
            print(f"  Mainboard EQUITY_L.csv: {len(mainboard_rows)} rows")
        except requests.HTTPError as e:
            print(f"\nLive fetch failed ({e}).")
            print("NSE is blocking scripted requests from this network/IP.")
            print("Download the files yourself instead:")
            print("  https://www.nseindia.com/market-data/securities-available-for-trading")
            print("  -> 'Securities available for Equity segment (.csv)'")
            print("  -> 'Securities available for trading in SME (.csv)'")
            print("Then re-run with: --equity-csv EQUITY_L.csv --sme-csv SME_EQUITY_L.csv")
            sys.exit(1)
        try:
            sme_rows = fetch_csv(session, SME_EQUITY_L_URL)
            print(f"  SME_EQUITY_L.csv: {len(sme_rows)} rows")
        except requests.HTTPError:
            print("  Could not fetch SME list, continuing without it.")
            sme_rows = []

    mainboard = build_mainboard_lookup(mainboard_rows)
    sme = build_sme_lookup(sme_rows)

    print(f"\nOpening {args.db} ...")
    con = sqlite3.connect(args.db)
    cur = con.cursor()

    cur.execute("SELECT symbol, basic_industry FROM basic_industry_map")
    classified = cur.fetchall()

    cur.execute("SELECT symbol, COUNT(*), MAX(date) FROM stock_prices GROUP BY symbol")
    price_info = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    print(f"Classifying {len(classified)} symbols...")

    cur.execute("DROP TABLE IF EXISTS listing_audit")
    cur.execute(
        """
        CREATE TABLE listing_audit (
            symbol TEXT PRIMARY KEY,
            basic_industry TEXT,
            listing_status TEXT,
            price_rows INTEGER,
            last_price_date TEXT,
            flag TEXT
        )
        """
    )

    counts = {}
    bugs = []

    for symbol, industry in classified:
        status = classify(symbol, mainboard, sme)
        rows_count, last_date = price_info.get(symbol, (0, None))
        has_data = rows_count > 0

        if status.startswith("NSE_EQ") and not has_data:
            flag = "BUG_LIKELY_MISSED_FETCH"
            bugs.append((symbol, industry, status))
        elif status.startswith(("NSE_BE", "NSE_BZ")) and not has_data:
            flag = "RESTRICTED_SERIES_NO_DATA"  # trade-to-trade / stressed, plausibly thin
        elif status == "NSE_SME" and not has_data:
            flag = "SME_NEEDS_SEPARATE_FEED"
        elif status == "NOT_ON_NSE":
            flag = "NOT_NSE_TRADEABLE"
        elif has_data and rows_count < 30:
            flag = "SPARSE_DATA_CHECK_LIQUIDITY"
        else:
            flag = "OK"

        counts[flag] = counts.get(flag, 0) + 1

        cur.execute(
            "INSERT INTO listing_audit VALUES (?, ?, ?, ?, ?, ?)",
            (symbol, industry, status, rows_count, last_date, flag),
        )

    con.commit()

    print("\n=== Summary ===")
    for flag, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {flag:30s} {n}")

    if bugs:
        with open("pipeline_bugs.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["symbol", "basic_industry", "nse_series"])
            for row in sorted(bugs, key=lambda r: r[1]):
                writer.writerow(row)
        print(f"\n{len(bugs)} symbols are confirmed NSE mainboard (EQ series) but have "
              f"ZERO rows in stock_prices -- these are real pipeline misses.")
        print("Written to pipeline_bugs.csv -- re-run your price fetch for exactly this list.")
    else:
        print("\nNo EQ-series symbols found with zero price data -- no pipeline bugs detected.")

    print(f"\nFull per-symbol classification saved to table 'listing_audit' in {args.db}.")
    print("Use this table to (a) fix the fetch pipeline for BUG_LIKELY_MISSED_FETCH symbols,")
    print("(b) exclude NOT_NSE_TRADEABLE / NSE_SME from breadth calcs (or fetch SME separately),")
    print("and (c) show the correct 'X of Y NSE-tradeable stocks' count in your popup UI.")

    con.close()


if __name__ == "__main__":
    main()
