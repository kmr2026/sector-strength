"""
Follow-up: the two candidate URLs for Nifty Private Bank both returned
200 but neither contained a SYMBOL column -- possibly niftyindices.com
serving a generic app page (200 status) instead of a real 404 for URLs
that don't exist. This tries more filename variants AND prints what's
actually in the response, so we can see directly rather than guess again.

Run: python find_private_bank_index_v2.py
"""
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

session = requests.Session()
session.headers.update(HEADERS)
session.get("https://www.nseindia.com", timeout=10)

candidates = [
    "https://archives.nseindia.com/content/indices/ind_niftyprivatebanklist.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty_privatebanklist.csv",
    "https://archives.nseindia.com/content/indices/ind_niftypvtbanklist.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_niftyprivatebank_list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty_privatebank_list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_niftypvtbank_list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty_pvt_bank_list.csv",
]

print("=== Testing expanded candidate list, showing actual content ===\n")
for url in candidates:
    try:
        r = session.get(url, timeout=15)
    except requests.RequestException as e:
        print(f"[ERROR] {url} -> {e}\n")
        continue
    has_symbol = "SYMBOL" in r.text.upper()
    content_type = r.headers.get("content-type", "?")
    mark = "OK" if r.status_code == 200 and has_symbol else str(r.status_code)
    print(f"[{mark}] {url}")
    print(f"  content-type: {content_type}, length: {len(r.text)} chars, has 'SYMBOL': {has_symbol}")
    if r.status_code == 200 and not has_symbol:
        print(f"  first 200 chars of body: {r.text[:200]!r}")
    print()

print("Done. If any [OK], that's the one. Otherwise send me the printed")
print("body previews -- they'll show what's actually being returned.")
