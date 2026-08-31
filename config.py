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
    # Verified via find_new_sector_indices.py:
    "Cement":              ("NIFTY CEMENT",             NEW_INDICES_PATH + "ind_niftycement_list.csv"),
    "Capital Goods":       ("NIFTY CAPITAL GOODS",      NEW_INDICES_PATH + "ind_niftycapitalgoods_list.csv"),
    "Power":               ("NIFTY POWER",              NEW_INDICES_PATH + "ind_niftypower_list.csv"),
    "NBFC":                ("NIFTY NBFC",               NEW_INDICES_PATH + "ind_niftynbfc_list.csv"),
    "Insurance":           ("NIFTY INSURANCE",          NEW_INDICES_PATH + "ind_niftyinsurance_list.csv"),
    # Verified via check_defence_variants.py: the ind_close_all file has TWO
    # Defence-related indices -- "Nifty India Defence" (cap-weighted) and
    # "Nifty India Defence Equal Weight" (a separate variant). The working
    # constituent URL (ind_niftyindiadefence_list.csv, no "equal weight" in
    # the filename) pairs with the plain cap-weighted one, consistent with
    # every other index here using the plain name for the base filename.
    "Defence":             ("NIFTY INDIA DEFENCE",      NEW_INDICES_PATH + "ind_niftyindiadefence_list.csv"),
    # Verified via find_private_bank_index_v2.py: unlike the other new
    # sectors, this one lives on the OLDER archives.nseindia.com path (same
    # as Bank/PSU Bank), with an underscore in an unusual spot in the
    # filename. Every niftyindices.com guess for this one returned a 200
    # but was actually the site's generic app shell HTML, not real data --
    # worth remembering that a 200 status there isn't proof of a real file.
    "Private Bank":        ("NIFTY PRIVATE BANK",       OLD_INDICES_PATH + "ind_nifty_privatebanklist.csv"),
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

# Second regime banner -- you trade mostly mid/smallcap, so Nifty 50's
# large-cap regime alone doesn't tell you the regime of the space you
# actually trade. Shown alongside Nifty 50, not instead of it -- the
# divergence between the two is itself informative.
MIDSMALL_INDEX = "NIFTY MIDSMALLCAP 400"

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

# FALLBACK industry classification source (only used if you skip
# classify_via_screener.py -- see fetch_data.py's update_nifty500_industries()).
# CORRECTED: this file's Industry column is NOT the older, finer-grained
# scheme (things like "FERTILISERS & PESTICIDES") -- live testing showed
# NSE retired that scheme before Nov 2024, and this file now uses the same
# coarse ~22-category scheme as the Total Market file (used for sector
# breadth widening above). It's still a plain CSV, not behind Akamai, so
# it's a reasonable ~500-stock fallback -- just not genuinely finer detail.
# The real primary source is classify_via_screener.py (~186 categories,
# ~2,500 stocks, via screener.in's public pages) -- run that instead.
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
