"""
Fetches NSE corporate actions (bonus issues, face-value splits) and
back-adjusts stock_prices so historical EMAs/52wk-high-low/RS aren't
corrupted by a split/bonus showing up as a fake overnight price crash.

WHY curl_cffi INSTEAD OF requests
-----------------------------------
www.nseindia.com (unlike archives.nseindia.com, which fetch_data.py
already uses fine) sits behind Akamai TLS/JA3 fingerprint detection --
it blocks plain `requests` even with perfect browser-like headers,
because the underlying TLS handshake still reveals Python/OpenSSL, not
Chrome/BoringSSL. curl_cffi impersonates a real Chrome TLS handshake.
Confirmed working live: homepage 403 with plain requests -> 200 with
curl_cffi(impersonate="chrome"), same machine, same day.

REGEX FORMATS -- confirmed against a real 1-year pull (Sep 2025-Sep
2026, 2132 records, 49 bonus + 51 split rows), not guessed:
  Bonus:  "Bonus A:B"                                              (exact)
  Split:  "Face Value Split (Sub-Division) - From Rs X/- Per Share
           To Rs Y/- Per Share"  (or "Re 1/-" for a single rupee)  (exact)

Both regexes are ANCHORED (^...$) deliberately -- a few real rows in the
same pull were "Scheme Of Arrangement - Bonus Ncrps 4:1", a bonus issue
of a DIFFERENT security class (preference shares, not equity). A loose
"contains bonus" match would misclassify these and apply the wrong
ratio to the equity price series. Anchored matching naturally excludes
them -- they fall through to the "unparsed, skipped" bucket, printed so
you can see what's being excluded and why, not silently dropped.

ADJUSTMENT MATH
----------------
Bonus "A:B" (A new shares for every B held) -- matches NSE's own F&O
adjustment-factor formula (adjustment factor = (A+B)/B, i.e. total
shares multiply by (A+B)/B):
    historical_price_multiplier = B / (A + B)

Split, face value F_old -> F_new (share count multiplies by F_old/F_new):
    historical_price_multiplier = F_new / F_old

In both cases: multiply close/high/low for every date STRICTLY BEFORE
ex_date by the multiplier. Applying multiple actions for the same
symbol in any order is safe -- each only ever touches dates before its
OWN ex_date, so the final cumulative adjustment for any given historical
date is just the product of every later action's multiplier, achieved
correctly regardless of processing order.

IDEMPOTENCY
------------
corporate_actions.applied tracks whether stock_prices has already been
adjusted for a given (symbol, ex_date, action_type). Re-running this
daily must never re-multiply the same action twice -- INSERT OR IGNORE
on the primary key means an action already seen keeps its existing
applied=1 and is never reprocessed.

DRY RUN BY DEFAULT
--------------------
Prints exactly what WOULD change (symbol, multiplier, rows affected)
without touching the DB, unless you pass --apply. Matches your
"auditable, no silent mutation" standard for anything as easy to get
subtly wrong as this.

Run locally:
    pip install curl_cffi
    python apply_corporate_actions.py            # dry run, prints only
    python apply_corporate_actions.py --apply     # actually adjusts stock_prices
"""
import re
import sys
import datetime as dt
from curl_cffi import requests as cf_requests

from config import STOCK_HISTORY_DAYS, DB_PATH
from db import get_conn, init_db

NSE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Same lookback as your stock_prices retention, plus a buffer -- an action
# with an ex-date just outside STOCK_HISTORY_DAYS still matters if any of
# your retained rows predate it.
LOOKBACK_DAYS = STOCK_HISTORY_DAYS + 60

BONUS_RE = re.compile(r"^Bonus\s+(\d+)\s*:\s*(\d+)$", re.IGNORECASE)
SPLIT_RE = re.compile(
    r"^Face Value Split \(Sub-Division\) - From R[se]\s*([\d.]+)/-\s*Per Share "
    r"To R[se]\s*([\d.]+)/-\s*Per Share$",
    re.IGNORECASE,
)


def make_nse_session():
    session = cf_requests.Session(impersonate="chrome")
    session.headers.update(NSE_HEADERS)
    home = session.get("https://www.nseindia.com", timeout=15)
    if home.status_code != 200:
        print(f"  [error] homepage warm-up returned {home.status_code} -- "
              f"NSE may have changed its blocking again. Stopping.")
        return None
    return session


def fetch_corporate_actions(session):
    today = dt.date.today()
    from_date = (today - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%d-%m-%Y")
    to_date = today.strftime("%d-%m-%Y")

    url = "https://www.nseindia.com/api/corporates-corporateActions"
    params = {"index": "equities", "from_date": from_date, "to_date": to_date}
    resp = session.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        print(f"  [error] corporate actions fetch returned {resp.status_code}")
        return []
    try:
        data = resp.json()
    except Exception as e:
        print(f"  [error] response wasn't valid JSON: {e}")
        return []
    return data if isinstance(data, list) else data.get("data", [])


def parse_action(record: dict):
    """Returns (action_type, ratio_text, multiplier) or None if this
    record doesn't match either exact format we trust."""
    subject = (record.get("subject") or "").strip()

    m = BONUS_RE.match(subject)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 0 or b <= 0:
            return None
        multiplier = b / (a + b)
        return "bonus", subject, multiplier

    m = SPLIT_RE.match(subject)
    if m:
        old_fv, new_fv = float(m.group(1)), float(m.group(2))
        if old_fv <= 0 or new_fv <= 0 or new_fv >= old_fv:
            # new face value should always be SMALLER than old for a split
            # -- if not, this isn't a normal split, don't guess.
            return None
        multiplier = new_fv / old_fv
        return "split", subject, multiplier

    return None


def main():
    dry_run = "--apply" not in sys.argv

    init_db()

    print("Establishing NSE session (curl_cffi, Chrome impersonation)...")
    session = make_nse_session()
    if session is None:
        sys.exit(1)

    print(f"Fetching corporate actions (last {LOOKBACK_DAYS} days)...")
    records = fetch_corporate_actions(session)
    print(f"  got {len(records)} total records\n")

    parsed = []
    skipped_bonus_like = 0
    skipped_split_like = 0
    for r in records:
        result = parse_action(r)
        if result:
            action_type, ratio_text, multiplier = result
            symbol = (r.get("symbol") or "").strip()
            ex_date_raw = (r.get("exDate") or "").strip()
            if not symbol or not ex_date_raw:
                continue
            try:
                ex_date = dt.datetime.strptime(ex_date_raw, "%d-%b-%Y").date().isoformat()
            except ValueError:
                print(f"  [warn] unparseable ex_date {ex_date_raw!r} for {symbol}, skipping")
                continue
            parsed.append((symbol, ex_date, action_type, ratio_text, multiplier))
        else:
            subject_lower = (r.get("subject") or "").lower()
            if "bonus" in subject_lower:
                skipped_bonus_like += 1
            elif "split" in subject_lower or "sub-division" in subject_lower:
                skipped_split_like += 1

    print(f"Parsed {len(parsed)} clean bonus/split actions.")
    if skipped_bonus_like:
        print(f"  [note] {skipped_bonus_like} bonus-like row(s) didn't match the "
              f"exact 'Bonus A:B' format (e.g. NCRPS/preference-share bonuses) -- skipped.")
    if skipped_split_like:
        print(f"  [note] {skipped_split_like} split-like row(s) didn't match the "
              f"exact face-value-change format -- skipped.")
    print()

    with get_conn() as conn:
        # Only symbols we actually track -- no point adjusting/logging
        # actions for stocks outside your universe.
        tracked_symbols = {row[0] for row in conn.execute("SELECT DISTINCT symbol FROM stock_prices")}

        new_actions = []
        for symbol, ex_date, action_type, ratio_text, multiplier in parsed:
            if symbol not in tracked_symbols:
                continue
            existing = conn.execute(
                "SELECT applied FROM corporate_actions WHERE symbol=? AND ex_date=? AND action_type=?",
                (symbol, ex_date, action_type),
            ).fetchone()
            if existing is not None:
                continue  # already seen (applied or not) -- never reprocess
            new_actions.append((symbol, ex_date, action_type, ratio_text, multiplier))

        print(f"{len(new_actions)} NEW action(s) not yet in corporate_actions table "
              f"(out of {len(tracked_symbols)} tracked symbols):\n")

        if not new_actions:
            print("Nothing to do.")
            return

        for symbol, ex_date, action_type, ratio_text, multiplier in new_actions:
            affected = conn.execute(
                "SELECT COUNT(*) FROM stock_prices WHERE symbol=? AND date<?",
                (symbol, ex_date),
            ).fetchone()[0]
            print(f"  {symbol:<15} {ex_date}  {action_type:<6}  '{ratio_text}'  "
                  f"multiplier={multiplier:.6f}  rows_to_adjust={affected}")

        if dry_run:
            print("\n[DRY RUN] No changes made. Re-run with --apply to actually "
                  "adjust stock_prices and record these as applied.")
            return

        print("\nApplying...")
        now = dt.datetime.now().isoformat()
        for symbol, ex_date, action_type, ratio_text, multiplier in new_actions:
            conn.execute(
                """UPDATE stock_prices
                   SET close = close * ?, high = high * ?, low = low * ?
                   WHERE symbol = ? AND date < ?""",
                (multiplier, multiplier, multiplier, symbol, ex_date),
            )
            conn.execute(
                """INSERT INTO corporate_actions
                   (symbol, ex_date, action_type, ratio_text, adjustment_multiplier, applied, fetched_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (symbol, ex_date, action_type, ratio_text, multiplier, now),
            )
            print(f"  [applied] {symbol} {ex_date} {action_type} x{multiplier:.6f}")

        print(f"\nDone. {len(new_actions)} action(s) applied to {DB_PATH}.")


if __name__ == "__main__":
    main()
