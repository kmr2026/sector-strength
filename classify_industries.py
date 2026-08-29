"""
OPTIONAL / ADVANCED -- you probably don't need to run this.

By default, the "All Industries" tab uses fetch_data.py's
update_nifty500_industries(), which pulls a plain CSV (no bot-protection
issues) covering ~500 stocks across ~70+ finer industry categories. That
runs automatically and is the recommended path.

This script attempts the more ambitious version: classifying ALL ~2,700
NSE-listed stocks (not just 500) into NSE's full 197-category "Basic
Industry" tier, by querying their per-stock quote-equity API.

CONFIRMED ON LIVE TESTING: this API is behind Akamai's bot protection with
a JavaScript challenge (the `_abck` cookie mechanism) -- it blocked every
request with a 403, even using curl_cffi's browser-fingerprint
impersonation. Fingerprint spoofing isn't enough here; Akamai requires
actually executing their obfuscated JS, which no plain HTTP client can do.

The only reliable way past this would be genuine browser automation
(Playwright/Selenium) -- a much bigger, slower (hours, not minutes) and
still not-guaranteed build. Given the CSV-based path above already gets
you real, reliable coverage, this script is left in the project as a
documented dead-end rather than built out further. If you decide you want
the full 2,700-stock version badly enough to justify that cost, let me
know and I'll build the Playwright version -- but the CSV path is very
likely good enough for spotting sector strength.

USAGE (if you want to try anyway, e.g. NSE loosens this in the future):
    python classify_industries.py            # classify everything not yet done
    python classify_industries.py --limit 20  # just the first 20, for testing
    python classify_industries.py --debug AAPL # print raw response for one symbol
"""
import io
import sys
import time
import random
import datetime as dt
import pandas as pd

from config import EQUITY_MASTER_URL
from db import get_conn, init_db

try:
    from curl_cffi import requests as cffi_requests
    HAVE_CURL_CFFI = True
except ImportError:
    HAVE_CURL_CFFI = False
    import requests as plain_requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/get-quotes/equity",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive",
}

QUOTE_API = "https://www.nseindia.com/api/quote-equity"
EQUITY_PAGE = "https://www.nseindia.com/get-quotes/equity"

MIN_DELAY, MAX_DELAY = 0.6, 1.2


def make_session():
    """Returns a session using curl_cffi (browser-fingerprint impersonation,
    can get past Akamai) if installed, else a plain requests session
    (fuller headers, but Akamai may still block it)."""
    if HAVE_CURL_CFFI:
        s = cffi_requests.Session(impersonate="chrome124")
        s.headers.update(HEADERS)
    else:
        s = plain_requests.Session()
        s.headers.update(HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(0.5)
        # Visiting an actual equity quote page (not just the homepage)
        # gets you more specific cookies that the API endpoint checks for.
        s.get(f"{EQUITY_PAGE}?symbol=RELIANCE", timeout=10)
    except Exception:
        pass
    return s


def fetch_equity_master(session) -> pd.DataFrame:
    r = session.get(EQUITY_MASTER_URL, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    return df


def classify_one(session, symbol: str):
    """Returns {'macro','sector','industry','basic_industry','company_name'},
    'RETRY', or None."""
    try:
        r = session.get(QUOTE_API, params={"symbol": symbol}, timeout=15)
    except Exception:
        return None
    if r.status_code in (401, 403):
        return "RETRY"
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None

    info = data.get("industryInfo") or data.get("info", {}).get("industryInfo") or {}
    company_name = (data.get("info") or {}).get("companyName")

    basic_industry = info.get("basicIndustry") or info.get("basic_industry")
    if not basic_industry:
        return None

    return {
        "macro": info.get("macro"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "basic_industry": basic_industry.strip(),
        "company_name": company_name,
    }


def run(limit: int | None = None):
    init_db()
    session = make_session()
    with get_conn() as conn:
        master = fetch_equity_master(session)
        sym_col = next((c for c in master.columns if c.strip().upper() == "SYMBOL"), None)
        if not sym_col:
            print(f"[error] unexpected EQUITY_L.csv columns: {list(master.columns)}")
            return
        all_symbols = master[sym_col].dropna().astype(str).str.strip().tolist()

        already_done = {
            row[0] for row in conn.execute("SELECT symbol FROM basic_industry_map").fetchall()
        }
        todo = [s for s in all_symbols if s not in already_done]
        if limit:
            todo = todo[:limit]

        print(f"Total symbols: {len(all_symbols)}, already classified: {len(already_done)}, "
              f"remaining this run: {len(todo)}")

        done, failed, retried_sessions = 0, 0, 0
        for i, symbol in enumerate(todo, 1):
            result = classify_one(session, symbol)
            if result == "RETRY":
                session = make_session()
                retried_sessions += 1
                result = classify_one(session, symbol)

            if isinstance(result, dict):
                conn.execute(
                    """INSERT OR REPLACE INTO basic_industry_map
                       (symbol, macro, sector, industry, basic_industry, company_name, classified_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (symbol, result["macro"], result["sector"], result["industry"],
                     result["basic_industry"], result["company_name"], dt.datetime.now().isoformat()),
                )
                done += 1
            else:
                failed += 1

            if i % 50 == 0:
                conn.commit()
                print(f"  ...{i}/{len(todo)} processed ({done} ok, {failed} failed, "
                      f"{retried_sessions} session retries)")

            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    print(f"\nDone. Classified {done} symbols this run ({failed} failed/skipped).")
    print("Run again anytime to pick up any that failed -- already-done symbols are skipped.")


def debug_one(symbol: str):
    print(f"Using client: {'curl_cffi (chrome124 impersonation)' if HAVE_CURL_CFFI else 'plain requests (curl_cffi not installed -- pip install curl_cffi for better odds)'}")
    session = make_session()
    r = session.get(QUOTE_API, params={"symbol": symbol}, timeout=15)
    print(f"status: {r.status_code}")
    print(f"content-type: {r.headers.get('content-type')}")
    print(r.text[:3000])


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--debug" and len(args) > 1:
        debug_one(args[1])
    elif args and args[0] == "--limit" and len(args) > 1:
        run(limit=int(args[1]))
    else:
        run()
