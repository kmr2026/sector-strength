"""
Optional local preview server.

This is NOT required for the site to work -- docs/ is a fully static
site (index.html reads docs/data/leaderboard.json directly), so once
you've run export_snapshot.py you can just double-click docs/index.html
or use any static file server.

This FastAPI app exists purely for convenience: `python app.py` gives
you a local URL with auto-reload-friendly serving, matching exactly
what GitHub Pages will serve.
"""
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Sector Strength (local preview)")
app.mount("/", StaticFiles(directory="docs", html=True), name="docs")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8010)
