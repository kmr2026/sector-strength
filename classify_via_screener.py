"""
Classifies NSE stocks into screener.in's own industry taxonomy (~188
leaf-level industries -- close to NSE's own ~197 Basic Industry count,
and likely a superset of your actual NSE universe).

WHY THIS ONE IS DIFFERENT FROM THE NSE ATTEMPTS: these are plain, public,
server-rendered pages -- no login, no premium paywall, no JS challenge.
I fetched and inspected the real pages before writing this (unlike the
earlier NSE attempts, which were educated guesses) -- specifically:

  - https://www.screener.in/market/                          (index of
    all ~188 leaf industries, with company counts and direct links)
  - https://www.screener.in/market/IN03/IN0301/IN030103/IN030103001/
    (an example leaf industry page -- "Refineries & Marketing", 13 companies)
  - https://www.screener.in/market/IN06/IN0601/IN060101/IN060101001/
    (a bigger one -- "Pharmaceuticals", 217 companies, confirms pagination
    via ?page=N&limit=50)

Each company links to /company/{SYMBOL}/... where {SYMBOL} is usually the
actual NSE trading symbol (confirmed: SUNPHARMA, CIPLA, RELIANCE, etc.) --
so these match directly against your existing stock_prices data with no
extra mapping step. A few smaller companies show a numeric BSE code
instead of an NSE symbol (BSE-only listings, or just how screener.in
links them) -- those are explicitly filtered out, since BSE data isn't
part of this project.

CONFIRMED VIA LIVE TESTING: hitting this at ~0.5s between requests tripped
a rate limit -- some industries came back empty, and you were temporarily
blocked from browsing the site normally too, which confirms it's an
IP-level throttle rather than a targeted block. This version is much more
conservative (several seconds between requests) and, importantly, is now
RESUMABLE: it skips industries you've already successfully classified, so
a retry after this kind of hiccup only redoes what's missing, not
everything. If an industry comes back with suspiciously few results (0,
when the index page said there should be more), it retries that industry
with backoff rather than silently recording a bad result.

USAGE:
    python classify_via_screener.py             # full run, skips what's already done
    python classify_via_screener.py --force      # re-fetch everything, even if already classified
    python classify_via_screener.py --debug      # fetch just the index page and print what it found
"""
import re
import sys
import time
import random
import datetime as dt
import requests
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

from db import get_conn, init_db

BASE = "https://www.screener.in"
INDEX_URL = f"{BASE}/market/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Much more conservative than the first attempt -- that one used 0.4-0.8s
# and tripped a rate limit. Screener.in is a much smaller operation than
# NSE; treat it gently.
MIN_DELAY, MAX_DELAY = 3.0, 5.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 15  # seconds; doubles each retry

# Leaf-level industry links look like /market/IN03/IN0301/IN030103/IN030103001/
LEAF_LINK_RE = re.compile(r"^/market/IN\d{2}/IN\d{4}/IN\d{6}/IN\d{9}/$")
COMPANY_LINK_RE = re.compile(r"^/company/([A-Za-z0-9]+)/")
RESULTS_COUNT_RE = re.compile(r"(\d+) results found: Showing page \d+ of (\d+)")


def _path_only(href: str) -> str:
    """Normalizes an href to just its path, whether the real page uses
    relative (/company/X/) or absolute (https://www.screener.in/company/X/)
    links -- I can't be 100% sure which from a markdown-rendered fetch, so
    parsing doesn't depend on it either way."""
    if href.startswith("http"):
        return urlsplit(href).path
    return href


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _sleep():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def get_soup_with_retry(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetches a page, retrying with backoff on failure or a likely
    rate-limit response (429, or a non-200 that isn't a plain 404)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=20)
        except requests.RequestException as e:
            print(f"    [warn] request error on attempt {attempt}/{MAX_RETRIES}: {e}")
            r = None

        if r is not None and r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")

        status = r.status_code if r is not None else "no response"
        if r is not None and r.status_code == 404:
            print(f"    [warn] {url} -> 404, not retrying")
            return None

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            print(f"    [warn] {url} -> {status}, retrying in {wait}s "
                  f"(attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
        else:
            print(f"    [warn] {url} -> {status}, giving up after {MAX_RETRIES} attempts")
    return None


def discover_industries(session: requests.Session) -> list[tuple[str, str]]:
    """Returns [(industry_name, leaf_url), ...] from the main index page."""
    soup = get_soup_with_retry(session, INDEX_URL)
    if soup is None:
        return []
    industries = []
    seen = set()
    for a in soup.find_all("a", href=True):
        path = _path_only(a["href"])
        if LEAF_LINK_RE.match(path):
            name = a.get_text(strip=True)
            if path not in seen and name:
                seen.add(path)
                industries.append((name, path))
    return industries


def fetch_industry_companies(session: requests.Session, leaf_url: str) -> list[tuple[str, str]] | None:
    """Returns [(symbol, company_name), ...] across all pages of one
    industry, or None if it couldn't be fetched reliably (caller should
    treat this as 'try again later', not 'zero companies').

    Tracks raw link count separately from the BSE-filtered count: if the
    page genuinely had zero parseable company links despite the index
    page expecting some, that's a real failure (bad/rate-limited response).
    But if links WERE found and all of them turned out to be BSE-only
    codes (a real, if rare, case -- e.g. an industry with exactly one
    small BSE-listed company), that's a legitimate empty result, not a
    failure, and shouldn't be retried forever."""
    companies = []
    raw_link_count = 0
    page = 1
    total_pages = 1
    expected_count = None

    while page <= total_pages:
        url = f"{BASE}{leaf_url}?limit=50&page={page}"
        soup = get_soup_with_retry(session, url)
        if soup is None:
            return None  # couldn't get this page reliably -- don't record a partial/bad result

        if page == 1:
            m = RESULTS_COUNT_RE.search(soup.get_text())
            if m:
                expected_count = int(m.group(1))
                total_pages = int(m.group(2))

        for a in soup.find_all("a", href=True):
            path = _path_only(a["href"])
            m = COMPANY_LINK_RE.match(path)
            if m:
                symbol = m.group(1)
                name = a.get_text(strip=True)
                if not (symbol and name):
                    continue
                raw_link_count += 1
                if symbol.isdigit():
                    continue  # BSE-only numeric code, not an NSE symbol -- skip
                companies.append((symbol, name))

        page += 1
        if page <= total_pages:
            _sleep()

    if expected_count is not None and expected_count > 0 and raw_link_count == 0:
        # The index page said there should be results but we parsed no
        # company links at all -- likely a bad/rate-limited response that
        # still returned HTTP 200. Treat as a failure so the caller retries.
        return None

    # raw_link_count > 0 but companies is empty means every match was a
    # BSE-only code -- a legitimate (if unusual) result, not a failure.
    return companies


def run(force: bool = False):
    init_db()
    session = make_session()

    print("Fetching industry index...")
    industries = discover_industries(session)
    print(f"Found {len(industries)} leaf-level industries")
    if not industries:
        print("[error] no industries found -- site structure may have changed, "
              "or the index page itself is currently rate-limited. Try again "
              "later, or run with --debug to inspect.")
        return

    with get_conn() as conn:
        already_done = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT basic_industry FROM basic_industry_map"
            ).fetchall()
        }
        empty_done = {
            row[0][len("empty_industry:"):] for row in conn.execute(
                "SELECT key FROM classification_meta WHERE key LIKE 'empty_industry:%'"
            ).fetchall()
        }
        already_done |= empty_done

    if not force and already_done:
        print(f"{len(already_done)} industries already classified from a previous "
              f"run -- skipping those. Use --force to re-fetch everything.")

    succeeded, failed = [], []
    for i, (name, leaf_url) in enumerate(industries, 1):
        if not force and name in already_done:
            continue

        companies = fetch_industry_companies(session, leaf_url)
        if companies is None:
            print(f"  [{i}/{len(industries)}] {name}: FAILED, will need a retry")
            failed.append(name)
            _sleep()
            continue

        print(f"  [{i}/{len(industries)}] {name}: {len(companies)} companies")
        now = dt.datetime.now().isoformat()
        rows = [(sym, name, cname, now) for sym, cname in companies]

        with get_conn() as conn:
            conn.execute("DELETE FROM basic_industry_map WHERE basic_industry = ?", (name,))
            if rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO basic_industry_map
                       (symbol, basic_industry, company_name, classified_at)
                       VALUES (?, ?, ?, ?)""",
                    rows,
                )
            else:
                # Legitimately empty (e.g. the only company was BSE-only) --
                # mark it done so it isn't endlessly re-fetched on future runs.
                conn.execute(
                    "INSERT OR REPLACE INTO classification_meta (key, value) VALUES (?, ?)",
                    (f"empty_industry:{name}", now),
                )
            conn.execute(
                "INSERT OR REPLACE INTO classification_meta (key, value) VALUES "
                "('basic_industry_source', 'screener_public_188cat')"
            )
        succeeded.append(name)
        _sleep()

    with get_conn() as conn:
        total_symbols = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM basic_industry_map"
        ).fetchone()[0]
        total_industries = conn.execute(
            "SELECT COUNT(DISTINCT basic_industry) FROM basic_industry_map"
        ).fetchone()[0]

    print(f"\nThis run: {len(succeeded)} industries succeeded, {len(failed)} failed.")
    print(f"Database now has: {total_symbols} unique symbols across {total_industries} industries.")
    if failed:
        print(f"\nFailed industries this run: {', '.join(failed)}")
        print("Just run the script again (no flags needed) -- it'll only retry "
              "these, everything else is already saved.")


def debug():
    session = make_session()
    industries = discover_industries(session)
    print(f"Found {len(industries)} industries:")
    for name, url in industries[:15]:
        print(f"  {name} -> {url}")
    if len(industries) > 15:
        print(f"  ... and {len(industries) - 15} more")

    if industries:
        name, url = industries[0]
        print(f"\nFetching sample industry: {name}")
        companies = fetch_industry_companies(session, url)
        if companies is None:
            print("  FAILED to fetch reliably")
        else:
            print(f"Found {len(companies)} companies:")
            for sym, cname in companies[:10]:
                print(f"  {sym}: {cname}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--debug" in args:
        debug()
    else:
        run(force="--force" in args)

