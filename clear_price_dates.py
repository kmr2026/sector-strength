"""
One-off / on-demand utility to purge specific date(s) from every
date-keyed table -- for correcting a date that got stored under the wrong
label (e.g. NSE served stale/cached content for a trading holiday's file
before fetch_data.py's _validate_file_date() existed to catch this).

Deletes rows for the given date(s) from:
  index_prices, stock_prices, score_history, regime_history, metric_history

score_history/regime_history/metric_history are included because those are
snapshots COMPUTED from the (bad) index_prices/stock_prices data for that
date -- leaving them in place would keep a phantom entry in score-history
sparklines and day-over-day delta badges even after the underlying price
data is gone.

Also resets corporate_actions.applied=0 for any action whose ex_date is
AFTER the cleared date. Reasoning: stock_prices rows for that date get
deleted here and re-fetched RAW (unadjusted) by the next fetch_data.py
run. If any corporate action's back-adjustment had already multiplied
that date's price (i.e. the date falls before the action's own ex_date),
the re-fetch silently overwrites the adjusted value with the raw one --
and without this reset, apply_corporate_actions.py's own idempotency
check would see the action already marked applied=1 and skip it forever,
permanently reintroducing the exact price discontinuity the corporate-
actions fix exists to prevent. This clears ALL symbols' rows for the
date (stock_prices is keyed by date across the whole universe, not
per-symbol), so it conservatively resets every action after that date
rather than trying to work out which symbols were actually touched --
a few extra re-applications on the next apply_corporate_actions.py run
are harmless; a missed one is not.

After running this, the next fetch_data.py run will see the date as
never-fetched and try again -- now going through the date cross-check
added in fetch_data.py, so if NSE is still serving the same stale content
for that URL, it gets rejected again instead of silently re-poisoning the
table. Run apply_corporate_actions.py --apply after fetch_data.py, same
as the normal daily pipeline, to pick back up any reset actions.

Usage:
    python clear_price_dates.py 2026-09-14
    python clear_price_dates.py 2026-09-14 2026-01-01   # multiple dates
"""
import sys
from db import get_conn, init_db

TABLES = [
    ("index_prices", "date"),
    ("stock_prices", "date"),
    ("score_history", "date"),
    ("regime_history", "date"),
    ("metric_history", "date"),
]


def clear_dates(dates: list[str]):
    init_db()  # ensures corporate_actions exists even on a fresh/old cached DB
    with get_conn() as conn:
        for d in dates:
            counts = {}
            for table, date_col in TABLES:
                n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {date_col} = ?", (d,)).fetchone()[0]
                if n:
                    conn.execute(f"DELETE FROM {table} WHERE {date_col} = ?", (d,))
                counts[table] = n
            removed = {t: n for t, n in counts.items() if n}
            if removed:
                print(f"{d}: removed " + ", ".join(f"{n} row(s) from {t}" for t, n in removed.items()))
            else:
                print(f"{d}: nothing found in any table -- already clean.")

            reset = conn.execute(
                "UPDATE corporate_actions SET applied = 0 WHERE ex_date > ? AND applied = 1",
                (d,),
            ).rowcount
            if reset:
                print(f"{d}: reset {reset} corporate action(s) with ex_date after this "
                      f"date back to applied=0 -- run apply_corporate_actions.py --apply "
                      f"after the next fetch_data.py run to reapply them.")


if __name__ == "__main__":
    dates = sys.argv[1:]
    if not dates:
        print("Usage: python clear_price_dates.py YYYY-MM-DD [YYYY-MM-DD ...]")
        sys.exit(1)
    clear_dates(dates)

