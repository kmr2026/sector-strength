"""
One-off helper: figure out the correct NSE constituent-list filenames for
Financial Services and Chemicals (the two that 404'd).

Run this once: python find_missing_filenames.py
It'll print which candidate URL actually works for each sector -- then
update config.py with the winning filename.
"""
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Chemicals is a newer index (launched 2025) -- NSE publishes newer index
# constituent lists on niftyindices.com under /IndexConstituent/, with an
# underscore before "list" (e.g. ind_niftyfinancialservicesexbank_list.xlsx),
# unlike the older archives.nseindia.com/content/indices/ pattern.
CANDIDATES = {
    "Chemicals": [
        "ind_niftychemicals_list.csv",
        "ind_niftychemicalslist.csv",
        "ind_niftyChemicals_list.csv",
        "ind_niftychemical_list.csv",
    ],
}

BASES = [
    "https://www.niftyindices.com/IndexConstituent/",
    "https://niftyindices.com/IndexConstituent/",
    "https://archives.nseindia.com/content/indices/",
]

session = requests.Session()
session.headers.update(HEADERS)
session.get("https://www.nseindia.com", timeout=10)

for sector, names in CANDIDATES.items():
    print(f"\n{sector}:")
    found = False
    for base in BASES:
        for name in names:
            url = base + name
            try:
                r = session.get(url, timeout=10)
            except requests.RequestException as e:
                print(f"  ERROR {url} -> {e}")
                continue
            mark = "OK" if r.status_code == 200 and "SYMBOL" in r.text.upper() else str(r.status_code)
            print(f"  [{mark}] {url}")
            if mark == "OK":
                found = True
    if not found:
        print("  -> none of the guesses worked, check nseindia.com's sectoral index page directly")
