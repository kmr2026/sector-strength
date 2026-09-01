"""
Runs the same scoring logic as the live app, but writes the result to
docs/data/leaderboard.json and docs/data/basic_industries.json instead of
serving it from an API.

This is what makes free static hosting (GitHub Pages) possible: the site
itself has no backend -- it just reads these JSON files, which you refresh
once a day.

Run this right after fetch_data.py, every day:

    python fetch_data.py
    python export_snapshot.py
    git add -A
    git commit -m "daily sector data update"
    git push
"""
import json
import datetime as dt
from pathlib import Path

from compute import compute_all as compute_sectors
from compute_basic_industry import compute_all_with_meta
from compute_stock_scanner import compute_all as compute_stock_scanner

DATA_DIR = Path(__file__).parent / "docs" / "data"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    leaderboard = compute_sectors()
    (DATA_DIR / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2, default=str))
    print(f"Wrote {len(leaderboard['sectors'])} sectors to leaderboard.json "
          f"(regime: {leaderboard['regime'].get('state', 'n/a')})")

    industries_result = compute_all_with_meta()
    (DATA_DIR / "basic_industries.json").write_text(json.dumps(industries_result, indent=2, default=str))
    print(f"Wrote {len(industries_result['industries'])} basic industries to basic_industries.json "
          f"(source: {industries_result['classification_source']})")

    scanner_result = compute_stock_scanner()
    (DATA_DIR / "stock_scanner.json").write_text(json.dumps(scanner_result, indent=2, default=str))
    print(f"Wrote {len(scanner_result)} stocks to stock_scanner.json")

    print(f"Done at {dt.datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
