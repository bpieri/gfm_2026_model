# fetchers/prices.py
import requests
import time
import io
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List
from bs4 import BeautifulSoup

# ── CME Forward Curve ─────────────────────────────────────────────────────────

# CME_XLSX_URL = "https://rogueng.duckdns.org/cme_excel/output.xlsx"
CME_XLSX_URL = "https://robotamp.pythonanywhere.com/data/new_pricing/output.xlsx"

MONTH_MAP = {
    "JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
    "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12,
}


def _parse_month_label(label: str) -> Optional[datetime]:
    """Convert 'NOV 26' → datetime(2026, 11, 1)."""
    try:
        parts = str(label).strip().upper().split()
        if len(parts) != 2:
            return None
        mo  = MONTH_MAP.get(parts[0])
        yr  = int(parts[1])
        yr  = yr + 2000 if yr < 100 else yr
        if not mo:
            return None
        return datetime(yr, mo, 1)
    except Exception:
        return None


def fetch_cme_forward_curve() -> Dict[str, List[Dict]]:
    """
    Download CME forward curve from the hosted Excel file.
    Parses wti ($/bbl), ulsd ($/gal), rbob ($/gal) sheets.
    Uses 'settle' column as the reference price.
    Returns only months with a valid non-zero settle price,
    limited to the next 24 months for display clarity.
    """
    try:
        r = requests.get(CME_XLSX_URL, timeout=20)
        r.raise_for_status()
        xls = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
    except Exception as e:
        print(f"  CME forward curve fetch failed: {e}")
        return {"wti": [], "ulsd": [], "rbob": []}

    today   = datetime.today()
    strips  = {}

    sheet_map = {
        "wti":  "wti",
        "ulsd": "ulsd",
        "rbob": "rbob",
    }

    for key, sheet_name in sheet_map.items():
        df = xls.get(sheet_name)
        if df is None:
            strips[key] = []
            continue

        df.columns = [str(c).strip().lower() for c in df.columns]
        if "month" not in df.columns or "settle" not in df.columns:
            strips[key] = []
            continue

        rows = []
        for _, row in df.iterrows():
            dt      = _parse_month_label(row["month"])
            settle  = row["settle"]
            if dt is None:
                continue
            if dt < today.replace(day=1):
                continue                          # skip expired months
            try:
                price = float(settle)
            except (ValueError, TypeError):
                continue
            if price <= 0:
                continue

            rows.append({
                "month":  dt.strftime("%b %Y"),
                "date":   dt.strftime("%Y-%m"),
                "dt":     dt,
                "price":  round(price, 4),
                "volume": int(row.get("volume", 0) or 0),
                "oi":     int(row.get("openinterest", 0) or 0),
            })

        # Sort by date, keep next 24 months
        rows.sort(key=lambda x: x["dt"])
        rows = rows[:24]
        # Drop dt — not JSON serialisable in cache
        for r in rows:
            r.pop("dt", None)
        strips[key] = rows

    return strips


def compute_forward_crack(
    strip: Dict[str, List[Dict]],
    crude_diff:   float = 0.0,
    gas_diff:     float = 0.0,
    diesel_diff:  float = 0.0,
    jet_fwd:      float = 4.07,
    bunker_fwd:   float = 2.52,
    asphalt_fwd:  float = 2.16,
    lpg_fwd:      float = 0.95,
    yields:       Dict  = None,
) -> List[Dict]:
    """
    Compute monthly forward crack spreads using CME settle prices
    plus location-specific differentials.

    crude_diff   $/bbl  added to WTI settle
    gas_diff     $/gal  added to RBOB settle
    diesel_diff  $/gal  added to ULSD settle

    Returns list of monthly dicts with:
        month, wti, rbob, ulsd, crack_321, crack_211, crack_532, crack_full
    """
    if yields is None:
        yields = {
            "gasoline": 0.465, "ulsd": 0.286,
            "jet": 0.095, "bunker": 0.048, "asphalt": 0.036,
        }

    wti_map  = {r["date"]: r["price"] for r in strip.get("wti",  [])}
    rbob_map = {r["date"]: r["price"] for r in strip.get("rbob", [])}
    ulsd_map = {r["date"]: r["price"] for r in strip.get("ulsd", [])}

    # Use the union of all available months
    all_dates = sorted(set(wti_map) | set(rbob_map) | set(ulsd_map))

    results = []
    for date in all_dates:
        wti_raw  = wti_map.get(date)
        rbob_raw = rbob_map.get(date)
        ulsd_raw = ulsd_map.get(date)

        if not wti_raw:
            continue

        wti   = wti_raw  + crude_diff
        rbob  = (rbob_raw  + gas_diff)    if rbob_raw  else None
        ulsd  = (ulsd_raw  + diesel_diff) if ulsd_raw  else None

        # Crack spreads — require at least wti + one product
        crack_321  = None
        crack_211  = None
        crack_532  = None
        crack_full = None

        if rbob and ulsd:
            crack_321  = round((2*rbob*42 + 1*ulsd*42 - 3*wti) / 3,  2)
            crack_211  = round((1*rbob*42 + 1*ulsd*42 - 2*wti) / 2,  2)
            crack_532  = round((3*rbob*42 + 2*ulsd*42 - 5*wti) / 5,  2)

            # Full yield using percentage fractions
            rev = (
                rbob      * yields.get("gasoline", 0.445) * 42 +
                ulsd      * yields.get("ulsd",     0.29) * 42 +
                jet_fwd   * yields.get("jet",      0.11) * 42 +
                bunker_fwd* yields.get("bunker",   0.035) * 42 +
                asphalt_fwd*yields.get("asphalt",  0.025) * 42 +
                lpg_fwd     * yields.get("lpg",    0.040) * 42
            )
            crack_full = round(rev - wti, 2)

        dt = datetime.strptime(date, "%Y-%m")
        results.append({
            "month":      dt.strftime("%b %Y"),
            "date":       date,
            "wti":        round(wti,  2),
            "rbob":       round(rbob, 4) if rbob else None,
            "ulsd":       round(ulsd, 4) if ulsd else None,
            "crack_321":  crack_321,
            "crack_211":  crack_211,
            "crack_532":  crack_532,
            "crack_full": crack_full,
        })

    return results


# ── Spot prices ───────────────────────────────────────────────────────────────

def fetch_spot_prices(eia_api_key: str = "") -> Dict[str, Optional[float]]:
    """
    WTI, RBOB, ULSD spot prices.
    Primary: derive from first month of CME strip (most liquid settle).
    Fallback: EIA API spot prices.
    """
    # Try CME strip first — most current settle price
    try:
        strip = fetch_cme_forward_curve()
        wti_rows  = strip.get("wti",  [])
        rbob_rows = strip.get("rbob", [])
        ulsd_rows = strip.get("ulsd", [])

        prices = {
            "wti_bbl":  wti_rows[0]["price"]  if wti_rows  else None,
            "rbob_gal": rbob_rows[0]["price"] if rbob_rows else None,
            "ulsd_gal": ulsd_rows[0]["price"] if ulsd_rows else None,
        }
        if all(v is not None for v in prices.values()):
            return prices
    except Exception as e:
        print(f"  CME spot derive failed: {e}")

    # EIA fallback
    prices = {"wti_bbl": None, "rbob_gal": None, "ulsd_gal": None}
    if eia_api_key:
        EIA_SPT = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

        def eia_spot(product, process, area, freq="daily"):
            try:
                params = [
                    ("api_key", eia_api_key), ("frequency", freq),
                    ("data[0]", "value"), ("facets[product][]", product),
                    ("facets[process][]", process), ("facets[duoarea][]", area),
                    ("sort[0][column]", "period"), ("sort[0][direction]", "desc"),
                    ("length", "3"),
                ]
                r    = requests.get(EIA_SPT, params=params, timeout=10)
                rows = r.json()["response"]["data"]
                return float(rows[0]["value"]) if rows else None
            except Exception:
                return None

        prices["wti_bbl"]  = eia_spot("EPC0",     "PF4", "Y35NY")
        prices["rbob_gal"] = eia_spot("EPMRR",    "PF4", "Y05LA")
        prices["ulsd_gal"] = eia_spot("EPD2DXL0", "PF4", "Y35NY")

    return prices


# ── Specialty products ────────────────────────────────────────────────────────

def fetch_specialty_prices(
    eia_api_key: str = "",
    fred_api_key: str = "",
) -> Dict[str, Optional[float]]:
    """Jet fuel, bunker, asphalt spot prices."""
    EIA_SPT = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

    def eia_spot(product, process, area, freq="weekly"):
        try:
            params = [
                ("api_key", eia_api_key), ("frequency", freq),
                ("data[0]", "value"), ("facets[product][]", product),
                ("facets[process][]", process), ("facets[duoarea][]", area),
                ("sort[0][column]", "period"), ("sort[0][direction]", "desc"),
                ("length", "3"),
            ]
            r    = requests.get(EIA_SPT, params=params, timeout=10)
            rows = r.json()["response"]["data"]
            return float(rows[0]["value"]) if rows else None
        except Exception:
            return None

    jet    = eia_spot("EPJK",  "PF4", "RGC")
    bunker = eia_spot("EPPR",  "PF4", "RGC")
    asph   = eia_spot("EPPA",  "PTE", "NUS", "monthly")

    return {
        "jet_gal":     jet,
        "bunker_gal":  bunker,
        "asphalt_gal": asph,
        "jet_src":     "EIA Gulf Coast" if jet    else "proxy",
        "bunker_src":  "EIA residual"   if bunker else "proxy",
        "asphalt_src": "EIA monthly"    if asph   else "proxy",
    }


# ── AAA metro prices ──────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
AAA_STATE_URL = "https://gasprices.aaa.com/?state={}"


def _scrape_state_metros(state_abbr: str) -> Dict[str, Dict]:
    url = AAA_STATE_URL.format(state_abbr)
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  AAA scrape failed ({state_abbr}): {e}")
        return {}

    soup   = BeautifulSoup(r.text, "html.parser")
    metros = {}

    for h3 in soup.find_all("h3"):
        name  = h3.get_text(strip=True)
        if not name or len(name) < 2:
            continue
        table = h3.find_next_sibling("table")
        if not table:
            sib = h3.find_next_sibling()
            if sib:
                table = sib.find("table")
        if not table:
            continue

        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            if "current" not in cols[0].get_text(strip=True).lower():
                continue

            def p(cell):
                try:
                    return float(cell.get_text(strip=True).replace("$", ""))
                except Exception:
                    return None

            metros[name] = {
                "regular":  p(cols[1]),
                "midgrade": p(cols[2]),
                "premium":  p(cols[3]),
                "diesel":   p(cols[4]),
                "state":    state_abbr,
            }
            break

    return metros


def fetch_location_prices(locations: list) -> Dict[str, Dict]:
    """Fetch AAA metro retail prices for all locations."""
    states_needed = set()
    for loc in locations:
        if loc.get("aaa_state"):
            states_needed.add(loc["aaa_state"])

    all_metro_prices = {}
    for state in sorted(states_needed):
        metros = _scrape_state_metros(state)
        all_metro_prices.update(metros)
        time.sleep(0.3)

    result = {}
    for loc in locations:
        display    = loc["display"]
        metro_name = loc.get("aaa_metro")

        if metro_name and metro_name in all_metro_prices:
            data   = all_metro_prices[metro_name]
            source = f"AAA Metro — {metro_name}"
        elif loc.get("manual_gas"):
            data   = {
                "regular":  loc["manual_gas"],
                "diesel":   loc["manual_diesel"],
                "midgrade": None,
                "premium":  None,
            }
            source = "Manual input"
        else:
            data   = {"regular": None, "diesel": None}
            source = "No data"

        result[display] = {**data, "source": source}

    return result







# # fetchers/prices.py
# # Fetches all price inputs needed for the refinery economics model:
# #   - WTI spot and forward strip (yfinance / EIA fallback)
# #   - RBOB gasoline spot and forward strip (yfinance)
# #   - ULSD/HO spot and forward strip (yfinance)
# #   - AAA metro gas and diesel prices for each location
# #   - Specialty product spot prices (EIA/FRED)

# import requests
# import time
# from datetime import datetime, timedelta
# from typing import Optional, Dict, List
# from bs4 import BeautifulSoup

# # ── Futures: spot + forward strip ─────────────────────────────────────────────

# def fetch_spot_prices() -> Dict[str, Optional[float]]:
#     """
#     Fetch WTI, RBOB, and ULSD spot prices.
#     Primary: yfinance. Fallback: EIA API.
#     Returns dict: wti_bbl, rbob_gal, ulsd_gal
#     """
#     prices = {}

#     # Try yfinance first
#     try:
#         import yfinance as yf
#         tickers = {"wti_bbl": "CL=F", "rbob_gal": "RB=F", "ulsd_gal": "HO=F"}
#         for key, ticker in tickers.items():
#             t    = yf.Ticker(ticker)
#             hist = t.history(period="5d")
#             prices[key] = float(hist["Close"].iloc[-1]) if not hist.empty else None
#         if all(v is not None for v in prices.values()):
#             return prices
#     except Exception:
#         pass

#     # EIA fallback
#     try:
#         # from config import EIA_API_KEY
#         import os
#         EIA_API_KEY = os.getenv("EIA_API_KEY", "")
#         EIA_SPT = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

#         def eia_spot(product, process, area, freq="daily"):
#             params = [
#                 ("api_key", EIA_API_KEY), ("frequency", freq),
#                 ("data[0]", "value"), ("facets[product][]", product),
#                 ("facets[process][]", process), ("facets[duoarea][]", area),
#                 ("sort[0][column]", "period"), ("sort[0][direction]", "desc"),
#                 ("length", "3"),
#             ]
#             r = requests.get(EIA_SPT, params=params, timeout=10)
#             rows = r.json()["response"]["data"]
#             return float(rows[0]["value"]) if rows else None

#         prices["wti_bbl"]  = prices.get("wti_bbl")  or eia_spot("EPC0",     "PF4", "Y35NY")
#         prices["rbob_gal"] = prices.get("rbob_gal") or eia_spot("EPMRR",    "PF4", "Y05LA")
#         prices["ulsd_gal"] = prices.get("ulsd_gal") or eia_spot("EPD2DXL0", "PF4", "Y35NY")
#     except Exception as e:
#         print(f"  EIA spot fallback failed: {e}")

#     return prices


# # def fetch_forward_strip() -> Dict[str, List[Dict]]:
# #     """
# #     Fetch WTI, RBOB, and ULSD forward curves via yfinance.
# #     Returns dict of lists, each entry: {month, date, price}

# #     yfinance contract naming:
# #         WTI:  CL + month_code + year (e.g. CLZ26 = Dec 2026)
# #         RBOB: RB + month_code + year
# #         ULSD: HO + month_code + year
# #     Month codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun
# #                  N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec
# #     """
# #     MONTH_CODES = {
# #         1:"F", 2:"G", 3:"H", 4:"J", 5:"K", 6:"M",
# #         7:"N", 8:"Q", 9:"U", 10:"V", 11:"X", 12:"Z"
# #     }

# #     try:
# #         import yfinance as yf
# #         strips = {"wti": [], "rbob": [], "ulsd": []}
# #         prefixes = {"wti": "CL", "rbob": "RB", "ulsd": "HO"}

# #         today   = datetime.today()
# #         # Start from next month
# #         start   = (today.replace(day=1) + timedelta(days=32)).replace(day=1)

# #         for i in range(12):
# #             month_dt = (start.replace(day=1) +
# #                         timedelta(days=32 * i)).replace(day=1)
# #             mo   = month_dt.month
# #             yr   = str(month_dt.year)[-2:]
# #             code = MONTH_CODES[mo]

# #             for product, prefix in prefixes.items():
# #                 ticker = f"{prefix}{code}{yr}=F"
# #                 try:
# #                     t    = yf.Ticker(ticker)
# #                     hist = t.history(period="3d")
# #                     if not hist.empty:
# #                         price = float(hist["Close"].iloc[-1])
# #                         strips[product].append({
# #                             "month": month_dt.strftime("%b %Y"),
# #                             "date":  month_dt.strftime("%Y-%m"),
# #                             "price": round(price, 3),
# #                         })
# #                 except Exception:
# #                     pass

# #         return strips

# #     except Exception as e:
# #         print(f"  Forward strip fetch failed: {e}")
# #         return {"wti": [], "rbob": [], "ulsd": []}

# def fetch_forward_strip(eia_api_key: str = "") -> dict:
#     """
#     Build a forward price curve using EIA historical data + spot prices.

#     Since yfinance doesn't reliably support individual monthly futures
#     contracts, we use:
#         WTI:  EIA weekly spot history → extrapolate flat forward
#         RBOB: Spot price held flat (no free forward curve available)
#         ULSD: Spot price held flat (no free forward curve available)

#     Returns dict of lists: {wti: [...], rbob: [...], ulsd: [...]}
#     Each entry: {month, date, price}
#     """
#     from datetime import datetime, timedelta

#     try:
#         # Get current spot prices
#         spot = fetch_spot_prices()
#         wti_spot  = spot.get("wti_bbl")
#         rbob_spot = spot.get("rbob_gal")
#         ulsd_spot = spot.get("ulsd_gal")

#         if not wti_spot:
#             return {"wti": [], "rbob": [], "ulsd": []}

#         # Try to get EIA WTI history to show recent trend
#         wti_history = []
#         if eia_api_key:
#             try:
#                 params = [
#                     ("api_key",            eia_api_key),
#                     ("frequency",          "weekly"),
#                     ("data[0]",            "value"),
#                     ("facets[product][]",  "EPC0"),
#                     ("facets[process][]",  "PF4"),
#                     ("facets[duoarea][]",  "Y35NY"),
#                     ("sort[0][column]",    "period"),
#                     ("sort[0][direction]", "desc"),
#                     ("length",             "52"),
#                 ]
#                 r    = requests.get(
#                     "https://api.eia.gov/v2/petroleum/pri/spt/data/",
#                     params=params, timeout=10
#                 )
#                 rows = r.json()["response"]["data"]
#                 for row in reversed(rows[:26]):  # last 6 months weekly
#                     wti_history.append({
#                         "month": row["period"],
#                         "date":  row["period"],
#                         "price": float(row["value"]),
#                     })
#             except Exception:
#                 pass

#         # Build 12-month forward curve — flat from current spot
#         # (no free forward curve exists for these products)
#         today = datetime.today()
#         strips = {"wti": [], "rbob": [], "ulsd": []}

#         for i in range(12):
#             # Advance by months
#             month_num = today.month + i
#             year      = today.year + (month_num - 1) // 12
#             month     = ((month_num - 1) % 12) + 1
#             dt        = datetime(year, month, 1)
#             label     = dt.strftime("%b %Y")
#             date_str  = dt.strftime("%Y-%m")

#             strips["wti"].append({
#                 "month": label,
#                 "date":  date_str,
#                 "price": round(wti_spot, 2),
#             })
#             if rbob_spot:
#                 strips["rbob"].append({
#                     "month": label,
#                     "date":  date_str,
#                     "price": round(rbob_spot, 3),
#                 })
#             if ulsd_spot:
#                 strips["ulsd"].append({
#                     "month": label,
#                     "date":  date_str,
#                     "price": round(ulsd_spot, 3),
#                 })

#         return strips

#     except Exception as e:
#         print(f"  Forward strip failed: {e}")
#         return {"wti": [], "rbob": [], "ulsd": []}


# # ── AAA metro prices ───────────────────────────────────────────────────────────

# HEADERS = {
#     "User-Agent": (
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#         "AppleWebKit/537.36 (KHTML, like Gecko) "
#         "Chrome/120.0.0.0 Safari/537.36"
#     )
# }

# AAA_STATE_URL = "https://gasprices.aaa.com/?state={}"

# # State abbreviation lookup for each AAA state page
# METRO_STATE_MAP = {
#     "Anchorage":        "AK",
#     "Austin-San Marcos":"TX",
#     "Victoria":         "TX",
#     "Lawton":           "OK",
#     "Tulsa":            "OK",
#     "Minot":            "ND",
#     "Midland":          "TX",
#     "Odessa":           "TX",
#     "Salt Lake City":   "UT",
#     "Lafayette":        "LA",
# }


# def _scrape_state_metros(state_abbr: str) -> Dict[str, Dict]:
#     """Scrape all metro prices for a single state page."""
#     url  = AAA_STATE_URL.format(state_abbr)
#     try:
#         r    = requests.get(url, headers=HEADERS, timeout=15)
#         r.raise_for_status()
#     except Exception as e:
#         print(f"  AAA scrape failed ({state_abbr}): {e}")
#         return {}

#     soup   = BeautifulSoup(r.text, "html.parser")
#     metros = {}

#     for h3 in soup.find_all("h3"):
#         name  = h3.get_text(strip=True)
#         if not name or len(name) < 2:
#             continue
#         table = h3.find_next_sibling("table")
#         if not table:
#             sib = h3.find_next_sibling()
#             if sib:
#                 table = sib.find("table")
#         if not table:
#             continue

#         for row in table.find_all("tr"):
#             cols = row.find_all("td")
#             if len(cols) < 5:
#                 continue
#             if "current" not in cols[0].get_text(strip=True).lower():
#                 continue

#             def p(cell):
#                 try:
#                     return float(cell.get_text(strip=True).replace("$", ""))
#                 except Exception:
#                     return None

#             metros[name] = {
#                 "regular":  p(cols[1]),
#                 "midgrade": p(cols[2]),
#                 "premium":  p(cols[3]),
#                 "diesel":   p(cols[4]),
#                 "state":    state_abbr,
#             }
#             break

#     return metros


# def fetch_location_prices(locations: list) -> Dict[str, Dict]:
#     """
#     Fetch AAA metro prices for all locations.
#     Scrapes each unique state page once, extracts metro prices.
#     Returns {location_display: {regular, diesel, midgrade, premium, source}}
#     """
#     # Determine which states to scrape
#     states_needed = set()
#     for loc in locations:
#         if loc.get("aaa_state"):
#             states_needed.add(loc["aaa_state"])

#     # Scrape each state once
#     all_metro_prices = {}
#     for state in sorted(states_needed):
#         metros = _scrape_state_metros(state)
#         all_metro_prices.update(metros)
#         time.sleep(0.3)

#     # Map to locations
#     result = {}
#     for loc in locations:
#         display    = loc["display"]
#         metro_name = loc.get("aaa_metro")
#         state      = loc.get("aaa_state")

#         if metro_name and metro_name in all_metro_prices:
#             data   = all_metro_prices[metro_name]
#             source = f"AAA Metro — {metro_name}"
#         elif loc.get("manual_gas"):
#             data   = {
#                 "regular": loc["manual_gas"],
#                 "diesel":  loc["manual_diesel"],
#                 "midgrade": None,
#                 "premium":  None,
#             }
#             source = "Manual input"
#         else:
#             data   = {"regular": None, "diesel": None}
#             source = "No data"

#         result[display] = {**data, "source": source}

#     return result


# # ── Specialty products ─────────────────────────────────────────────────────────

# def fetch_specialty_prices(eia_api_key: str,
#                            fred_api_key: str) -> Dict[str, Optional[float]]:
#     """
#     Fetch jet fuel, bunker, and asphalt spot prices.
#     Falls back to proxy if live data unavailable.
#     """
#     EIA_SPT = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

#     def eia_spot(product, process, area, freq="weekly"):
#         try:
#             params = [
#                 ("api_key", eia_api_key), ("frequency", freq),
#                 ("data[0]", "value"), ("facets[product][]", product),
#                 ("facets[process][]", process), ("facets[duoarea][]", area),
#                 ("sort[0][column]", "period"), ("sort[0][direction]", "desc"),
#                 ("length", "3"),
#             ]
#             r    = requests.get(EIA_SPT, params=params, timeout=10)
#             rows = r.json()["response"]["data"]
#             return float(rows[0]["value"]) if rows else None
#         except Exception:
#             return None

#     jet     = eia_spot("EPJK",  "PF4", "RGC")
#     bunker  = eia_spot("EPPR",  "PF4", "RGC")
#     asphalt = eia_spot("EPPA",  "PTE", "NUS", "monthly")

#     return {
#         "jet_gal":        jet,
#         "bunker_gal":     bunker,
#         "asphalt_gal":    asphalt,
#         "jet_src":        "EIA Gulf Coast spot" if jet     else "proxy",
#         "bunker_src":     "EIA residual spot"   if bunker  else "proxy",
#         "asphalt_src":    "EIA monthly"         if asphalt else "proxy",
#     }
