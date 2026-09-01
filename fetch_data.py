"""
Pulls daily data from NSE's public archives and stores it in SQLite.

Run this once a day after market close (e.g. via Windows Task Scheduler,
same pattern as your NSEBand pipeline).

NSE quirks handled here:
  - archives.nseindia.com wants a browser-like User-Agent, or it 403s.
  - You generally need to hit the homepage first to pick up cookies before
    the archive endpoints will serve you.
  - Weekends/holidays have no file -> we just skip those dates quietly.

NOTE: NSE occasionally renames/moves these files. If a sector's constituent
list starts 404ing, check config.py -> SECTORS and update the filename.
"""
import io
import time
import datetime as dt
import requests
import pandas as pd

from config import NSE_BASE, SECTORS, INDEX_HISTORY_DAYS, STOCK_HISTORY_DAYS, TOTAL_MARKET_URL, NIFTY500_INDUSTRY_URL, MIDSMALL_INDEX
from db import get_conn, init_db

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    # NOTE: no longer priming via www.nseindia.com's homepage first. Live
    # testing showed archives.nseindia.com issues its own _abck/bm_sz
    # cookies on the very first request and works fine unprimed -- while
    # the homepage is on the much more aggressively Akamai-protected main
    # site, and if THAT request gets soft-blocked/challenged, the
    # resulting cookie rides along on every later archives request in
    # this session and can get them silently rejected too, even though a
    # fresh unprimed request would have worked. If this ever needs
    # priming again, prime against archives.nseindia.com itself, not
    # www.nseindia.com.
    return s


def trading_days_back(n: int):
    """Yield the last n calendar days (we filter out weekends; NSE holidays
    just come back as failed downloads and get skipped)."""
    d = dt.date.today()
    days = []
    while len(days) < n:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d -= dt.timedelta(days=1)
    return days


def _fetch_csv(session: requests.Session, url: str, timeout: int, label: str) -> pd.DataFrame | None:
    """Shared fetch+parse with a visible reason on failure -- previously
    fetch_index_file/fetch_bhavcopy returned None on ANY failure (bad
    status, empty body, bad parse) and the caller just counted it as
    'missed', with no way to tell a genuine holiday apart from a block or
    a schema change. Now prints exactly which one it was."""
    try:
        r = session.get(url, timeout=timeout)
    except requests.RequestException as e:
        print(f"  [miss] {label}: request failed -- {e}")
        return None
    if r.status_code != 200:
        preview = (r.text or "")[:150].replace("\n", " ")
        print(f"  [miss] {label}: status={r.status_code}, preview={preview!r}")
        return None
    if not r.text.strip():
        print(f"  [miss] {label}: status=200 but empty body (likely a holiday)")
        return None
    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        preview = r.text[:150].replace("\n", " ")
        print(f"  [miss] {label}: status=200 but couldn't parse as CSV -- {e} -- preview={preview!r}")
        return None
    df.columns = [c.strip() for c in df.columns]
    return df


def fetch_index_file(session: requests.Session, date: dt.date) -> pd.DataFrame | None:
    fname = f"ind_close_all_{date.strftime('%d%m%Y')}.csv"
    url = f"{NSE_BASE}/content/indices/{fname}"
    return _fetch_csv(session, url, timeout=15, label=f"index {date.isoformat()}")


def fetch_bhavcopy(session: requests.Session, date: dt.date) -> pd.DataFrame | None:
    fname = f"sec_bhavdata_full_{date.strftime('%d%m%Y')}.csv"
    url = f"{NSE_BASE}/products/content/{fname}"
    return _fetch_csv(session, url, timeout=20, label=f"bhavcopy {date.isoformat()}")


def fetch_constituents(session: requests.Session, list_url: str) -> list[str]:
    r = session.get(list_url, timeout=15)
    if r.status_code != 200:
        print(f"  [warn] constituent list not found: {list_url} ({r.status_code})")
        return []
    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return []
    symbol_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    if not symbol_col:
        return []
    return df[symbol_col].dropna().astype(str).str.strip().tolist()


def update_constituents(force: bool = False):
    """Fetches each sector's constituent list -- but only for sectors that
    don't already have one, unless force=True. Per-sector check, not a
    single global 'does the table have any rows' flag: that global-flag
    version was a real bug (found via live testing) -- once your first
    sectors populated this table, the whole function stopped running
    forever, silently starving any NEW sector added to config.py later of
    its constituent list (breadth/stock-detail then show empty for that
    sector, even though its index-level price data backfills fine). Same
    fix pattern as the index_prices brand-new-index backfill above."""
    print("Refreshing sector constituent lists...")
    session = make_session()
    with get_conn() as conn:
        for sector_name, (_, list_url) in SECTORS.items():
            if not force:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM sector_constituents WHERE sector = ?", (sector_name,)
                ).fetchone()[0]
                if existing > 0:
                    continue
            symbols = fetch_constituents(session, list_url)
            if not symbols:
                continue
            conn.execute("DELETE FROM sector_constituents WHERE sector = ?", (sector_name,))
            conn.executemany(
                "INSERT OR IGNORE INTO sector_constituents (symbol, sector) VALUES (?, ?)",
                [(sym, sector_name) for sym in symbols],
            )
            print(f"  {sector_name}: {len(symbols)} symbols")


def update_total_market():
    """NO LONGER CALLED by default (see run_daily_update). This was used to
    widen Sector breadth beyond the narrow official index constituents --
    reverted at your request, since 'All Industries' now covers the
    broader picture properly via screener.in classification instead.
    Kept here in case you want to bring widening back for Sectors later."""
    print("Refreshing Total Market industry classifications...")
    session = make_session()
    r = session.get(TOTAL_MARKET_URL, timeout=20)
    if r.status_code != 200:
        print(f"  [warn] Total Market list not found ({r.status_code})")
        return
    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"  [warn] couldn't parse Total Market list: {e}")
        return
    df.columns = [c.strip() for c in df.columns]
    sym_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    ind_col = next((c for c in df.columns if "industry" in c.lower()), None)
    if not sym_col or not ind_col:
        print(f"  [warn] unexpected columns: {list(df.columns)}")
        return
    rows = [
        (str(r[sym_col]).strip(), str(r[ind_col]).strip())
        for _, r in df.iterrows()
        if pd.notna(r[sym_col]) and pd.notna(r[ind_col])
    ]
    with get_conn() as conn:
        conn.execute("DELETE FROM total_market_constituents")
        conn.executemany(
            "INSERT OR REPLACE INTO total_market_constituents (symbol, industry) VALUES (?, ?)",
            rows,
        )
    print(f"  {len(rows)} stocks classified across {df[ind_col].nunique()} industries")


def update_nifty500_industries():
    """Populates basic_industry_map from NSE's Nifty 500 constituent list --
    a plain CSV (not behind Akamai, unlike the quote API).

    CORRECTED: this file's Industry column turned out to be the SAME
    22-category scheme as the Total Market file (confirmed via live data --
    NSE apparently retired the older, finer classification scheme at this
    URL sometime before Nov 2024). So this does NOT give finer-than-sector
    detail -- it's a reasonable ~500-stock fallback so the 'All Industries'
    tab has something to show, but it won't be meaningfully different from
    the widened Sectors tab. classify_industries_playwright.py is what
    actually gets you real, finer categories -- see that file."""
    print("Refreshing Nifty 500 industry classifications (coarse fallback)...")
    session = make_session()
    r = session.get(NIFTY500_INDUSTRY_URL, timeout=20)
    if r.status_code != 200:
        print(f"  [warn] Nifty 500 list not found ({r.status_code})")
        return
    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"  [warn] couldn't parse Nifty 500 list: {e}")
        return
    df.columns = [c.strip() for c in df.columns]
    sym_col = next((c for c in df.columns if c.strip().lower() == "symbol"), None)
    ind_col = next((c for c in df.columns if "industry" in c.lower()), None)
    name_col = next((c for c in df.columns if "company" in c.lower() and "name" in c.lower()), None)
    if not sym_col or not ind_col:
        print(f"  [warn] unexpected columns: {list(df.columns)}")
        return
    rows = [
        (
            str(r[sym_col]).strip(),
            str(r[ind_col]).strip(),
            str(r[name_col]).strip() if name_col else None,
            dt.datetime.now().isoformat(),
        )
        for _, r in df.iterrows()
        if pd.notna(r[sym_col]) and pd.notna(r[ind_col])
    ]
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO basic_industry_map
               (symbol, basic_industry, company_name, classified_at)
               VALUES (?, ?, ?, ?)""",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO classification_meta (key, value) VALUES ('basic_industry_source', 'csv_coarse_22cat')"
        )
    print(f"  {len(rows)} stocks classified across {df[ind_col].nunique()} categories "
          f"(coarse -- same scheme as sector widening, not finer)")


def update_index_prices():
    print(f"Fetching index history ({INDEX_HISTORY_DAYS} days)...")
    session = make_session()
    wanted = {v[0] for v in SECTORS.values()} | {"NIFTY 50", MIDSMALL_INDEX}
    got, missed = 0, 0
    with get_conn() as conn:
        # If any wanted index has zero rows so far (e.g. just added to
        # config), the normal per-date skip below would mean it only
        # starts accumulating from today -- ema_block() needs 25+ days
        # before showing anything, 200+ for the 200 EMA. So: force a full
        # backfill this run whenever that's the case. INSERT OR REPLACE
        # makes re-fetching already-stored dates harmless, just slower.
        rows_per_index = {
            name: conn.execute(
                "SELECT COUNT(*) FROM index_prices WHERE sector = ?", (name,)
            ).fetchone()[0]
            for name in wanted
        }
        brand_new = [name for name, n in rows_per_index.items() if n == 0]
        if brand_new:
            print(f"  new index(es) with no history yet: {brand_new} -- doing a full backfill this run")
            existing_dates = set()
        else:
            existing_dates = {
                row[0] for row in conn.execute(
                    "SELECT DISTINCT date FROM index_prices"
                ).fetchall()
            }
        for date in trading_days_back(INDEX_HISTORY_DAYS):
            ds = date.isoformat()
            if ds in existing_dates:
                continue
            df = fetch_index_file(session, date)
            if df is None:
                missed += 1
                continue
            name_col = next((c for c in df.columns if "index" in c.lower() and "name" in c.lower()), None)
            close_col = next((c for c in df.columns if c.strip().lower() == "closing index value"), None)
            if not name_col or not close_col:
                missed += 1
                continue
            rows = []
            for _, r in df.iterrows():
                idx_name = str(r[name_col]).strip().upper()
                if idx_name in wanted:
                    try:
                        rows.append((idx_name, ds, float(r[close_col])))
                    except (ValueError, TypeError):
                        continue
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO index_prices (sector, date, close) VALUES (?, ?, ?)",
                    rows,
                )
                got += 1
            time.sleep(0.3)
    print(f"  index files parsed: {got}, missed/holidays: {missed}")


def update_stock_prices():
    """Stores EVERY EQ-series stock's daily close/high/low/volume, not just
    the ones in your tracked sectors -- this is what makes the
    basic-industry view AND the stock scanner possible.

    'existing_dates' only counts dates where volume IS NOT NULL -- so any
    date stored back when this only saved 'close' (before high/low/volume
    were added) looks unfetched and gets pulled again automatically here,
    filling in the full row via INSERT OR REPLACE. Self-healing, no
    separate backfill script needed -- same trick update_index_prices()
    already uses for brand-new indices.
    """
    print(f"Fetching stock bhavcopy history ({STOCK_HISTORY_DAYS} days, full universe)...")
    session = make_session()
    with get_conn() as conn:
        existing_dates = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT date FROM stock_prices WHERE volume IS NOT NULL"
            ).fetchall()
        }
        got, missed, total_rows = 0, 0, 0
        for date in trading_days_back(STOCK_HISTORY_DAYS):
            ds = date.isoformat()
            if ds in existing_dates:
                continue
            df = fetch_bhavcopy(session, date)
            if df is None:
                missed += 1
                continue
            sym_col = next((c for c in df.columns if c.strip().upper() == "SYMBOL"), None)
            close_col = next((c for c in df.columns if c.strip().upper() == "CLOSE_PRICE"), None)
            high_col = next((c for c in df.columns if c.strip().upper() == "HIGH_PRICE"), None)
            low_col = next((c for c in df.columns if c.strip().upper() == "LOW_PRICE"), None)
            vol_col = next((c for c in df.columns if c.strip().upper() == "TTL_TRD_QNTY"), None)
            series_col = next((c for c in df.columns if c.strip().upper() == "SERIES"), None)
            if not sym_col or not close_col:
                missed += 1
                continue
            rows = []
            for _, r in df.iterrows():
                if series_col and str(r[series_col]).strip().upper() != "EQ":
                    continue
                sym = str(r[sym_col]).strip()
                try:
                    close = float(r[close_col])
                except (ValueError, TypeError):
                    continue
                # high/low/volume are best-effort -- a missing/malformed
                # value on any of these shouldn't drop the whole row, since
                # close alone still feeds every EMA/breadth/RS calc that
                # already existed before this change.
                def _optional_float(col):
                    if not col:
                        return None
                    try:
                        return float(r[col])
                    except (ValueError, TypeError):
                        return None
                high = _optional_float(high_col)
                low = _optional_float(low_col)
                volume = _optional_float(vol_col)
                rows.append((sym, ds, close, high, low, volume))
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO stock_prices (symbol, date, close, high, low, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                got += 1
                total_rows += len(rows)
            time.sleep(0.3)
    print(f"  bhavcopy files parsed: {got}, missed/holidays: {missed}, rows stored: {total_rows}")


def run_daily_update():
    init_db()
    with get_conn() as conn:
        has_basic_industry = conn.execute(
            "SELECT COUNT(*) FROM basic_industry_map"
        ).fetchone()[0] > 0
    # Always call this -- it's per-sector idempotent now (skips sectors
    # that already have data), so it's cheap even when nothing's new, and
    # it's what catches any newly-added sector automatically going forward.
    update_constituents()
    if not has_basic_industry:
        update_nifty500_industries()
    update_index_prices()
    update_stock_prices()
    print("Done.")


if __name__ == "__main__":
    run_daily_update()
