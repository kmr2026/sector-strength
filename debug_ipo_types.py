"""
DEBUG ONLY. Run once, send Claude the output.

Checks every distinct securityType value NSE's public-past-issues
actually returns, and how many records/symbols fall under each -- to
confirm whether filtering to just {"EQ","BE"} is too narrow (e.g. SME
IPOs might use a different code like "SM") or correct.
"""
import requests
from collections import Counter

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
}


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    r = session.get("https://www.nseindia.com/api/public-past-issues", timeout=20)
    records = r.json()
    print(f"total records: {len(records)}")

    counts = Counter(rec.get("securityType") for rec in records)
    print("\nDistinct securityType values and their counts:")
    for stype, count in counts.most_common():
        print(f"  {stype!r}: {count}")

    print("\nA few example records for each non-EQ/BE type (to see what they actually are):")
    seen_types = set()
    for rec in records:
        st = rec.get("securityType")
        if st not in ("EQ", "BE") and st not in seen_types:
            seen_types.add(st)
            print(f"  [{st}] {rec}")


if __name__ == "__main__":
    main()
