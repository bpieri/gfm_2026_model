# engine/location_margins.py
from engine.crack import crack_321, crack_211, crack_532, crack_full

# Federal excise taxes — unchanged since Oct 1, 1993
FEDERAL_TAX_GAS    = 0.184   # $/gallon
FEDERAL_TAX_DIESEL = 0.244   # $/gallon

# State motor fuel taxes — excise + fees, $/gallon
# Source: Federation of Tax Administrators + EIA, rates as of July 2025
# These are the total state-level per-gallon charges (excise + environmental
# fees + other per-gallon levies). Does NOT include local/county taxes
# or sales taxes on fuel.
STATE_TAXES = {
    # ── States covering our 12 locations ─────────────────────────────────────
    "AK": {"gas": 0.0895, "diesel": 0.0895},  # Alaska — lowest in US
    "TX": {"gas": 0.200,  "diesel": 0.200},   # Texas — flat rate
    "OK": {"gas": 0.190,  "diesel": 0.190},   # Oklahoma
    "ND": {"gas": 0.230,  "diesel": 0.230},   # North Dakota
    "UT": {"gas": 0.385,  "diesel": 0.385},   # Utah — updated Jul 2025
    "LA": {"gas": 0.200,  "diesel": 0.200},   # Louisiana
    "NM": {"gas": 0.229,  "diesel": 0.270},   # New Mexico — incl. loading fee

    # ── Additional states (for completeness / future locations) ───────────────
    "AL": {"gas": 0.300,  "diesel": 0.300},
    "AR": {"gas": 0.247,  "diesel": 0.285},
    "AZ": {"gas": 0.180,  "diesel": 0.260},
    "CA": {"gas": 0.596,  "diesel": 0.454},   # excise only (not cap-and-trade)
    "CO": {"gas": 0.220,  "diesel": 0.205},
    "CT": {"gas": 0.524,  "diesel": 0.489},   # variable; Jul 2025 rate
    "DC": {"gas": 0.235,  "diesel": 0.235},
    "DE": {"gas": 0.230,  "diesel": 0.220},
    "FL": {"gas": 0.373,  "diesel": 0.382},
    "GA": {"gas": 0.331,  "diesel": 0.371},
    "HI": {"gas": 0.160,  "diesel": 0.160},   # excise only; counties add more
    "ID": {"gas": 0.330,  "diesel": 0.330},
    "IL": {"gas": 0.470,  "diesel": 0.545},   # Jul 2025 rate
    "IN": {"gas": 0.350,  "diesel": 0.590},   # variable; Jan 2025 rate
    "IA": {"gas": 0.300,  "diesel": 0.325},
    "KS": {"gas": 0.240,  "diesel": 0.260},
    "KY": {"gas": 0.264,  "diesel": 0.234},   # variable; Jan 2025
    "ME": {"gas": 0.300,  "diesel": 0.312},
    "MD": {"gas": 0.461,  "diesel": 0.478},
    "MA": {"gas": 0.240,  "diesel": 0.240},
    "MI": {"gas": 0.310,  "diesel": 0.310},
    "MN": {"gas": 0.319,  "diesel": 0.319},   # updated Jan 2025
    "MS": {"gas": 0.184,  "diesel": 0.184},
    "MO": {"gas": 0.270,  "diesel": 0.270},
    "MT": {"gas": 0.330,  "diesel": 0.298},
    "NE": {"gas": 0.304,  "diesel": 0.304},
    "NV": {"gas": 0.238,  "diesel": 0.278},
    "NH": {"gas": 0.238,  "diesel": 0.238},
    "NJ": {"gas": 0.449,  "diesel": 0.538},
    "NY": {"gas": 0.246,  "diesel": 0.246},   # state excise only
    "NC": {"gas": 0.403,  "diesel": 0.403},
    "OH": {"gas": 0.385,  "diesel": 0.470},
    "OR": {"gas": 0.380,  "diesel": 0.380},
    "PA": {"gas": 0.576,  "diesel": 0.741},   # highest diesel in US
    "RI": {"gas": 0.340,  "diesel": 0.340},
    "SC": {"gas": 0.280,  "diesel": 0.280},
    "SD": {"gas": 0.280,  "diesel": 0.280},
    "TN": {"gas": 0.260,  "diesel": 0.270},
    "VT": {"gas": 0.317,  "diesel": 0.330},
    "VA": {"gas": 0.308,  "diesel": 0.318},
    "WA": {"gas": 0.494,  "diesel": 0.494},   # Jan 2025; note: large increase
    "WV": {"gas": 0.357,  "diesel": 0.357},
    "WI": {"gas": 0.309,  "diesel": 0.309},
    "WY": {"gas": 0.240,  "diesel": 0.240},
}


def _state_tax(state: str, fuel: str) -> float:
    """Return state excise tax in $/gal. Defaults to $0.300 if state unknown."""
    return STATE_TAXES.get(state or "", {}).get(fuel, 0.300)


def compute_location_margins(
    locations:        list,
    spot_prices:      dict,
    location_prices:  dict,
    specialty:        dict,
    yields:           dict,
    dist_margin_gal:  float = 0.35,
    gas_diff_override: float = None,
    diesel_diff_override: float = None,
) -> list:
    """
    Compute the full price waterfall and all spread formulas for every location.

    Price waterfall per location:
        retail_gas              AAA pump price ($/gal)
        − federal_tax_gas       $0.184/gal (fixed)
        − state_tax_gas         varies by state ($/gal)
        = pretax_gas            implied pre-tax price
        − dist_margin_gal       distribution + retail margin ($/gal)
        = wholesale_gas         implied wholesale / refinery gate price
        → adj_gas               NYMEX RBOB anchored + local delta + product diff

    Yield fractions must be expressed as decimals (0.465 = 46.5%).
    """
    wti_spot  = spot_prices.get("wti_bbl")
    rbob_spot = spot_prices.get("rbob_gal")
    ulsd_spot = spot_prices.get("ulsd_gal")

    if not wti_spot or not rbob_spot or not ulsd_spot:
        return []

    # Specialty with proxies
    jet     = specialty.get("jet_gal")     or ulsd_spot * 1.05
    bunker  = specialty.get("bunker_gal")  or ulsd_spot * 0.70
    asphalt = specialty.get("asphalt_gal") or ulsd_spot * 0.60

    rows = []
    for loc in locations:
        display      = loc["display"]
        state        = loc.get("aaa_state", "")
        light_diff   = loc.get("light_diff",   0.0)
        heavy_diff   = loc.get("heavy_diff",   0.0)
        catfeed_diff = loc.get("catfeed_diff", 0.0)

        loc_gas_diff    = loc.get("gas_diff",    0.0)
        loc_diesel_diff = loc.get("diesel_diff", 0.0)

        if gas_diff_override is not None:
            loc_gas_diff    = gas_diff_override
        if diesel_diff_override is not None:
            loc_diesel_diff = diesel_diff_override

        crude_light   = wti_spot + light_diff
        crude_heavy   = wti_spot + heavy_diff
        crude_catfeed = wti_spot + catfeed_diff

        lp            = location_prices.get(display, {})
        retail_gas    = lp.get("regular")
        retail_diesel = lp.get("diesel")
        source        = lp.get("source", "No data")

        if not retail_gas:
            rows.append({
                "display": display, "source": source,
                "state": state,
                "retail_gas": None, "retail_diesel": None,
                "pretax_gas": None, "pretax_diesel": None,
                "wholesale_gas": None, "wholesale_diesel": None,
                "crude_light": crude_light,
                "crude_heavy": crude_heavy,
                "crude_catfeed": crude_catfeed,
                "spread_321": None, "spread_211": None,
                "spread_532": None, "spread_full": None,
                "federal_tax_gas":  FEDERAL_TAX_GAS,
                "federal_tax_diesel": FEDERAL_TAX_DIESEL,
                "state_tax_gas":    _state_tax(state, "gas"),
                "state_tax_diesel": _state_tax(state, "diesel"),
                "total_tax_gas":    FEDERAL_TAX_GAS + _state_tax(state, "gas"),
                "total_tax_diesel": FEDERAL_TAX_DIESEL + _state_tax(state, "diesel"),
                "dist_margin": dist_margin_gal,
            })
            continue

        # ── Price waterfall ───────────────────────────────────────────────────
        fed_gas       = FEDERAL_TAX_GAS
        fed_diesel    = FEDERAL_TAX_DIESEL
        st_gas        = _state_tax(state, "gas")
        st_diesel     = _state_tax(state, "diesel")
        total_tax_gas = fed_gas + st_gas
        total_tax_die = fed_diesel + st_diesel

        pretax_gas    = max(retail_gas    - total_tax_gas,    0.10)
        retail_diesel = retail_diesel or retail_gas * 1.10
        pretax_diesel = max(retail_diesel - total_tax_die,    0.10)

        wholesale_gas    = max(pretax_gas    - dist_margin_gal, 0.05)
        wholesale_diesel = max(pretax_diesel - dist_margin_gal, 0.05)

        adj_gas    = rbob_spot + (wholesale_gas    - rbob_spot) + loc_gas_diff
        adj_diesel = ulsd_spot + (wholesale_diesel - ulsd_spot) + loc_diesel_diff

        lpg = specialty.get("lpg_gal") or ulsd_spot * 0.25

        # ── Crack spreads ─────────────────────────────────────────────────────
        s321  = round(crack_321(crude_light, adj_gas, adj_diesel), 2)
        s211  = round(crack_211(crude_light, adj_gas, adj_diesel), 2)
        s532  = round(crack_532(crude_light, adj_gas, adj_diesel), 2)
        sfull = round(crack_full(
            crude_light, adj_gas, adj_diesel,
            jet, bunker, asphalt, lpg, yields
        ), 2)

        rows.append({
            "display":            display,
            "source":             source,
            "state":              state,
            # ── Waterfall ──
            "retail_gas":         round(retail_gas,       3),
            "retail_diesel":      round(retail_diesel,    3),
            "federal_tax_gas":    round(fed_gas,          3),
            "federal_tax_diesel": round(fed_diesel,       3),
            "state_tax_gas":      round(st_gas,           3),
            "state_tax_diesel":   round(st_diesel,        3),
            "total_tax_gas":      round(total_tax_gas,    3),
            "total_tax_diesel":   round(total_tax_die,    3),
            "pretax_gas":         round(pretax_gas,       3),
            "pretax_diesel":      round(pretax_diesel,    3),
            "dist_margin":        round(dist_margin_gal,  3),
            "wholesale_gas":      round(wholesale_gas,    3),
            "wholesale_diesel":   round(wholesale_diesel, 3),
            "loc_gas_diff":       round(loc_gas_diff,     3),
            "loc_diesel_diff":    round(loc_diesel_diff,  3),
            "adj_gas":            round(adj_gas,          3),
            "adj_diesel":         round(adj_diesel,       3),
            # ── Crude ──
            "crude_light":        round(crude_light,      2),
            "crude_heavy":        round(crude_heavy,      2),
            "crude_catfeed":      round(crude_catfeed,    2),
            # ── Results ──
            "spread_321":         s321,
            "spread_211":         s211,
            "spread_532":         s532,
            "spread_full":        sfull,
        })

    return rows

# # engine/location_margins.py
# from engine.crack import crack_321, crack_211, crack_532, crack_full

# FEDERAL_TAX_GAS    = 0.184   # $/gal — fixed since Oct 1993
# FEDERAL_TAX_DIESEL = 0.244   # $/gal — fixed since Oct 1993

# STATE_TAXES = {
#     "AK": {"gas": 0.090, "diesel": 0.090},
#     "TX": {"gas": 0.200, "diesel": 0.200},
#     "OK": {"gas": 0.190, "diesel": 0.190},
#     "ND": {"gas": 0.230, "diesel": 0.230},
#     "UT": {"gas": 0.364, "diesel": 0.364},
#     "LA": {"gas": 0.200, "diesel": 0.200},
#     "NM": {"gas": 0.170, "diesel": 0.210},
# }


# def _state_tax(state: str, fuel: str) -> float:
#     return STATE_TAXES.get(state or "", {}).get(fuel, 0.30)


# def compute_location_margins(
#     locations:        list,
#     spot_prices:      dict,
#     location_prices:  dict,
#     specialty:        dict,
#     yields:           dict,
#     dist_margin_gal:  float = 0.35,
#     gas_diff_override: float = None,
#     diesel_diff_override: float = None,
# ) -> list:
#     """
#     Compute the full price waterfall and all spread formulas for every location.

#     Yield fractions must be expressed as DECIMALS (0.465 = 46.5%).
#     Each location can carry its own crude_diff, gas_diff, diesel_diff from
#     config.py; these can be further overridden at the sidebar level.

#     Price waterfall per location:
#         retail_gas          AAA pump price
#         → pretax_gas        after federal + state excise taxes
#         → wholesale_gas     after distribution + retail margin
#         → adj_gas           NYMEX RBOB anchored + local delta + location gas diff

#     Returns list of dicts, one per location.
#     """
#     wti_spot  = spot_prices.get("wti_bbl")
#     rbob_spot = spot_prices.get("rbob_gal")
#     ulsd_spot = spot_prices.get("ulsd_gal")

#     if not wti_spot or not rbob_spot or not ulsd_spot:
#         return []

#     # Specialty with proxies
#     jet     = specialty.get("jet_gal")     or ulsd_spot * 1.05
#     bunker  = specialty.get("bunker_gal")  or ulsd_spot * 0.70
#     asphalt = specialty.get("asphalt_gal") or ulsd_spot * 0.60

#     rows = []
#     for loc in locations:
#         display      = loc["display"]
#         state        = loc.get("aaa_state", "")
#         light_diff   = loc.get("light_diff",   0.0)
#         heavy_diff   = loc.get("heavy_diff",   0.0)
#         catfeed_diff = loc.get("catfeed_diff", 0.0)

#         # Location-level product diffs (from config, overridable in sidebar)
#         loc_gas_diff    = loc.get("gas_diff",    0.0)
#         loc_diesel_diff = loc.get("diesel_diff", 0.0)

#         # Sidebar override takes precedence if provided
#         if gas_diff_override is not None:
#             loc_gas_diff    = gas_diff_override
#         if diesel_diff_override is not None:
#             loc_diesel_diff = diesel_diff_override

#         # Effective crude prices
#         crude_light   = wti_spot + light_diff
#         crude_heavy   = wti_spot + heavy_diff
#         crude_catfeed = wti_spot + catfeed_diff

#         # Retail prices from AAA
#         lp            = location_prices.get(display, {})
#         retail_gas    = lp.get("regular")
#         retail_diesel = lp.get("diesel")
#         source        = lp.get("source", "No data")

#         if not retail_gas:
#             rows.append({
#                 "display": display, "source": source,
#                 "retail_gas": None, "retail_diesel": None,
#                 "pretax_gas": None, "pretax_diesel": None,
#                 "wholesale_gas": None, "wholesale_diesel": None,
#                 "crude_light": crude_light,
#                 "crude_heavy": crude_heavy,
#                 "crude_catfeed": crude_catfeed,
#                 "spread_321": None, "spread_211": None,
#                 "spread_532": None, "spread_full": None,
#                 "state_tax_gas": None, "federal_tax_gas": FEDERAL_TAX_GAS,
#                 "dist_margin": dist_margin_gal,
#                 "loc_gas_diff": loc_gas_diff,
#                 "loc_diesel_diff": loc_diesel_diff,
#             })
#             continue

#         # ── Price waterfall ──────────────────────────────────────────────────
#         fed_gas      = FEDERAL_TAX_GAS
#         fed_diesel   = FEDERAL_TAX_DIESEL
#         st_gas       = _state_tax(state, "gas")
#         st_diesel    = _state_tax(state, "diesel")
#         total_tax_gas    = fed_gas    + st_gas
#         total_tax_diesel = fed_diesel + st_diesel

#         pretax_gas    = max(retail_gas    - total_tax_gas,    0.10)
#         retail_diesel = retail_diesel or retail_gas * 1.10
#         pretax_diesel = max(retail_diesel - total_tax_diesel, 0.10)

#         wholesale_gas    = max(pretax_gas    - dist_margin_gal, 0.05)
#         wholesale_diesel = max(pretax_diesel - dist_margin_gal, 0.05)

#         # Apply location product differentials on top of wholesale
#         adj_gas    = rbob_spot + (wholesale_gas    - rbob_spot) + loc_gas_diff
#         adj_diesel = ulsd_spot + (wholesale_diesel - ulsd_spot) + loc_diesel_diff

#         # ── Crack spreads ────────────────────────────────────────────────────
#         s321  = round(crack_321(crude_light, adj_gas, adj_diesel), 2)
#         s211  = round(crack_211(crude_light, adj_gas, adj_diesel), 2)
#         s532  = round(crack_532(crude_light, adj_gas, adj_diesel), 2)
#         sfull = round(crack_full(
#             crude_light, adj_gas, adj_diesel,
#             jet, bunker, asphalt, yields
#         ), 2)

#         rows.append({
#             "display":           display,
#             "source":            source,
#             "state":             state,
#             # ── Price waterfall ──
#             "retail_gas":        round(retail_gas,       3),
#             "retail_diesel":     round(retail_diesel,    3),
#             "federal_tax_gas":   round(fed_gas,          3),
#             "state_tax_gas":     round(st_gas,           3),
#             "total_tax_gas":     round(total_tax_gas,    3),
#             "pretax_gas":        round(pretax_gas,       3),
#             "pretax_diesel":     round(pretax_diesel,    3),
#             "dist_margin":       round(dist_margin_gal,  3),
#             "wholesale_gas":     round(wholesale_gas,    3),
#             "wholesale_diesel":  round(wholesale_diesel, 3),
#             "loc_gas_diff":      round(loc_gas_diff,     3),
#             "loc_diesel_diff":   round(loc_diesel_diff,  3),
#             "adj_gas":           round(adj_gas,          3),
#             "adj_diesel":        round(adj_diesel,       3),
#             # ── Crude prices ──
#             "crude_light":       round(crude_light,      2),
#             "crude_heavy":       round(crude_heavy,      2),
#             "crude_catfeed":     round(crude_catfeed,    2),
#             # ── Spread results ──
#             "spread_321":        s321,
#             "spread_211":        s211,
#             "spread_532":        s532,
#             "spread_full":       sfull,
#         })

#     return rows





# # engine/location_margins.py
# from engine.crack import crack_321, crack_211, crack_532, crack_full
# from config import GALLONS_PER_BARREL, FEDERAL_TAX_GAS, FEDERAL_TAX_DIESEL


# def compute_location_margins(
#     locations: list,
#     spot_prices: dict,
#     location_prices: dict,
#     specialty: dict,
#     yields: dict,
#     dist_margin_gal: float = 0.35,
# ) -> list:
#     """
#     Compute all spread formulas for every location.

#     Returns list of dicts, one per location, with:
#         display, crude_light, crude_heavy, crude_catfeed,
#         retail_gas, retail_diesel, wholesale_gas, wholesale_diesel,
#         spread_321, spread_211, spread_532, spread_full,
#         source
#     """
#     wti     = spot_prices.get("wti_bbl")
#     rbob    = spot_prices.get("rbob_gal")
#     ulsd    = spot_prices.get("ulsd_gal")

#     if not wti or not rbob or not ulsd:
#         return []

#     # Specialty with proxies
#     jet     = specialty.get("jet_gal")     or ulsd * 1.05
#     bunker  = specialty.get("bunker_gal")  or ulsd * 0.70
#     asphalt = specialty.get("asphalt_gal") or ulsd * 0.60

#     rows = []
#     for loc in locations:
#         display      = loc["display"]
#         light_diff   = loc["light_diff"]
#         heavy_diff   = loc["heavy_diff"]
#         catfeed_diff = loc["catfeed_diff"]

#         crude_light   = wti + light_diff
#         crude_heavy   = wti + heavy_diff
#         crude_catfeed = wti + catfeed_diff

#         # Get local retail prices
#         lp           = location_prices.get(display, {})
#         retail_gas   = lp.get("regular")
#         retail_diesel= lp.get("diesel")
#         source       = lp.get("source", "No data")

#         if not retail_gas:
#             rows.append({
#                 "display": display, "source": source,
#                 "retail_gas": None, "retail_diesel": None,
#                 "crude_light": crude_light, "crude_heavy": crude_heavy,
#                 "spread_321": None, "spread_211": None,
#                 "spread_532": None, "spread_full": None,
#             })
#             continue

#         # Strip taxes
#         state_tax_gas    = _state_tax(loc["aaa_state"], "gas")
#         state_tax_diesel = _state_tax(loc["aaa_state"], "diesel")
#         pretax_gas    = max(retail_gas    - FEDERAL_TAX_GAS    - state_tax_gas,    0.10)
#         pretax_diesel = max(retail_diesel - FEDERAL_TAX_DIESEL - state_tax_diesel, 0.10) if retail_diesel else pretax_gas * 1.10

#         # Strip distribution margin
#         wholesale_gas    = max(pretax_gas    - dist_margin_gal, 0.05)
#         wholesale_diesel = max(pretax_diesel - dist_margin_gal, 0.05)

#         # Regional anchor to NYMEX
#         adj_gas    = rbob + (wholesale_gas    - rbob)
#         adj_diesel = ulsd + (wholesale_diesel - ulsd)

#         rows.append({
#             "display":          display,
#             "source":           source,
#             "retail_gas":       round(retail_gas,       3),
#             "retail_diesel":    round(retail_diesel,    3) if retail_diesel else None,
#             "pretax_gas":       round(pretax_gas,       3),
#             "wholesale_gas":    round(wholesale_gas,    3),
#             "wholesale_diesel": round(wholesale_diesel, 3),
#             "crude_light":      round(crude_light,      2),
#             "crude_heavy":      round(crude_heavy,      2),
#             "crude_catfeed":    round(crude_catfeed,    2),
#             "spread_321":       round(crack_321(crude_light, adj_gas, adj_diesel), 2),
#             "spread_211":       round(crack_211(crude_light, adj_gas, adj_diesel), 2),
#             "spread_532":       round(crack_532(crude_light, adj_gas, adj_diesel), 2),
#             "spread_full":      round(crack_full(
#                 crude_light, adj_gas, adj_diesel,
#                 jet, bunker, asphalt, yields
#             ), 2),
#         })

#     return rows


# def _state_tax(state: str, fuel: str) -> float:
#     """
#     Average state excise tax per gallon.
#     Simplified table — major states for our 12 locations.
#     """
#     TAXES = {
#         "AK": {"gas": 0.090, "diesel": 0.090},
#         "TX": {"gas": 0.200, "diesel": 0.200},
#         "OK": {"gas": 0.190, "diesel": 0.190},
#         "ND": {"gas": 0.230, "diesel": 0.230},
#         "UT": {"gas": 0.364, "diesel": 0.364},
#         "LA": {"gas": 0.200, "diesel": 0.200},
#         "NM": {"gas": 0.170, "diesel": 0.210},
#     }
#     return TAXES.get(state or "", {}).get(fuel, 0.30)