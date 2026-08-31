"""
Central config: which sectors to track, and where NSE publishes the data for each.

If NSE changes a filename/URL (they do, occasionally), you only need to fix it here.
"""

NSE_BASE = "https://archives.nseindia.com"
OLD_INDICES_PATH = f"{NSE_BASE}/content/indices/"
NEW_INDICES_PATH = "https://www.niftyindices.com/IndexConstituent/"

# Sector display name -> (index name as it appears in NSE's ind_close_all_DDMMYYYY.csv,
#                          FULL constituent list CSV url)
# Older/established sectoral indices are published under archives.nseindia.com;
# newer ones (e.g. Chemicals, launched 2025) are published under niftyindices.com
# with a slightly different filename convention -- hence full URLs here rather
# than just filenames.
SECTORS = {
    "Auto":               ("NIFTY AUTO",               OLD_INDICES_PATH + "ind_niftyautolist.csv"),
    "Bank":                ("NIFTY BANK",                OLD_INDICES_PATH + "ind_niftybanklist.csv"),
    "IT":                  ("NIFTY IT",                  OLD_INDICES_PATH + "ind_niftyitlist.csv"),
    "Pharma":              ("NIFTY PHARMA",              OLD_INDICES_PATH + "ind_niftypharmalist.csv"),
    "Metal":               ("NIFTY METAL",               OLD_INDICES_PATH + "ind_niftymetallist.csv"),
    "FMCG":                ("NIFTY FMCG",                OLD_INDICES_PATH + "ind_niftyfmcglist.csv"),
    "Energy":              ("NIFTY ENERGY",              OLD_INDICES_PATH + "ind_niftyenergylist.csv"),
    "Realty":              ("NIFTY REALTY",              OLD_INDICES_PATH + "ind_niftyrealtylist.csv"),
    "Media":               ("NIFTY MEDIA",               OLD_INDICES_PATH + "ind_niftymedialist.csv"),
    "PSU Bank":            ("NIFTY PSU BANK",            OLD_INDICES_PATH + "ind_niftypsubanklist.csv"),
    "Financial Services":  ("NIFTY FINANCIAL SERVICES",  OLD_INDICES_PATH + "ind_niftyfinancelist.csv"),
    "Consumer Durables":   ("NIFTY CONSUMER DURABLES",   OLD_INDICES_PATH + "ind_niftyconsumerdurableslist.csv"),
    "Oil & Gas":           ("NIFTY OIL & GAS",           OLD_INDICES_PATH + "ind_niftyoilgaslist.csv"),
    "Healthcare":          ("NIFTY HEALTHCARE INDEX",    OLD_INDICES_PATH + "ind_niftyhealthcarelist.csv"),
    "Consumption":         ("NIFTY INDIA CONSUMPTION",   OLD_INDICES_PATH + "ind_niftyconsumptionlist.csv"),
    # PLACEHOLDER -- run find_missing_filenames.py and paste the working URL here.
    "Chemicals":           ("NIFTY CHEMICALS",           NEW_INDICES_PATH + "ind_niftychemicals_list.csv"),
    # Verified via find_telecom_index.py: index name in ind_close_all csv is
    # "Nifty Telecommunications" (matched here in uppercase, since
    # update_index_prices() uppercases before comparing).
    "Telecom":             ("NIFTY TELECOMMUNICATIONS", NEW_INDICES_PATH + "ind_niftytelecommunications_list.csv"),
}

# Broader breadth via NSE's Nifty Total Market list (~750 stocks, tagged by
# NSE's own 22-category Industry classification). Only sectors with a clean
# 1:1 match to one of those 22 categories are listed here -- breadth for
# these sectors is computed over ALL Total Market stocks in that industry,
# not just the ~15-20 in the official sectoral index. Sectors NOT listed
# here (Bank, PSU Bank, Pharma, Healthcare, Energy, Consumption) keep using
# only their official sectoral index constituents, because this 22-category
# classification is too coarse to split them out accurately (e.g. it lumps
# Pharma in with hospitals/diagnostics under one "Healthcare" bucket, and
# Banks in with NBFCs/insurers under one "Financial Services" bucket).
TOTAL_MARKET_URL = NEW_INDICES_PATH + "ind_niftytotalmarket_list.csv"

SECTOR_TO_BROAD_INDUSTRY = {
    "Auto":               "Automobile and Auto Components",
    "IT":                  "Information Technology",
    "Metal":               "Metals & Mining",
    "Realty":              "Realty",
    "FMCG":                "Fast Moving Consumer Goods",
    "Consumer Durables":   "Consumer Durables",
    "Financial Services":  "Financial Services",
    "Oil & Gas":           "Oil Gas & Consumable Fuels",
    "Media":               "Media Entertainment & Publication",
    "Chemicals":           "Chemicals",
    "Telecom":             "Telecommunication",
}

BENCHMARK = "NIFTY 50"

# How much history to keep
INDEX_HISTORY_DAYS = 300     # need ~200+ trading days for the 200 EMA
STOCK_HISTORY_DAYS = 300     # bumped from 60 -- basic-industry synthetic indices
                              # also need ~200+ days for their own 200 EMA

DB_PATH = "sector_strength.db"

# Extension thresholds used for flags in the UI (tune to taste)
EXTENDED_FROM_21EMA_PCT = 12.0   # flag sector if index > 12% above its 21 EMA

# Full list of every NSE-listed equity symbol (used by the OPTIONAL, harder
# classify_industries.py path -- see that file's docstring)
EQUITY_MASTER_URL = f"{NSE_BASE}/content/equities/EQUITY_L.csv"

# PRIMARY industry classification source: NSE's Nifty 500 constituent list
# uses an older, much finer-grained "Industry" column (e.g. "FERTILISERS &
# PESTICIDES", "CEMENT & CEMENT PRODUCTS" -- ~70+ categories) than the
# 22-category Total Market file. It's a plain CSV, same reliable pattern as
# everything else in this project -- unlike the per-stock quote API, it's
# NOT behind Akamai bot protection. Covers ~500 stocks (top 500 by market
# cap), not the full universe, but with real granularity and zero risk of
# getting blocked.
NIFTY500_INDUSTRY_URL = OLD_INDICES_PATH + "ind_nifty500list.csv"

# A basic industry needs at least this many stocks with price history to be
# shown at all -- below this, breadth/EMA/RS numbers aren't statistically
# meaningful (e.g. a "72% breadth" from 2 stocks means almost nothing).
MIN_STOCKS_PER_BASIC_INDUSTRY = 5

# Separate, higher bar just for the UI's low-sample flag on the breadth
# stock count. A category can clear MIN_STOCKS_PER_BASIC_INDUSTRY (be shown
# at all) while still being too thin to fully trust -- this is the line
# where the stock-count next to breadth gets visually flagged, not where
# the row disappears.
LOW_SAMPLE_THRESHOLD = 10

# % of stocks above their own 21-day MA at or above which breadth is
# flagged as "overheated" -- almost the whole group has already moved,
# which is a crowded/late signal rather than a strength signal. Meant to
# be rare (like EXTENDED_FROM_21EMA_PCT), not a routine reading.
OVERHEATED_BREADTH_PCT = 90.0
