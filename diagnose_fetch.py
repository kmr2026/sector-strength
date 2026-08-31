"""
Diagnostic: shows the RAW status code and response NSE sends back,
instead of the silent None that fetch_data.py's normal functions return.

Run this from the same folder as fetch_data.py:
    python diagnose_fetch.py
"""
import datetime as dt
from fetch_data import make_session, NSE_BASE

# A known real trading day (Friday) so we're not accidentally testing
# an actual holiday.
test_date = dt.date(2026, 8, 28)

session = make_session()

print("=" * 60)
print("INDEX FILE TEST")
print("=" * 60)
fname = f"ind_close_all_{test_date.strftime('%d%m%Y')}.csv"
url = f"{NSE_BASE}/content/indices/{fname}"
print(f"URL: {url}")
r = session.get(url, timeout=15)
print(f"Status code: {r.status_code}")
print(f"Response headers: {dict(r.headers)}")
print(f"First 500 chars of body:\n{r.text[:500]}")

print()
print("=" * 60)
print("BHAVCOPY FILE TEST")
print("=" * 60)
fname2 = f"sec_bhavdata_full_{test_date.strftime('%d%m%Y')}.csv"
url2 = f"{NSE_BASE}/products/content/{fname2}"
print(f"URL: {url2}")
r2 = session.get(url2, timeout=20)
print(f"Status code: {r2.status_code}")
print(f"Response headers: {dict(r2.headers)}")
print(f"First 500 chars of body:\n{r2.text[:500]}")
