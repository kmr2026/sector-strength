"""
DEBUG ONLY -- not part of the pipeline. Run this once, by hand, and send
Claude the output.

Purpose: check whether NSE's actual IPO data (real primary-market issues,
distinct from the "date of listing" column in EQUITY_L.csv, which also
picks up demergers/spin-offs like Tata Motors Commercial Vehicles or
Vedanta Aluminium Metal) is reachable via plain requests, BEFORE building
a real fetch pipeline around it.

Why this is worth checking first, not assuming: every URL that's worked
in this project so far (EQUITY_L.csv, circuit bands, Nifty 500 industry
list) lives on archives.nseindia.com -- plain static files, no bot
protection. The IPO page NSE actually publishes
(nseindia.com/market-data/all-upcoming-issues-ipo) is on the OTHER,
modern site -- the same one that hard-blocked quote-equity earlier this
session with a flat Akamai 403, even through a real headed Chrome browser
via Playwright. This script tries a few plausible API paths behind that
page and prints the raw response, so we find out in 10 seconds whether
this is viable at all, instead of building a whole filter/pipeline on a
guess.

USAGE:
    python debug_ipo_api.py
"""
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
}

# Best-guess candidate endpoints behind the public IPO page -- NSE doesn't
# publish an API reference, so these are informed guesses based on the
# page's own URL and common NSE API naming patterns, not confirmed paths.
CANDIDATES = [
    "https://www.nseindia.com/api/public-past-issues",
    "https://www.nseindia.com/api/all-upcoming-issues?category=ipo",
    "https://www.nseindia.com/api/ipo-detail",
    "https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData",  # unlikely, included for completeness
]


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    print("Step 1: priming a session against www.nseindia.com homepage...")
    try:
        r = session.get("https://www.nseindia.com", timeout=15)
        print(f"  homepage status: {r.status_code}")
    except Exception as e:
        print(f"  [warn] homepage request itself failed: {e}")

    for url in CANDIDATES:
        print(f"\nTrying: {url}")
        try:
            r = session.get(url, timeout=15)
            print(f"  status: {r.status_code}")
            print(f"  first 500 chars of response:\n  {r.text[:500]}")
        except Exception as e:
            print(f"  [error] request failed: {e}")

    print("\n\n--- Deeper look at public-past-issues: find an entry that's actually listed ---")
    try:
        r = session.get("https://www.nseindia.com/api/public-past-issues", timeout=15)
        data = r.json()
        print(f"Total entries returned: {len(data)}")
        listed = [row for row in data if row.get("listingDate") and row.get("listingDate") != "-"]
        print(f"Entries with a real listingDate: {len(listed)}")
        if listed:
            print("First 3 listed entries, full fields:")
            for row in listed[:3]:
                print(" ", row)
        else:
            print("None in this response had a real listingDate -- may need a date-range "
                  "query param this script isn't passing. Full first entry for reference:")
            print(" ", data[0] if data else "(empty response)")
    except Exception as e:
        print(f"[error] {e}")


if __name__ == "__main__":
    main()
