import sqlite3
from contextlib import contextmanager
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_prices (
    sector TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY (sector, date)
);

CREATE TABLE IF NOT EXISTS stock_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL NOT NULL,
    high REAL,
    low REAL,
    volume REAL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS sector_constituents (
    symbol TEXT NOT NULL,
    sector TEXT NOT NULL,
    PRIMARY KEY (symbol, sector)
);

CREATE TABLE IF NOT EXISTS total_market_constituents (
    symbol TEXT NOT NULL PRIMARY KEY,
    industry TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS basic_industry_map (
    symbol TEXT NOT NULL PRIMARY KEY,
    macro TEXT,
    sector TEXT,
    industry TEXT,
    basic_industry TEXT NOT NULL,
    company_name TEXT,
    market_cap_cr REAL,
    shares_outstanding REAL,
    classified_at TEXT
);

CREATE TABLE IF NOT EXISTS classification_meta (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS fetch_log (
    run_at TEXT NOT NULL,
    date TEXT,
    status TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS score_history (
    key TEXT NOT NULL,
    date TEXT NOT NULL,
    score INTEGER NOT NULL,
    bullish_stack INTEGER,
    overheated INTEGER,
    PRIMARY KEY (key, date)
);

CREATE TABLE IF NOT EXISTS regime_history (
    key TEXT NOT NULL,
    date TEXT NOT NULL,
    state TEXT,
    PRIMARY KEY (key, date)
);

-- Generic day-keyed metric tracker, shared by any numeric per-sector/
-- per-industry metric that wants a delta badge (RS Rating, % within
-- 52-week high, and future ones) without needing a dedicated table per
-- metric. 'metric' distinguishes which one a row belongs to.
CREATE TABLE IF NOT EXISTS metric_history (
    metric TEXT NOT NULL,
    key TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (metric, key, date)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Migration for databases created before bullish_stack/overheated
        # existed on score_history -- CREATE TABLE IF NOT EXISTS above is a
        # no-op on an already-existing table, so these columns need adding
        # separately. Harmless/no-op on a fresh table that already has them.
        for col in ("bullish_stack", "overheated"):
            try:
                conn.execute(f"ALTER TABLE score_history ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Same pattern for stock_prices' high/low/volume -- added for the
        # stock-scanner feature. fetch_data.py's update_stock_prices()
        # treats any date missing 'volume' as not-yet-fetched, so existing
        # close-only rows self-heal (get re-fetched with full OHLCV) on the
        # next run -- no separate backfill script needed.
        for col in ("high", "low", "volume"):
            try:
                conn.execute(f"ALTER TABLE stock_prices ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Same pattern for basic_industry_map's market_cap_cr -- added for
        # the scanner's Market Cap filter. classify_via_screener.py needs
        # --force on its next run to backfill this for industries already
        # classified before this column existed (its normal skip-what's-
        # already-done logic won't revisit them otherwise).
        try:
            conn.execute("ALTER TABLE basic_industry_map ADD COLUMN market_cap_cr REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        # shares_outstanding is the stable, derived value (market_cap_cr /
        # CMP at scrape time) -- compute_stock_scanner.py multiplies this
        # by TODAY's close price to get a market cap that's fresh every
        # day, instead of the one-time scraped market_cap_cr snapshot
        # going stale as the price moves.
        try:
            conn.execute("ALTER TABLE basic_industry_map ADD COLUMN shares_outstanding REAL")
        except sqlite3.OperationalError:
            pass  # column already exists


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
