"""
ONE-TIME classification of all ~2,700 NSE stocks into the full 197-category
Basic Industry tier -- using a REAL browser (Playwright) instead of a
plain HTTP client, since NSE's quote-equity API is behind Akamai bot
protection that requires actually executing their JS challenge (confirmed
via live testing: even curl_cffi's browser-fingerprint impersonation got
blocked -- spoofing the fingerprint isn't enough, Akamai checks that real
JS ran).

Playwright runs your REAL, already-installed Google Chrome (via
channel="chrome") rather than its own bundled Chromium build -- confirmed
via live testing that NSE's edge protection was fingerprinting and
resetting connections from Playwright's bundled Chromium specifically,
while your actual Chrome browser loads the site fine. Since it's the same
trusted browser binary you already browse with, it should carry the same
fingerprint. When it loads nseindia.com, it executes NSE's real JS,
legitimately solves any challenge, and gets valid cookies. We then call
the API via page.evaluate(), which runs fetch() INSIDE that real browser's
JS environment -- so from the site's side, it's indistinguishable from you
actually browsing.

SETUP (one-time):
    pip install playwright

    You need Google Chrome already installed on this machine (you do --
    Playwright will find and use it via channel="chrome"). If it can't
    find it, run: playwright install chrome

RUN THIS FIRST, before fetch_data.py's automatic fallback kicks in: once
this table has any rows, fetch_data.py will skip the lighter ~500-stock
CSV-based classification and leave this (better) data in place.

WHY THIS IS UNTESTED ON MY END: my sandbox can't run a real browser against
nseindia.com. This is the standard, architecturally correct approach for
Akamai-protected sites (real browser = real JS execution = legitimate
cookies), but I haven't verified it live. Two things worth trying if it
still doesn't work:
  1. Run with --headed to watch it work (a visible browser window) --
     some bot-detection setups are stricter on headless browsers
     specifically, and headed mode avoids that signal entirely.
  2. If it's still blocked, `pip install playwright-stealth` and let me
     know -- there's an extra patch to make Playwright's headless browser
     harder to fingerprint as automated, which I can wire in.

RESUMABLE: already-classified symbols are skipped, so if this gets
interrupted partway through, just run it again.

USAGE:
    python classify_industries_playwright.py             # classify everything not yet done
    python classify_industries_playwright.py --limit 20    # just the first 20, for testing
    python classify_industries_playwright.py --debug RELIANCE  # print result for one symbol
    python classify_industries_playwright.py --headed      # visible browser window
"""
import io
import sys
import time
import random
import datetime as dt
import requests
import pandas as pd
from playwright.sync_api import sync_playwright

from config import EQUITY_MASTER_URL
from db import get_conn, init_db

HOMEPAGE = "https://www.nseindia.com"
EQUITY_PAGE = "https://www.nseindia.com/get-quotes/equity"
QUOTE_API_PATH = "/api/quote-equity?symbol={symbol}"

MIN_DELAY, MAX_DELAY = 1.0, 2.0
RELOAD_EVERY = 200  # periodically reload the page to keep the session fresh

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_equity_master() -> list[str]:
    r = requests.get(EQUITY_MASTER_URL, timeout=20, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    sym_col = next((c for c in df.columns if c.strip().upper() == "SYMBOL"), None)
    if not sym_col:
        raise RuntimeError(f"unexpected EQUITY_L.csv columns: {list(df.columns)}")
    return df[sym_col].dropna().astype(str).str.strip().tolist()


def _raw_fetch(page, symbol: str):
    """Same fetch as classify_one, but returns the raw response untouched --
    including __status/__error -- so --debug can actually show what's
    happening instead of just 'None'."""
    js = """
        async (path) => {
            try {
                const res = await fetch(path, { headers: { "Accept": "application/json" } });
                const bodyText = await res.text();
                return { __httpStatus: res.status, __ok: res.ok, __bodyPreview: bodyText.slice(0, 1500) };
            } catch (e) {
                return { __error: String(e) };
            }
        }
    """
    return page.evaluate(js, QUOTE_API_PATH.format(symbol=symbol))


def classify_one(page, symbol: str):
    """Runs fetch() inside the real browser page -- inherits real cookies
    and JS environment, so this looks like genuine browsing to Akamai."""
    js = """
        async (path) => {
            try {
                const res = await fetch(path, { headers: { "Accept": "application/json" } });
                if (!res.ok) return { __status: res.status };
                return await res.json();
            } catch (e) {
                return { __error: String(e) };
            }
        }
    """
    try:
        data = page.evaluate(js, QUOTE_API_PATH.format(symbol=symbol))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("__status") or data.get("__error"):
        return None

    info = data.get("industryInfo") or (data.get("info") or {}).get("industryInfo") or {}
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


def _goto_with_retry(page, url: str, attempts: int = 3):
    """Some Akamai setups fingerprint the HTTP/2 connection itself and drop
    automated clients before any page content loads. We already launch
    Chromium with HTTP/2 disabled to sidestep that, but retry a couple of
    times in case of an unrelated transient network hiccup too."""
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            return
        except Exception as e:
            last_err = e
            print(f"  [warn] navigation attempt {attempt}/{attempts} failed: {e}")
            time.sleep(3)
    raise last_err


def run(limit: int | None = None, headed: bool = False):
    init_db()
    all_symbols = fetch_equity_master()
    with get_conn() as conn:
        already_done = {
            row[0] for row in conn.execute(
                "SELECT symbol FROM basic_industry_map WHERE sector IS NOT NULL"
            ).fetchall()
        }
    todo = [s for s in all_symbols if s not in already_done]
    if limit:
        todo = todo[:limit]
    print(f"Total symbols: {len(all_symbols)}, already classified: {len(already_done)}, "
          f"remaining this run: {len(todo)}")
    if not todo:
        print("Nothing to do.")
        return

    with sync_playwright() as p:
        # Using channel="chrome" drives your actual installed Google Chrome
        # rather than Playwright's own bundled Chromium build. The bundled
        # one has a distinguishable connection fingerprint that NSE's edge
        # protection appears to specifically flag (confirmed: your real
        # Chrome loads the site fine, Playwright's bundled Chromium was
        # getting its connection reset). Real Chrome should carry the same
        # trusted fingerprint your browser already has.
        browser = p.chromium.launch(
            channel="chrome",
            headless=not headed,
            args=["--disable-http2"],
        )
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        print("Loading nseindia.com to establish a real browser session...")
        _goto_with_retry(page, HOMEPAGE)
        time.sleep(2)  # let any background JS challenge settle

        done, failed = 0, 0
        with get_conn() as conn:
            for i, symbol in enumerate(todo, 1):
                if i > 1 and i % RELOAD_EVERY == 0:
                    _goto_with_retry(page, HOMEPAGE)
                    time.sleep(1)

                result = classify_one(page, symbol)
                if isinstance(result, dict):
                    conn.execute(
                        """INSERT INTO basic_industry_map
                           (symbol, macro, sector, industry, basic_industry, company_name, classified_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(symbol) DO UPDATE SET
                             macro=excluded.macro,
                             sector=excluded.sector,
                             industry=excluded.industry,
                             basic_industry=excluded.basic_industry,
                             company_name=excluded.company_name,
                             classified_at=excluded.classified_at""",
                        (symbol, result["macro"], result["sector"], result["industry"],
                         result["basic_industry"], result["company_name"], dt.datetime.now().isoformat()),
                    )
                    done += 1
                else:
                    failed += 1

                if i % 50 == 0:
                    conn.commit()
                    print(f"  ...{i}/{len(todo)} processed ({done} ok, {failed} failed)")

                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            if done > 0:
                conn.execute(
                    "INSERT OR REPLACE INTO classification_meta (key, value) VALUES ('basic_industry_source', 'playwright_full_197cat')"
                )
                conn.commit()

        browser.close()

    print(f"\nDone. Classified {done} symbols this run ({failed} failed/skipped).")
    print("Run again anytime to pick up any that failed -- already-done symbols are skipped.")


def debug_one(symbol: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-http2"])
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        print("--- Attempt 1: fetch from homepage session ---")
        print("Loading nseindia.com...")
        _goto_with_retry(page, HOMEPAGE)
        time.sleep(2)
        print(f"Fetching {QUOTE_API_PATH.format(symbol=symbol)} from within the browser...")
        print(_raw_fetch(page, symbol))

        print(f"\n--- Attempt 2: fetch after visiting the actual quote page for {symbol} ---")
        quote_page_url = f"{EQUITY_PAGE}?symbol={symbol}"
        print(f"Loading {quote_page_url} ...")
        _goto_with_retry(page, quote_page_url)
        time.sleep(2)
        print(f"Fetching {QUOTE_API_PATH.format(symbol=symbol)} again...")
        print(_raw_fetch(page, symbol))

        browser.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    headed = "--headed" in args
    if "--debug" in args:
        idx = args.index("--debug")
        debug_one(args[idx + 1])
    elif "--limit" in args:
        idx = args.index("--limit")
        run(limit=int(args[idx + 1]), headed=headed)
    else:
        run(headed=headed)
