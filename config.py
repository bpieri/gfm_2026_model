# config.py
import os
from dotenv import load_dotenv

load_dotenv()


def _get_secret(key):
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key)
    except Exception:
        return None


EIA_API_KEY  = _get_secret("EIA_API_KEY")
FRED_API_KEY = _get_secret("FRED_API_KEY")

GALLONS_PER_BARREL = 42
FEDERAL_TAX_GAS    = 0.184
FEDERAL_TAX_DIESEL = 0.244

# ── Full Yield defaults — expressed as DECIMAL fractions of one barrel ────────
# These sum to 0.93 — the remaining 0.07 is refinery use / losses
# YIELD_DEFAULTS = {
#     "gasoline":    0.465,   # 46.5%
#     "ulsd":        0.286,   # 28.6%
#     "jet":         0.095,   #  9.5%
#     "bunker":      0.048,   #  4.8%
#     "asphalt":     0.036,   #  3.6%
#     "refinery_use":0.060,   #  6.0% — consumed, reduces saleable yield
# }

YIELD_DEFAULTS = {
    "gasoline":     0.445,
    "ulsd":         0.290,
    "jet":          0.110,
    "bunker":       0.035,
    "asphalt":      0.025,
    "lpg_other":    0.040,   # LPG, NGLs, petrochemical feed, misc — EIA residual
    "refinery_use": 0.055,
}

SPECIALTY_DEFAULTS = {
    "jet_gal":     5.75,
    "bunker_gal":  3.16,
    "asphalt_gal": 2.85,
    "lpg_gal":     0.95,    # Mont Belvieu propane proxy — WTI×0.50÷42 ≈ $0.95–$1.10
}

# ── Location definitions ──────────────────────────────────────────────────────
# light_diff / heavy_diff / catfeed_diff : crude diffs vs WTI ($/bbl)
# gas_diff / diesel_diff                 : product diffs vs NYMEX ($/gal)

LOCATIONS = [
    {
        "display":       "Alaska — Port Mackenzie",
        "aaa_metro":     "Anchorage",
        "aaa_state":     "AK",
        "light_diff":    12.00,
        "heavy_diff":     8.00,
        "catfeed_diff":   4.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Greenport — Austin, TX",
        "aaa_metro":     "Austin-San Marcos",
        "aaa_state":     "TX",
        "light_diff":     0.00,
        "heavy_diff":    -1.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Victoria, TX",
        "aaa_metro":     "Victoria",
        "aaa_state":     "TX",
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   7.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Duncan, OK",
        "aaa_metro":     "Lawton",
        "aaa_state":     "OK",
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Dewey, OK",
        "aaa_metro":     "Tulsa",
        "aaa_state":     "OK",
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "North Dakota — Stampede",
        "aaa_metro":     "Minot",
        "aaa_state":     "ND",
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Big Spring, TX",
        "aaa_metro":     "Midland",
        "aaa_state":     "TX",
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Utah",
        "aaa_metro":     "Salt Lake City",
        "aaa_state":     "UT",
        "light_diff":    -3.00,
        "heavy_diff":    -7.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "SE New Mexico",
        "aaa_metro":     "Odessa",
        "aaa_state":     "TX",
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Louisiana",
        "aaa_metro":     "Lafayette",
        "aaa_state":     "LA",
        "light_diff":     2.00,
        "heavy_diff":     0.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
    },
    {
        "display":       "Edmonton, Alberta",
        "aaa_metro":     None,
        "aaa_state":     None,
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
        "manual_gas":    3.80,
        "manual_diesel": 4.20,
    },
    {
        "display":       "Puerto Rico",
        "aaa_metro":     None,
        "aaa_state":     None,
        "light_diff":     0.00,
        "heavy_diff":    -3.00,
        "catfeed_diff":   5.00,
        "gas_diff":       0.00,
        "diesel_diff":    0.00,
        "manual_gas":    4.80,
        "manual_diesel": 5.20,
    },
]

# # config.py
# import os
# from dotenv import load_dotenv

# load_dotenv()

# def _get_secret(key):
#     val = os.getenv(key)
#     if val:
#         return val
#     try:
#         import streamlit as st
#         return st.secrets.get(key)
#     except Exception:
#         return None

# EIA_API_KEY  = _get_secret("EIA_API_KEY")
# FRED_API_KEY = _get_secret("FRED_API_KEY")

# # config.py
# # Rogue Refinery Economics — site-specific margin model
# # Location presets, crude differentials, yield defaults

# # ── Location definitions ──────────────────────────────────────────────────────
# # Each location has:
# #   display       : shown in UI
# #   aaa_metro     : exact AAA metro name for gas/diesel prices
# #   aaa_state     : fallback state if metro scrape fails
# #   light_diff    : light crude diff to WTI ($/bbl)
# #   heavy_diff    : heavy crude diff to WTI ($/bbl)
# #   catfeed_diff  : cat feed diff to WTI ($/bbl)

# LOCATIONS = [
#     {
#         "display":      "Alaska — Port Mackenzie",
#         "aaa_metro":    "Anchorage",
#         "aaa_state":    "AK",
#         "light_diff":   12.00,
#         "heavy_diff":   8.00,
#         "catfeed_diff": 4.00,
#     },
#     {
#         "display":      "Greenport — Austin, TX",
#         "aaa_metro":    "Austin-San Marcos",
#         "aaa_state":    "TX",
#         "light_diff":   0.00,
#         "heavy_diff":   -1.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "Victoria, TX",
#         "aaa_metro":    "Victoria",
#         "aaa_state":    "TX",
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 7.00,
#     },
#     {
#         "display":      "Duncan, OK",
#         "aaa_metro":    "Lawton",   # nearest AAA metro
#         "aaa_state":    "OK",
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "Dewey, OK",
#         "aaa_metro":    "Tulsa",    # nearest AAA metro
#         "aaa_state":    "OK",
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "North Dakota — Stampede",
#         "aaa_metro":    "Minot",
#         "aaa_state":    "ND",
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "Big Spring, TX",
#         "aaa_metro":    "Midland",  # nearest AAA metro
#         "aaa_state":    "TX",
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "Utah",
#         "aaa_metro":    "Salt Lake City",
#         "aaa_state":    "UT",
#         "light_diff":   -3.00,
#         "heavy_diff":   -7.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "SE New Mexico",
#         "aaa_metro":    "Odessa",   # nearest AAA metro (TX but closest)
#         "aaa_state":    "NM",
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "Louisiana",
#         "aaa_metro":    "Lafayette",
#         "aaa_state":    "LA",
#         "light_diff":   2.00,
#         "heavy_diff":   0.00,
#         "catfeed_diff": 5.00,
#     },
#     {
#         "display":      "Edmonton, Alberta",
#         "aaa_metro":    None,       # Canada — no AAA data, manual input
#         "aaa_state":    None,
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#         "manual_gas":   3.80,       # CAD-to-USD converted estimate $/gal
#         "manual_diesel": 4.20,
#     },
#     {
#         "display":      "Puerto Rico",
#         "aaa_metro":    None,       # PR — no AAA data, manual input
#         "aaa_state":    None,
#         "light_diff":   0.00,
#         "heavy_diff":   -3.00,
#         "catfeed_diff": 5.00,
#         "manual_gas":   4.80,       # PR typically ~$1 premium to mainland
#         "manual_diesel": 5.20,
#     },
# ]

# # ── Full Yield defaults ───────────────────────────────────────────────────────
# # Standard US refinery yield fractions (gallons per barrel of crude)
# YIELD_DEFAULTS = {
#     "gasoline": 19.5,
#     "ulsd":     12.0,
#     "jet":       4.0,
#     "bunker":    2.0,
#     "asphalt":   1.5,
# }

# # Default specialty product prices ($/gal) — overridden by live EIA/FRED
# SPECIALTY_DEFAULTS = {
#     "jet_gal":     4.07,   # EIA Gulf Coast Jet A spot
#     "bunker_gal":  2.52,   # ULSD × 0.70 proxy
#     "asphalt_gal": 2.16,   # ULSD × 0.60 proxy
# }

# # ── Unit constants ────────────────────────────────────────────────────────────
# GALLONS_PER_BARREL = 42
# FEDERAL_TAX_GAS    = 0.184
# FEDERAL_TAX_DIESEL = 0.244

# # ── Forward curve months to display ──────────────────────────────────────────
# # yfinance contract month codes
# FORWARD_MONTHS = 12   # show 12 months of forward curve