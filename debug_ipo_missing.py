"""
DEBUG ONLY. Run once, send Claude the output.

Checks whether a specific set of symbols that ChartsMaze shows as recent
IPOs, but our site is missing, are genuinely absent from NSE's own
public-past-issues record, or present under a different symbol/spelling
that our exact-match logic missed.
"""
import requests

MISSING_SYMBOLS = [
    "TATACAP", "PIRAMALFIN", "CEINSYS", "IBULLSLTD", "SKFINDUS",
    "CANHLIFE", "ABCOTS", "ADVENTHTL", "AEROPLANE", "AGL", "ASTAR",
]
MISSING_COMPANY_HINTS = [
    "Tata Capital", "Piramal", "Ceinsys", "Indiabulls", "SKF",
    "Canara HSBC", "Abcots", "Advent", "Aeroplane", "Astar",
]

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
    print(f"status: {r.status_code}")
    records = r.json()
    print(f"total records: {len(records)}")

    all_symbols = {rec.get("symbol", "").upper() for rec in records}
    all_companies_lower = [rec.get("company", "").lower() for rec in records]

    print("\n--- Exact symbol match check ---")
    for sym in MISSING_SYMBOLS:
        found = sym.upper() in all_symbols
        print(f"  {sym:12s} -> {'FOUND' if found else 'not found'}")

    print("\n--- Fuzzy company-name search (in case symbol differs) ---")
    for hint in MISSING_COMPANY_HINTS:
        matches = [rec for rec in records if hint.lower() in rec.get("company", "").lower()]
        if matches:
            print(f"  '{hint}': {len(matches)} match(es)")
            for m in matches[:3]:
                print(f"    {m}")
        else:
            print(f"  '{hint}': no match at all in this response")


if __name__ == "__main__":
    main()
