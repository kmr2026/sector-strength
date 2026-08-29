from db import get_conn, init_db

init_db()  # safe to call even if tables already exist

with get_conn() as conn:
    before = conn.execute("SELECT COUNT(*) FROM basic_industry_map").fetchone()[0]
    conn.execute("DELETE FROM basic_industry_map")
    conn.execute("DELETE FROM classification_meta WHERE key = 'basic_industry_source'")
    conn.execute("DELETE FROM classification_meta WHERE key LIKE 'empty_industry:%'")

print(f"Cleared {before} rows from basic_industry_map, and reset classification_meta.")
print("Ready for a clean run of classify_via_screener.py.")
