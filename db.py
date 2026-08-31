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
    PRIMARY KEY (key, date)
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


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
