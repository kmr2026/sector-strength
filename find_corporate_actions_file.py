"""
One-off diagnostic: find NSE's corporate-actions file (splits/bonuses/
dividends per symbol) and confirm a working, scriptable download URL.

WHY THIS EXISTS
----------------
NSE's own circular (NSE/CMTR/70563, Oct 1 2025) confirms the file we want
is Bcddmmyyyy.csv (corporate action details) inside PRddmmyy.zip -- the
"Bhavcopy (PR)" bundle -- with the display page at nseindia.com/all-reports.

BUT the circular only names the human-facing report page, not the actual
file-download endpoint the page's JS calls, and nseindia.com/all-reports
lives on www.nseindia.com -- the heavily Akamai-protected domain
fetch_data.py deliberately avoids (see its make_session() comment: a
soft-blocked request there can poison the whole session's cookies for
every later archives.nseindia.com request too).

There's also a real chance NSE's older direct archive path still works:
archives.nseindia.com historical EQUITIES folder used to serve PR.zip
files directly by date, no Akamai challenge, same pattern as your
existing bhavcopy fetch.

Rather than hardcode a guess, this script tries several candidate URLs,
with and without priming, and prints EXACTLY what comes back for each --
status code, content-type, first bytes -- so we commit only a URL we've
actually confirmed works, consistent with find_missing_filenames.py /
check_defence_variants.py elsewhere in this repo.

Doesn't touch the DB or config.py. Just prints. Run locally:
    python find_corporate_actions_file.py
"""
import datetime as dt
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Most recent trading day we can reasonably expect a file to exist for.
# Walk back to the last weekday so this works no matter what day you run it.
d = dt.date.today()
while d.weekday() >= 5:  # Sat/Sun
    d -= dt.timedelta(days=1)

ddmmyy = d.strftime("%d%m%y")
ddmmyyyy = d.strftime("%d%m%Y")
mon_upper = d.strftime("%b").upper()   # e.g. SEP
year = d.strftime("%Y")

CANDIDATES = [
    # 1) Old-style direct archive path (pre-rename convention, unconfirmed
    #    whether still live) -- same domain/pattern as your working
    #    bhavcopy fetch, no Akamai challenge if it works.
    (
        "archives.nseindia.com historical EQUITIES (old PR naming)",
        f"https://archives.nseindia.com/content/historical/EQUITIES/{year}/{mon_upper}/PR{ddmmyy}.zip",
    ),
    # 2) Same path, but with the POST-rename filename convention from the
    #    Oct 2025 circular (4-digit year still just in the inner CSV name,
    #    outer zip name unchanged per the circular's own table).
    (
        "archives.nseindia.com historical EQUITIES (current PR naming)",
        f"https://archives.nseindia.com/content/historical/EQUITIES/{year}/{mon_upper}/PR{ddmmyy}.zip",
    ),
    # 3) The www.nseindia.com all-reports API the report page itself likely
    #    calls under the hood (common NSE pattern: /api/reports?...).
    #    Genuinely unconfirmed -- included so we get a real 403/404 on
    #    record rather than skipping it.
    (
        "www.nseindia.com all-reports API guess",
        f"https://www.nseindia.com/api/reports?archives=%5B%7B%22name%22%3A%22CM%20-%20Bhavcopy(PR)%22%2C%22type%22%3A%22archives%22%2C%22category%22%3A%22capital-market%22%2C%22section%22%3A%22equities%22%7D%5D&date={ddmmyy}&type=equities&mode=single",
    ),
]


def try_url(session: requests.Session, label: str, url: str, primed: bool):
    tag = "primed" if primed else "unprimed"
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
    except requests.RequestException as e:
        print(f"  [{tag}] {label}\n         {url}\n         -> request failed: {e}\n")
        return
    ctype = r.headers.get("Content-Type", "?")
    size = len(r.content)
    preview = r.content[:80]
    print(f"  [{tag}] {label}")
    print(f"         {url}")
    print(f"         -> status={r.status_code}  content-type={ctype}  bytes={size}")
    print(f"         -> first bytes: {preview!r}")
    print()


print(f"Testing for trading date {d.isoformat()} (ddmmyy={ddmmyy}, ddmmyyyy={ddmmyyyy})\n")

print("=== Attempt 1: unprimed session (matches fetch_data.py's working pattern) ===\n")
s1 = requests.Session()
for label, url in CANDIDATES:
    try_url(s1, label, url, primed=False)

print("=== Attempt 2: primed session (hit www.nseindia.com homepage first for cookies) ===\n")
s2 = requests.Session()
try:
    home = s2.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
    print(f"  Priming GET https://www.nseindia.com -> status={home.status_code}, "
          f"cookies received: {list(s2.cookies.keys())}\n")
except requests.RequestException as e:
    print(f"  Priming request failed: {e}\n")
for label, url in CANDIDATES:
    try_url(s2, label, url, primed=True)

print("=== Done. Look for a 200 status with content-type application/zip or ===")
print("=== application/x-zip-compressed and non-trivial byte count -- that's ===")
print("=== the one to commit to config.py + fetch_data.py.                  ===")
