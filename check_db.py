from db import get_conn

with get_conn() as conn:
    rows = conn.execute("SELECT COUNT(*) FROM basic_industry_map").fetchone()[0]
    industries = conn.execute("SELECT COUNT(DISTINCT basic_industry) FROM basic_industry_map").fetchone()[0]
    source_row = conn.execute(
        "SELECT value FROM classification_meta WHERE key = 'basic_industry_source'"
    ).fetchone()
    source = source_row[0] if source_row else "(not set)"

print(f"basic_industry_map rows: {rows}")
print(f"distinct industries: {industries}")
print(f"classification_source: {source}")
