# Sector Strength

A dashboard that ranks NSE sectors AND all 197 of NSE's "Basic Industry"
categories, using the framework from our conversation:

- Index price vs. its 21 / 50 / 200 EMA, and whether they're bullishly
  stacked (21 > 50 > 200, all sloping up)
- % of stocks above their own 10-day MA (breadth), and whether that
  breadth is rising or falling vs a week ago
- Relative strength vs Nifty 50 (rising = leading, falling = lagging)
- A transparent, additive composite score (0-100) combining all three —
  nothing hidden, click any row to see exactly which points came from where

Two views, one site:
- **Sectors** — your 16 tracked sectors + Telecom, using NSE's own official
  index prices, with breadth widened from ~250 stocks to ~750 wherever a
  clean industry match exists (marked with a green "+")
- **All Industries** — every one of NSE's 197 Basic Industry categories
  that has enough stocks to be statistically meaningful, using a
  **synthetic** equal-weighted index (see note below — NSE doesn't publish
  a real index for these, so we build one from the member stocks)

No cloud, no login required to run it. Hosting is free (see step 5).

## 1. Install

You need Python 3.10+. From this folder:

```
pip install -r requirements.txt
```

## 2. One-time: classify stocks into industries

Three options now, ranked by how well they've actually tested out. Pick
one before you run `fetch_data.py` for the first time (it only auto-fills
the weakest fallback if this table is still empty). Whichever you use,
the site honestly labels which one is active — see "Honest labeling"
below, and in `docs/app.js`.

### Recommended: screener.in's public industry pages (~188 categories)

```
pip install beautifulsoup4
python classify_via_screener.py
```

This is the one that actually worked. Unlike the NSE quote API, these are
plain, public, server-rendered pages — no login, no premium paywall, no
JS challenge, no bot-blocking encountered during testing. I fetched and
inspected the real pages before writing this script (index page listing
all ~188 leaf industries, a small industry, and a large paginated one) so
the parsing is built against actual verified structure, not a guess.

It fetches `screener.in/market/` (an index of every leaf-level industry
with company counts), then each industry's company list (handling
pagination). Company links use the actual NSE symbol as the URL slug in
most cases, so they match your existing price data directly — a handful
of smaller/BSE-only companies show a numeric BSE code instead, and those
just naturally get excluded later (no NSE price history to score).

Expect a few minutes for the full ~190-250 page fetch, politely paced.
Self-labels the data as `screener_public_188cat` once it succeeds.

Run `python classify_via_screener.py --debug` first if you want to sanity
check it against just the index page + one sample industry before
committing to the full run.

### Alternative: full 197-category NSE version — currently blocked

```
pip install playwright
python classify_industries_playwright.py
```

**Status as of live testing:** still getting a 403 "Access Denied" from
NSE's edge, even using your real, already-installed Chrome with a genuine
browser session. This looks like either a dedicated, stricter rule on
this exact API path, or your IP flagged from earlier attempts — worth a
router restart as a diagnostic if you're curious, but the screener.in
path above already gets you real, working data without fighting this.

### Fallback: coarse ~500-stock CSV version (automatic if you skip both above)

If you skip both options above, `fetch_data.py` automatically fills this
in using a plain CSV download — see `update_nifty500_industries()` in
`fetch_data.py`. **Correction from earlier:** I originally believed this
gave a finer ~70-category breakdown; live testing showed NSE retired that
scheme before Nov 2024, and this file now uses the same coarse
~22-category scheme as the Sectors tab's breadth-widening. It's just a
placeholder so "All Industries" has something to show if you skip the
better options — the site labels it honestly as `csv_coarse_22cat` rather
than pretending it's finer than it is.

## 3. Pull price data

```
python fetch_data.py
```

Downloads:
- Sector constituent lists + Nifty Total Market industry tags (once)
- Nifty 500 fallback industry classification (once, only if you skipped
  step 2's Playwright option)
- ~300 days of sector index history
- ~300 days of **every** NSE stock's daily close (not just your tracked
  sectors — the full bhavcopy universe, needed for both views' breadth/EMA)

First run downloads 300 daily files and will take a while. After that,
re-running only fetches new dates, so it's fast — run it daily.

**Unverified live on my end** (my sandbox can't reach nseindia.com) — but
this follows the exact same CSV-download pattern that's already confirmed
working for your sector data, so it should carry over cleanly.

## 4. Preview it locally

```
python app.py
```

Then open **http://127.0.0.1:8010**. (`docs/` is a fully static site — you
could also just double-click `docs/index.html`, or use any static file
server.)

## 5. Put it on a free website (GitHub Pages)

Since this only needs to update once a day, the cleanest free option is a
**static site** — no server to keep alive, no cold starts, nothing that
expires. `export_snapshot.py` turns the day's computed leaderboard into
JSON files that the page reads directly.

**One-time setup:**
1. Create a new **public** GitHub repo (e.g. `sector-strength`).
2. From this folder: `git init`, `git add .`, `git commit -m "initial"`,
   then follow GitHub's instructions to push it to that repo.
3. On GitHub: **Settings → Pages → Source → Deploy from a branch**,
   branch `main`, folder **`/docs`** → Save.
4. GitHub gives you a URL like `https://<username>.github.io/sector-strength/`
   — that's your live site.

**Every day after that**, run:
```
python fetch_data.py
python export_snapshot.py
git add -A
git commit -m "daily sector data update"
git push
```
The site updates within a minute or two of the push. Wire this into the
same Task Scheduler job you use for `fetch_data.py`.

**`sector_strength.db` never gets pushed** — `.gitignore` excludes it.
Only the small JSON snapshots go public.

## How the score is built

Same formula for both views (see `scoring.py`):

| Signal | Points |
|---|---|
| Price above 21 EMA | +10 |
| Price above 50 EMA | +10 |
| Price above 200 EMA | +10 |
| Bullish EMA stack (21>50>200) | +15 |
| 21 EMA sloping up | +5 |
| Extended >12% above 21 EMA | −10 |
| Breadth level (scaled) | up to +25 |
| Breadth rising vs 1 week ago | +10 |
| RS ratio above its own 21 EMA | +10 |
| RS ratio rising vs 1 week ago | +5 |

## The synthetic index (Basic Industry view only)

NSE publishes real index prices for your 16 tracked sectors (Nifty Auto,
Nifty Bank, etc.) going back decades. They don't do this for all 197
Basic Industry categories — that classification only exists to tag
individual stocks, not as tradable indices.

So for the Basic Industry view, we build our own: an **equal-weighted**
index (every stock counts the same — we don't have free market-cap data
to weight by size) computed from the average daily return across that
industry's stocks, compounded into an index level starting at 1000. It's
a standard, legitimate technique — it's just not an NSE-published number,
which is why the UI marks these as synthetic and the site shows a note
banner on that tab.

Industries with fewer than `MIN_STOCKS_PER_BASIC_INDUSTRY` (default: 5,
in `config.py`) stocks with price history are left out entirely — a
breadth or EMA reading from 2-3 stocks isn't statistically meaningful.

## Files

```
config.py                   sectors, industry mappings, thresholds — edit here first
db.py                        SQLite schema/connection (includes classification_meta,
                               which tracks whether basic_industry_map is the coarse
                               CSV fallback or the real Playwright classification)
scoring.py                   shared EMA/breadth/RS/score math (used by both views)
fetch_data.py                 daily price puller — full universe, run daily
                                (also fetches the coarse fallback classification, once)
classify_via_screener.py      RECOMMENDED — ~188-category classification via
                                screener.in's public pages, actually works
classify_industries_playwright.py   full 2,700-stock/197-category coverage via a
                                      real browser — currently blocked at the API
                                      level even with a genuine Chrome session, see
                                      that file's docstring for current status
classify_industries.py        deprecated — plain-HTTP attempt, confirmed blocked by
                                Akamai even with curl_cffi impersonation; kept for reference
compute.py                    scores your 16 tracked sectors (real NSE indices)
compute_basic_industry.py     scores all qualifying Basic Industries (synthetic indices);
                                compute_all_with_meta() wraps results with which
                                classification source is currently active
export_snapshot.py            writes docs/data/*.json — run after fetch_data.py
app.py                        local preview server (optional, not needed for hosting)
find_missing_filenames.py     one-off helper if an NSE constituent URL 404s
inspect_total_market.py       one-off helper to inspect the Total Market industry file
docs/                         the site itself — push this repo, point GitHub Pages at /docs
  index.html, style.css, app.js   the dashboard (two tabs, no build step, no dependencies).
                                    The "All Industries" tab shows a banner honestly stating
                                    whether it's the coarse fallback or the real 197-category
                                    data — no manual updating needed, it reads the source
                                    straight from the exported JSON.
  data/leaderboard.json           sector view data — from compute.py
  data/basic_industries.json      { classification_source, industries: [...] } — from
                                    compute_basic_industry.compute_all_with_meta()
```

## Extending it

- **Add a sector**: add an entry to `SECTORS` in `config.py`.
- **Change the min stock count for Basic Industries**: `MIN_STOCKS_PER_BASIC_INDUSTRY` in `config.py`.
- **Change EMA extension threshold, lookback windows, etc.**: all in `config.py`.
- **Different breadth MA**: `breadth_block()` in `scoring.py` hardcodes a 10-day MA.
