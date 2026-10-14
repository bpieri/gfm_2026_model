# app.py — Rogue Refinery Economics v6
# Today tab: clean 3-panel layout, no clutter
# Forward tab: basis-driven inputs against CME curve
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from config import (
    LOCATIONS, YIELD_DEFAULTS, SPECIALTY_DEFAULTS,
    EIA_API_KEY, FRED_API_KEY,
)
from fetchers.prices import (
    fetch_spot_prices,
    fetch_cme_forward_curve,
    compute_forward_crack,
    fetch_location_prices,
    fetch_specialty_prices,
)
from engine.location_margins import compute_location_margins
from engine.crack import crack_321 as _c321


def _scroll_top():
    components.html("""<script>
    (function(){function s(){var e=['[data-testid="stAppViewContainer"]',
    '[data-testid="stMain"]','.main','body'];
    for(var i=0;i<e.length;i++){var el=window.parent.document.querySelector(e[i]);
    if(el)el.scrollTop=0;}window.parent.scrollTo(0,0);}
    s();setTimeout(s,150);setTimeout(s,400);})();
    </script>""", height=0)


st.set_page_config(page_title="Rogue Refinery Economics",
                   page_icon="🏭", layout="wide")

st.markdown("""
<style>
.stApp{background:#0D1117}
.ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
  border-radius:8px;padding:10px 20px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
.ticker-item{display:flex;flex-direction:column;align-items:center}
.ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
.ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
.ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
.sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
  text-transform:uppercase;margin:12px 0 8px 0}
.loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
  padding:14px 16px;cursor:pointer}
.loc-card:hover{border-color:#E8A020}
.loc-card-name{font-size:11px;color:#8B949E;text-transform:uppercase;
  letter-spacing:1px;margin-bottom:4px}
.loc-card-spread{font-size:26px;font-weight:700;font-family:monospace}
.loc-card-badge{display:inline-block;font-size:9px;font-weight:600;
  letter-spacing:1px;padding:2px 8px;border-radius:4px;margin-top:4px}
.loc-card-pnl{font-size:11px;color:#8B949E;margin-top:4px}
.badge-strong{background:#0D2A1A;color:#3FB950}
.badge-moderate{background:#2A1F08;color:#E8A020}
.badge-thin{background:#2A0D0D;color:#F85149}
/* Headline GRM card — larger, more visual weight */
.grm-hero{background:#161B22;border:1px solid #E8A020;border-radius:12px;
  padding:28px 20px;text-align:center}
.grm-hero-label{font-size:10px;color:#8B949E;text-transform:uppercase;
  letter-spacing:2px;margin-bottom:8px}
.grm-hero-value{font-size:52px;font-weight:700;font-family:monospace;
  line-height:1;margin-bottom:6px}
.grm-hero-sub{font-size:12px;color:#8B949E}
/* Supporting metric cards */
.metric-card{background:#161B22;border:1px solid #30363D;border-radius:8px;
  padding:16px;text-align:center}
.mc-label{font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px}
.mc-value{font-size:22px;font-weight:700;color:#E6EDF3;font-family:monospace}
.mc-sub{font-size:10px;color:#8B949E;margin-top:2px}
/* Price reference table */
.price-row{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.price-chip{background:#161B22;border:1px solid #21262D;border-radius:6px;
  padding:6px 12px;display:inline-flex;align-items:center;gap:8px}
.price-chip-label{font-size:9px;color:#8B949E;text-transform:uppercase;
  letter-spacing:1px}
.price-chip-value{font-size:13px;font-weight:600;color:#E6EDF3;font-family:monospace}
/* Basis input label */
.basis-label{font-size:10px;color:#8B949E;margin-bottom:2px}
.basis-note{font-size:10px;color:#484F58;margin-top:2px}
#MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
.block-container{padding-top:0.3rem !important;padding-bottom:0 !important}
[data-testid="stAppViewContainer"]>[data-testid="stVerticalBlock"]{padding-top:0 !important}
h2,h3{margin-top:0 !important}
[data-testid="stSidebar"]{background:#161B22}
div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;border-radius:8px}
p,.stMarkdown p,.stText{color:#E6EDF3 !important}
.stDataFrame{color:#E6EDF3 !important}
[data-testid="stMetricValue"]{color:#E6EDF3 !important}
[data-testid="stMetricLabel"]{color:#8B949E !important}
caption,.stCaption{color:#8B949E !important}
label,.stSelectbox label,.stNumberInput label,.stToggle label{color:#8B949E !important}
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def spread_color(v):
    if v is None: return "#8B949E"
    return "#3FB950" if v >= 25 else ("#E8A020" if v >= 12 else "#F85149")

def spread_label(v):
    if v is None: return "—"
    return "STRONG" if v >= 25 else ("MODERATE" if v >= 12 else "THIN")

def spread_badge_class(v):
    if v is None: return "badge-thin"
    return "badge-strong" if v >= 25 else ("badge-moderate" if v >= 12 else "badge-thin")

def fmt_bbl(v):  return f"${v:.2f}" if v is not None else "—"
def fmt_gal(v):  return f"${v:.3f}" if v is not None else "—"

def fmt_grm(spread, throughput):
    if spread is None or not throughput: return None
    return round(spread * throughput * 30 / 1_000_000, 2)

def sign_str(v):
    if v is None: return "—"
    return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"

def chips(items):
    """Render a row of price chips as HTML."""
    html = "<div class='price-row'>"
    for label, val in items:
        html += (f"<div class='price-chip'>"
                 f"<span class='price-chip-label'>{label}</span>"
                 f"<span class='price-chip-value'>{val}</span></div>")
    html += "</div>"
    return html


# ── Password ───────────────────────────────────────────────────────────────────
def check_password():
    try:
        correct = st.secrets.get("APP_PASSWORD")
    except Exception:
        return
    if not correct: return
    if not st.session_state.get("auth"):
        st.title("🏭 Rogue Refinery Economics")
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
            if pwd == correct:
                st.session_state["auth"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
        st.stop()


# ── Cached fetchers ────────────────────────────────────────────────────────────
GSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTfw6hAiE418gmKF2Ut0qRV2xCTex3fB4wY4IUwoR_5x5bRDpPxPbGwCaJunbjXDhHAeu-h_lQhUKiB"
    "/pub?gid=0&single=true&output=csv"
)

@st.cache_data(ttl=3600)
def get_specialty_sheet() -> dict:
    import requests, csv, io
    try:
        r = requests.get(GSHEET_URL, timeout=10)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
        result = {}
        for row in reader:
            loc = row.get("location","").strip()
            if not loc: continue
            result[loc] = {
                "jet_gal":     float(row.get("jet_gal",     SPECIALTY_DEFAULTS["jet_gal"])),
                "bunker_gal":  float(row.get("bunker_gal",  SPECIALTY_DEFAULTS["bunker_gal"])),
                "asphalt_gal": float(row.get("asphalt_gal", SPECIALTY_DEFAULTS["asphalt_gal"])),
                "lpg_gal":     float(row.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal",0.95))),
                "last_updated":row.get("last_updated","—"),
            }
        return result
    except Exception as e:
        print(f"  Google Sheet fetch failed: {e}")
        return {}

@st.cache_data(ttl=3600)
def get_cme():  return fetch_cme_forward_curve()

@st.cache_data(ttl=3600)
def get_spot(): return fetch_spot_prices(EIA_API_KEY)

@st.cache_data(ttl=3600)
def get_lp():   return fetch_location_prices(LOCATIONS)

@st.cache_data(ttl=86400)
def get_spec(): return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# ── Build live margins ─────────────────────────────────────────────────────────
def build_live_margins(lp, sheet_prices):
    live_spot = get_spot()
    eia_spec  = get_spec()
    yields    = {k: v for k, v in YIELD_DEFAULTS.items()}
    rows      = []
    for loc in LOCATIONS:
        n    = loc["display"]
        spec = sheet_prices.get(n, {})
        ulsd = live_spot.get("ulsd_gal", 3.5) or 3.5
        wti  = live_spot.get("wti_bbl",  80)  or 80
        location_specialty = {
            "jet_gal":     spec.get("jet_gal",     eia_spec.get("jet_gal")     or ulsd*1.05),
            "bunker_gal":  spec.get("bunker_gal",  eia_spec.get("bunker_gal")  or ulsd*0.70),
            "asphalt_gal": spec.get("asphalt_gal", eia_spec.get("asphalt_gal") or ulsd*0.60),
            "lpg_gal":     spec.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal",0.95)),
        }
        margin_list = compute_location_margins(
            locations=[dict(loc)], spot_prices=live_spot,
            location_prices=lp, specialty=location_specialty,
            yields=yields, dist_margin_gal=0.35)
        if margin_list:
            r = margin_list[0]
            r["throughput"]   = loc.get("throughput", 30000)
            r["pnl"]          = fmt_grm(r.get("spread_321"), r["throughput"])
            r["specialty"]    = location_specialty
            r["spec_updated"] = spec.get("last_updated","—")
            rows.append(r)
    return rows, live_spot, yields


# ── Forward state init ─────────────────────────────────────────────────────────
def init_fwd_state(n, loc_cfg, sheet_prices, live_spot):
    """
    Initialise forward tab session state.
    Basis fields auto-populate from location config (light_diff etc).
    Specialty prices from Google Sheet.
    CME absolute prices are NOT stored — they come from the strip at render time.
    """
    if st.session_state.get(f"_fwd_init_{n}"): return
    spec = sheet_prices.get(n, {})
    ulsd = live_spot.get("ulsd_gal", 3.5) or 3.5
    wti  = live_spot.get("wti_bbl",  80)  or 80
    st.session_state.update({
        # Crude basis — decomposed: quality diff + transport tariff from config
        f"fwd_light_qual_{n}":    float(loc_cfg.get("light_quality_diff",    loc_cfg.get("light_diff",0.0))),
        f"fwd_light_tariff_{n}":  float(loc_cfg.get("light_transport_tariff",2.50)),
        f"fwd_heavy_qual_{n}":    float(loc_cfg.get("heavy_quality_diff",    loc_cfg.get("heavy_diff",0.0))),
        f"fwd_heavy_tariff_{n}":  float(loc_cfg.get("heavy_transport_tariff",2.50)),
        f"fwd_light_pct_{n}":     80.0,   # % of slate = light crude (default 80%)
        # Cost transparency opex items ($/bbl) — for net margin display
        f"ct_opex_{n}":           4.00,
        f"ct_prod_transport_{n}": 0.50,
        f"ct_blendstock_{n}":     1.20,
        f"ct_rin_{n}":            0.80,
        f"ct_maintenance_{n}":    0.75,
        # Product basis vs NYMEX
        f"fwd_gas_basis_{n}":   float(loc_cfg.get("gas_diff",     0.0)),
        f"fwd_die_basis_{n}":   float(loc_cfg.get("diesel_diff",  0.0)),
        # Specialty — flat forward assumption from Google Sheet
        f"fwd_jet_{n}":         spec.get("jet_gal",     ulsd*1.05),
        f"fwd_jet_delta_{n}":   0.0,   # $/gal vs current
        f"fwd_bunker_{n}":      spec.get("bunker_gal",  ulsd*0.70),
        f"fwd_bunker_delta_{n}":0.0,
        f"fwd_asphalt_{n}":     spec.get("asphalt_gal", ulsd*0.60),
        f"fwd_asphalt_delta_{n}":0.0,
        f"fwd_lpg_{n}":         spec.get("lpg_gal",     round(wti*0.50/42,3)),
        f"fwd_lpg_delta_{n}":   0.0,
        f"fwd_dist_{n}":        0.35,
        f"fwd_tp_{n}":          loc_cfg.get("throughput", 30000),
    })
    for k, v in YIELD_DEFAULTS.items():
        if f"fwd_y_{k}_{n}" not in st.session_state:
            st.session_state[f"fwd_y_{k}_{n}"] = round(v * 100, 1)
    st.session_state[f"_fwd_init_{n}"] = True


# ── Ticker ─────────────────────────────────────────────────────────────────────
def render_ticker(live_spot, live_margins):
    wti  = live_spot.get("wti_bbl")
    rbob = live_spot.get("rbob_gal")
    ulsd = live_spot.get("ulsd_gal")
    sp   = [r["spread_321"] for r in live_margins if r.get("spread_321")]
    pavg = round(sum(sp)/len(sp),2) if sp else None
    grm  = sum(r["pnl"] for r in live_margins if r.get("pnl"))
    pc   = spread_color(pavg)
    st.markdown(f"""
    <div class="ticker-bar">
      <div class="ticker-item"><span class="ticker-label">WTI Crude</span>
        <span class="ticker-value">{fmt_bbl(wti)}</span>
        <span class="ticker-label">per barrel</span></div>
      <div class="ticker-divider"></div>
      <div class="ticker-item"><span class="ticker-label">RBOB</span>
        <span class="ticker-value">{fmt_gal(rbob)}</span>
        <span class="ticker-label">per gallon</span></div>
      <div class="ticker-divider"></div>
      <div class="ticker-item"><span class="ticker-label">ULSD</span>
        <span class="ticker-value">{fmt_gal(ulsd)}</span>
        <span class="ticker-label">per gallon</span></div>
      <div class="ticker-divider"></div>
      <div class="ticker-item"><span class="ticker-label">RBOB $/bbl</span>
        <span class="ticker-value">{fmt_bbl(round(rbob*42,2) if rbob else None)}</span>
        <span class="ticker-label">×42</span></div>
      <div class="ticker-divider"></div>
      <div class="ticker-item"><span class="ticker-label">Portfolio Avg 3-2-1</span>
        <span class="ticker-value" style="color:{pc}">{"$"+str(pavg)+"/bbl" if pavg else "—"}</span>
        <span class="ticker-label" style="color:{pc}">{spread_label(pavg)}</span></div>
      <div class="ticker-divider"></div>
      <div class="ticker-item"><span class="ticker-label">Portfolio GRM/mo</span>
        <span class="ticker-value" style="color:#3FB950">{"$"+str(round(grm,1))+"MM" if grm else "—"}</span>
        <span class="ticker-label">before opex</span></div>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# COST TRANSPARENCY PANEL
# ══════════════════════════════════════════════════════════════════════════════
def _render_cost_transparency(n, grm_bbl, tp, live_mode=True):
    """
    Investment committee cost transparency panel.
    Shows what IS and IS NOT included in GRM, with editable opex deductions
    and a live estimated net margin calculation.
    """
    with st.expander(
        "💼 Cost Transparency — What's in GRM vs What's Not (Investment Committee View)",
        expanded=False):

        st.markdown(
            "<div style='font-size:11px;color:#8B949E;margin-bottom:12px'>"
            "GRM is a <b>gross</b> margin — it does not include operating costs. "
            "The items below are common deductions to arrive at net margin. "
            "Adjust to your actual cost structure.</div>",
            unsafe_allow_html=True)

        col_in, col_out = st.columns(2)

        with col_in:
            st.markdown(
                "<div style='background:#0D2A1A;border-radius:6px;padding:10px 14px;"
                "margin-bottom:8px'>"
                "<div style='font-size:10px;font-weight:600;color:#3FB950;"
                "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
                "✅ INCLUDED IN GRM</div>",
                unsafe_allow_html=True)
            included_items = [
                ("Crude quality differential",   "Crude grade premium/discount vs WTI"),
                ("Crude pipeline/marine tariff",  "Field to refinery gate transport"),
                ("Federal & state fuel taxes",    "Stripped from AAA retail prices"),
                ("Distribution margin",           "Terminal to pump ($0.35/gal default)"),
                ("Refinery fuel & losses",        "~5.5% of barrel burned onsite"),
            ]
            for item, desc in included_items:
                st.markdown(
                    f"<div style='margin-bottom:6px'>"
                    f"<span style='font-size:11px;color:#E6EDF3'>{item}</span><br>"
                    f"<span style='font-size:10px;color:#484F58'>{desc}</span>"
                    f"</div>",
                    unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with col_out:
            st.markdown(
                "<div style='background:#2A0D0D;border-radius:6px;padding:10px 14px;"
                "margin-bottom:8px'>"
                "<div style='font-size:10px;font-weight:600;color:#F85149;"
                "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
                "❌ NOT IN GRM — deduct for net margin</div>",
                unsafe_allow_html=True)

            OPEX_ITEMS = [
                (f"ct_opex_{n}",            "Refinery opex ($/bbl)",            4.00,
                 "Labor, utilities, catalysts, chemicals"),
                (f"ct_prod_transport_{n}",   "Product transport ($/bbl)",         0.50,
                 "Pipeline/truck from refinery to terminal"),
                (f"ct_blendstock_{n}",       "Blendstock costs ($/bbl)",          1.20,
                 "Ethanol, butane, MTBE, additives"),
                (f"ct_rin_{n}",              "RIN obligations ($/bbl)",           0.80,
                 "Renewable fuel standard compliance"),
                (f"ct_maintenance_{n}",      "Maintenance & turnaround ($/bbl)",  0.75,
                 "Annualized capex, scheduled downtime"),
            ]
            total_deductions = 0.0
            for key, label, default, desc in OPEX_ITEMS:
                val = st.number_input(
                    label, min_value=0.0, max_value=20.0,
                    value=float(st.session_state.get(key, default)),
                    step=0.25, format="%.2f", key=f"ctp_{key}")
                st.session_state[key] = val
                total_deductions += val
                st.caption(desc)
            st.markdown("</div>", unsafe_allow_html=True)

        net_margin = round((grm_bbl or 0) - total_deductions, 2) if grm_bbl else None
        net_grm_mm = round(net_margin * tp * 30 / 1e6, 2) if (net_margin and tp) else None
        net_clr    = ("#3FB950" if net_margin and net_margin >= 10
                      else ("#E8A020" if net_margin and net_margin >= 0
                      else "#F85149"))

        net_mm_html = (
            f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:1px'>Net GRM / Month</div>"
            f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
            f"color:{net_clr}'>${net_grm_mm:.1f}MM</div></div>"
        ) if net_grm_mm else ""

        st.markdown(
            f"<div style='background:#161B22;border:1px solid #30363D;"
            f"border-radius:8px;padding:14px 18px;margin-top:8px'>"
            f"<div style='display:flex;gap:24px;align-items:center;flex-wrap:wrap'>"
            f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:1px'>Gross Refining Margin</div>"
            f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
            f"color:#E8A020'>${(grm_bbl or 0):.2f}/bbl</div></div>"
            f"<div style='font-size:22px;color:#484F58'>−</div>"
            f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:1px'>Est. Total Deductions</div>"
            f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
            f"color:#F85149'>${total_deductions:.2f}/bbl</div></div>"
            f"<div style='font-size:22px;color:#484F58'>=</div>"
            f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:1px'>Est. Net Margin</div>"
            f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
            f"color:{net_clr}'>{'$'+str(net_margin)+'/bbl' if net_margin is not None else '—'}</div></div>"
            f"{net_mm_html}"
            f"</div>"
            f"<div style='font-size:10px;color:#484F58;margin-top:8px'>"
            f"⚠️ Estimated net margin uses industry benchmark defaults. "
            f"Adjust deduction items to your actual cost structure. "
            f"Not a substitute for detailed project-level financial modeling.</div>"
            f"</div>",
            unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO PAGE
# ══════════════════════════════════════════════════════════════════════════════
LOC_COORDS = {
    "Alaska — Port Mackenzie":  (61.35,-150.02),
    "Greenport — Austin, TX":   (30.27, -97.74),
    "Victoria, TX":             (28.81, -97.00),
    "Duncan, OK":               (34.50, -97.96),
    "Dewey, OK":                (36.80, -95.93),
    "North Dakota — Stampede":  (48.40,-101.30),
    "Big Spring, TX":           (32.25,-101.48),
    "Utah":                     (40.76,-111.89),
    "SE New Mexico":            (33.39,-104.52),
    "Louisiana":                (30.22, -92.02),
    "Puerto Rico":              (18.22, -66.59),
}

def show_portfolio(live_margins):
    valid = [r for r in live_margins if r.get("spread_321")]
    if valid:
        best  = max(valid, key=lambda x: x["spread_321"])
        worst = min(valid, key=lambda x: x["spread_321"])
        total = sum(r["pnl"] for r in valid if r.get("pnl"))
        sc1,sc2,sc3 = st.columns(3)
        sc1.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Best Margin Today</div>
            <div class='mc-value' style='color:#3FB950'>${best["spread_321"]:.2f}/bbl</div>
            <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
        </div>""", unsafe_allow_html=True)
        sc2.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Thinnest Margin Today</div>
            <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
              ${worst["spread_321"]:.2f}/bbl</div>
            <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
        </div>""", unsafe_allow_html=True)
        sc3.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Total Portfolio GRM / Month</div>
            <div class='mc-value' style='color:#3FB950'>
              {"$"+str(round(total,1))+"MM" if total else "—"}</div>
            <div class='mc-sub'>before opex · full yield basis</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # Report button
    rp1, rp2 = st.columns([3,1])
    with rp2:
        if st.button("📋 Management Report", use_container_width=True):
            st.session_state["view"] = "report"
            st.rerun()

    # Map
    st.markdown("<div class='sec-hdr'>Portfolio Map — 3-2-1 Crack Spread</div>",
                unsafe_allow_html=True)
    map_rows = []
    for r in live_margins:
        c = LOC_COORDS.get(r["display"],(39.5,-98.35))
        s = r.get("spread_321")
        spec = r.get("specialty",{})
        map_rows.append({
            "name":  r["display"],
            "short": r["display"].split("—")[-1].split(",")[0].strip(),
            "lat":c[0],"lon":c[1],"spread":s,"color":spread_color(s),
            "hover":(
                f"<b>{r['display']}</b><br>"
                f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
                f"Full Yield GRM: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
                f"GRM/mo: {'$'+str(r['pnl'])+'MM' if r.get('pnl') else '—'}<br>"
                f"Jet: ${spec.get('jet_gal','—')}/gal · Bunker: ${spec.get('bunker_gal','—')}/gal"
            ),
        })
    df_m = pd.DataFrame(map_rows)
    fig_m = go.Figure()
    fig_m.add_trace(go.Scattergeo(
        lat=df_m["lat"],lon=df_m["lon"],mode="markers+text",
        marker=dict(size=20,color=df_m["color"].tolist(),
                    line=dict(width=2,color="#0D1117"),opacity=0.90),
        text=df_m["short"],textposition="top center",
        textfont=dict(size=10,color="#E6EDF3"),
        hovertext=df_m["hover"],hoverinfo="text"))
    for _,row in df_m.iterrows():
        if row["spread"]:
            fig_m.add_trace(go.Scattergeo(
                lat=[row["lat"]-1.9],lon=[row["lon"]],mode="text",
                text=[f"${row['spread']:.0f}"],
                textfont=dict(size=10,color=row["color"],family="monospace"),
                hoverinfo="skip",showlegend=False))
    fig_m.update_layout(
        geo=dict(scope="world",showland=True,landcolor="#1C2128",
                 showocean=True,oceancolor="#0D1117",
                 showlakes=True,lakecolor="#0D1117",
                 showcountries=True,countrycolor="#30363D",
                 showcoastlines=True,coastlinecolor="#30363D",
                 showframe=False,bgcolor="#0D1117",
                 center=dict(lat=45,lon=-100),projection_scale=1.4,
                 lonaxis_range=[-175,-50],lataxis_range=[10,78]),
        paper_bgcolor="#0D1117",margin=dict(l=0,r=0,t=0,b=0),
        height=400,showlegend=False)
    for lbl,clr,ya in [("● STRONG ≥$25","#3FB950",0.13),
                        ("● MODERATE $12–25","#E8A020",0.09),
                        ("● THIN <$12","#F85149",0.05)]:
        fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
            text=lbl,showarrow=False,font=dict(color=clr,size=10),
            bgcolor="#0D1117",align="left")
    st.plotly_chart(fig_m, use_container_width=True)

    IN_CONSTRUCTION  = {"Victoria, TX","Duncan, OK"}
    DEVELOPMENT_ORDER = [
        ("Alaska — Port Mackenzie","Port Mackenzie","AK"),
        ("Greenport — Austin, TX", "Austin",       "TX"),
        ("Big Spring, TX",         "Big Spring",   "TX"),
        ("Dewey, OK",              "Dewey",        "OK"),
        ("North Dakota — Stampede","Stampede",     "ND"),
        ("Utah",                   "Utah",         "UT"),
        ("SE New Mexico",          "SE New Mexico","NM"),
        ("Louisiana",              "Louisiana",    "LA"),
        ("Puerto Rico",            "Puerto Rico",  "PR"),
    ]
    margin_map = {r["display"]: r for r in live_margins}

    def _card(r, key):
        s     = r.get("spread_321")
        clr   = spread_color(s)
        badge = spread_badge_class(s)
        pnl_s = f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—"
        short = r["display"].split("—")[-1].split(",")[0].strip()
        st.markdown(f"""<div class='loc-card'>
            <div class='loc-card-name'>{short}</div>
            <div class='loc-card-spread' style='color:{clr}'>
                {"$"+str(s)+"/bbl" if s else "—"}</div>
            <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
            <div class='loc-card-pnl'>{pnl_s}</div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open →", key=key, use_container_width=True):
            st.session_state["view"]    = "detail"
            st.session_state["sel_loc"] = r["display"]
            st.rerun()

    st.markdown("<div class='sec-hdr'>In Construction</div>", unsafe_allow_html=True)
    constr = [r for r in live_margins if r["display"] in IN_CONSTRUCTION]
    cc = st.columns(4)
    for i,r in enumerate(constr):
        with cc[i%4]: _card(r, f"btn_con_{i}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<div class='sec-hdr'>Development Locations</div>", unsafe_allow_html=True)
    dev = [(dn,sl,st_) for dn,sl,st_ in DEVELOPMENT_ORDER if dn in margin_map]
    dc  = st.columns(4)
    for i,(dn,sl,_) in enumerate(dev):
        with dc[i%4]: _card(margin_map[dn], f"btn_dev_{i}")

    # Portfolio download
    st.markdown("---")
    st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
                unsafe_allow_html=True)
    dl_rows = []
    for r in live_margins:
        tp  = r.get("throughput",30000)
        gm  = fmt_grm(r.get("spread_321"),tp)
        spec= r.get("specialty",{})
        dl_rows.append({
            "Location":              r["display"],
            "Source":                r.get("source","—"),
            "Throughput (bbl/day)":  tp,
            "Light Crude ($/bbl)":   r.get("crude_light"),
            "Heavy Crude ($/bbl)":   r.get("crude_heavy"),
            "Gasoline - Retail":     r.get("retail_gas"),
            "Gasoline - Pre-tax":    r.get("pretax_gas"),
            "Gasoline - Wholesale":  r.get("wholesale_gas"),
            "Diesel - Retail":       r.get("retail_diesel"),
            "Diesel - Wholesale":    r.get("wholesale_diesel"),
            "Jet Fuel ($/gal)":      spec.get("jet_gal"),
            "Bunker ($/gal)":        spec.get("bunker_gal"),
            "Asphalt ($/gal)":       spec.get("asphalt_gal"),
            "LPG/Other ($/gal)":     spec.get("lpg_gal"),
            "3-2-1 ($/bbl)":         r.get("spread_321"),
            "2-1-1 ($/bbl)":         r.get("spread_211"),
            "5-3-2 ($/bbl)":         r.get("spread_532"),
            "Full Yield GRM ($/bbl)":r.get("spread_full"),
            "Monthly GRM ($MM)":     gm,
            "Annual GRM ($MM)":      round(gm*12,2) if gm else None,
            "Specialty Updated":     r.get("spec_updated","—"),
            "As Of":                 datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
    df_dl = pd.DataFrame(dl_rows)
    dc1,dc2 = st.columns([1,2])
    with dc1:
        st.download_button("⬇️ Download All Locations CSV",
            data=df_dl.to_csv(index=False),
            file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",use_container_width=True)
    with dc2:
        st.dataframe(df_dl[[
            "Location","Light Crude ($/bbl)",
            "Gasoline - Retail","Gasoline - Wholesale",
            "Diesel - Retail","Diesel - Wholesale",
            "Jet Fuel ($/gal)","Bunker ($/gal)",
            "3-2-1 ($/bbl)","Full Yield GRM ($/bbl)","Monthly GRM ($MM)",
        ]],use_container_width=True,hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOCATION DETAIL — two tabs
# ══════════════════════════════════════════════════════════════════════════════
def show_detail(live_margins, strip, sheet_prices, live_spot):
    _scroll_top()
    sel = st.session_state.get("sel_loc","")
    r   = next((m for m in live_margins if m["display"]==sel), None)
    loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})

    bc,tc = st.columns([1,8])
    with bc:
        if st.button("← Portfolio"):
            st.session_state["view"] = "portfolio"
            st.rerun()
    with tc:
        s321 = r.get("spread_321") if r else None
        clr  = spread_color(s321)
        short= sel.split("—")[-1].split(",")[0].strip() if sel else "—"
        st.markdown(
            f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
            f"<span style='color:{clr};font-family:monospace'>"
            f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
            f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
            f"</h3>",unsafe_allow_html=True)
    if not r:
        st.warning("No data for this location.")
        return

    n         = sel
    tp        = r.get("throughput",30000)
    spec      = r.get("specialty",{})
    spec_date = r.get("spec_updated","—")
    init_fwd_state(n, loc_cfg, sheet_prices, live_spot)
    st.markdown("---")
    tab_today, tab_fwd = st.tabs(["📊 Today", "📈 Forward View"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — TODAY  (Financial + Operations views)
    # ══════════════════════════════════════════════════════════════════════════
    with tab_today:
        sfull  = r.get("spread_full")
        ws_g   = r.get("wholesale_gas",   0) or 0
        ws_d   = r.get("wholesale_diesel", 0) or 0
        ret_g  = r.get("retail_gas",  0) or 0
        ret_d  = r.get("retail_diesel",0) or 0
        cr_    = r.get("crude_light",  0) or 0
        jet_p  = spec.get("jet_gal",    SPECIALTY_DEFAULTS["jet_gal"])
        bnk_p  = spec.get("bunker_gal", SPECIALTY_DEFAULTS["bunker_gal"])
        asp_p  = spec.get("asphalt_gal",SPECIALTY_DEFAULTS["asphalt_gal"])
        lpg_p  = spec.get("lpg_gal",    SPECIALTY_DEFAULTS.get("lpg_gal",0.95))

        yields = {k: v for k, v in YIELD_DEFAULTS.items()}
        y_g  = yields.get("gasoline",  0.445)
        y_d  = yields.get("ulsd",      0.290)
        y_j  = yields.get("jet",       0.110)
        y_b  = yields.get("bunker",    0.035)
        y_a  = yields.get("asphalt",   0.025)
        y_l  = yields.get("lpg_other", 0.040)
        y_ru = yields.get("refinery_use",0.055)
        _sal = y_g+y_d+y_j+y_b+y_a+y_l

        gc_ = round(ws_g  *y_g*42,2)
        dc_ = round(ws_d  *y_d*42,2)
        jc_ = round(jet_p *y_j*42,2)
        bc_ = round(bnk_p *y_b*42,2)
        ac_ = round(asp_p *y_a*42,2)
        lc_ = round(lpg_p *y_l*42,2)
        total_rev = gc_+dc_+jc_+bc_+ac_+lc_
        grm_full  = round(total_rev - cr_, 2)

        # ── Throughput input (top of Today tab — drives all volume calcs) ─────
        tp_col, _ = st.columns([1,3])
        with tp_col:
            tp_today = st.number_input(
                "Throughput (bbl/day)",
                min_value=0, max_value=500000,
                value=int(st.session_state.get(f"today_tp_{n}",
                          r.get("throughput", 30000))),
                step=1000, key=f"today_tp_input_{n}")
            st.session_state[f"today_tp_{n}"] = int(tp_today)

        tp   = tp_today
        pnl_v = fmt_grm(s321, tp)

        # ── Volume calculations ───────────────────────────────────────────────
        # bbl/day
        crude_bbl_day  = tp
        gas_bbl_day    = round(tp * y_g, 0)
        die_bbl_day    = round(tp * y_d, 0)
        jet_bbl_day    = round(tp * y_j, 0)
        bnk_bbl_day    = round(tp * y_b, 0)
        asp_bbl_day    = round(tp * y_a, 0)
        lpg_bbl_day    = round(tp * y_l, 0)
        ref_bbl_day    = round(tp * y_ru,0)
        # gal/day (×42)
        gas_gal_day    = gas_bbl_day * 42
        die_gal_day    = die_bbl_day * 42
        jet_gal_day    = jet_bbl_day * 42
        bnk_gal_day    = bnk_bbl_day * 42
        lpg_gal_day    = lpg_bbl_day * 42
        # Asphalt: convert to short tons (approx 6.3 bbl/short ton for liquid asphalt)
        asp_ton_day    = round(asp_bbl_day / 6.3, 1)
        # Monthly (×30)
        crude_bbl_mo   = crude_bbl_day * 30
        gas_bbl_mo     = gas_bbl_day   * 30
        die_bbl_mo     = die_bbl_day   * 30

        # ── PANEL 1: Hero GRM + supporting metrics ────────────────────────────
        hero_col, supp_col = st.columns([2, 3], gap="large")

        with hero_col:
            grm_clr = spread_color(grm_full)
            st.markdown(f"""
            <div class='grm-hero'>
              <div class='grm-hero-label'>Refinery Crack Spread — Full Yield</div>
              <div class='grm-hero-value' style='color:{grm_clr}'>
                ${grm_full:.2f}
              </div>
              <div style='font-size:14px;font-weight:600;color:{grm_clr};
                          letter-spacing:2px;margin-bottom:12px'>
                per barrel · {spread_label(grm_full)}
              </div>
              <div style='background:#21262D;border-radius:8px;padding:10px;
                          display:inline-block;width:100%;box-sizing:border-box'>
                <div style='font-size:9px;color:#8B949E;text-transform:uppercase;
                            letter-spacing:1px'>Monthly GRM</div>
                <div style='font-size:28px;font-weight:700;font-family:monospace;
                            color:#3FB950'>
                  {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
                </div>
                <div style='font-size:10px;color:#8B949E'>{f"{tp:,} bbl/day · before opex"}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        with supp_col:
            sa1,sa2 = st.columns(2)
            sa1.markdown(f"""<div class='metric-card'>
                <div class='mc-label'>3-2-1 Reference Spread</div>
                <div class='mc-value' style='color:{spread_color(s321)}'>
                    {"$"+str(s321)+"/bbl" if s321 else "—"}</div>
                <div class='mc-sub'>2 gas + 1 diesel benchmark</div>
            </div>""", unsafe_allow_html=True)
            sa2.markdown(f"""<div class='metric-card'>
                <div class='mc-label'>Annual GRM Run-Rate</div>
                <div class='mc-value' style='color:#3FB950'>
                    {"$"+str(round(pnl_v*12,1))+"MM" if pnl_v else "—"}</div>
                <div class='mc-sub'>{f"at {tp:,} bbl/day"}</div>
            </div>""", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            sb1,sb2,sb3 = st.columns(3)
            sb1.markdown(f"""<div class='metric-card'>
                <div class='mc-label'>2-1-1 Spread</div>
                <div class='mc-value' style='color:{spread_color(r.get("spread_211"))};font-size:18px'>
                    {"$"+str(r.get("spread_211"))+"/bbl" if r.get("spread_211") else "—"}</div>
                <div class='mc-sub'>1 gas + 1 diesel</div>
            </div>""", unsafe_allow_html=True)
            sb2.markdown(f"""<div class='metric-card'>
                <div class='mc-label'>5-3-2 Spread</div>
                <div class='mc-value' style='color:{spread_color(r.get("spread_532"))};font-size:18px'>
                    {"$"+str(r.get("spread_532"))+"/bbl" if r.get("spread_532") else "—"}</div>
                <div class='mc-sub'>3 gas + 2 diesel</div>
            </div>""", unsafe_allow_html=True)
            sb3.markdown(f"""<div class='metric-card'>
                <div class='mc-label'>Crude Cost</div>
                <div class='mc-value' style='color:#F85149;font-size:18px'>
                    ${cr_:.2f}/bbl</div>
                <div class='mc-sub'>WTI + location diff</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── PANEL 2: Waterfall ────────────────────────────────────────────────
        st.markdown("<div class='sec-hdr'>Where Does the Margin Come From? — $/bbl</div>",
                    unsafe_allow_html=True)
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute","relative","relative","relative",
                     "relative","relative","relative","total"],
            x=["− Crude","+ Gasoline","+ Diesel","+ Jet",
               "+ Bunker","+ Asphalt","+ LPG","= GRM"],
            y=[-cr_, gc_, dc_, jc_, bc_, ac_, lc_, 0],
            text=[f"-${cr_:.2f}",f"+${gc_:.2f}",f"+${dc_:.2f}",
                  f"+${jc_:.2f}",f"+${bc_:.2f}",f"+${ac_:.2f}",
                  f"+${lc_:.2f}",f"${grm_full:.2f}"],
            textposition="outside",
            textfont=dict(size=11,color="#E6EDF3"),
            connector=dict(line=dict(color="#30363D",width=1)),
            decreasing=dict(marker_color="#F85149"),
            increasing=dict(marker_color="#3FB950"),
            totals=dict(marker_color="#E8A020"),
        ))
        fig_wf.update_layout(
            paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
            font_color="#E6EDF3",
            yaxis=dict(title="$/bbl",gridcolor="#21262D",tickfont=dict(size=11)),
            xaxis=dict(gridcolor="#21262D",tickangle=0,tickfont=dict(size=11)),
            margin=dict(l=0,r=0,t=8,b=0),height=340,showlegend=False)
        st.plotly_chart(fig_wf, use_container_width=True)

        # ── PANEL 3: Product contribution cards (always visible) ──────────────
        st.markdown("<div class='sec-hdr'>Product Contribution to GRM</div>",
                    unsafe_allow_html=True)
        PRODUCTS = [
            ("Gasoline", gc_,y_g,"#4A90D9",ws_g),
            ("Diesel",   dc_,y_d,"#E8A020",ws_d),
            ("Jet Fuel", jc_,y_j,"#5A9E3A",jet_p),
            ("Bunker",   bc_,y_b,"#8B4FBF",bnk_p),
            ("Asphalt",  ac_,y_a,"#CC7722",asp_p),
            ("LPG/Other",lc_,y_l,"#3AA6B9",lpg_p),
        ]
        pcols = st.columns(6)
        for col,(name,rev,yld,clr,price_gal) in zip(pcols,PRODUCTS):
            crude_alloc = round(cr_*(yld/_sal) if _sal>0 else 0,2)
            net         = round(rev-crude_alloc,2)
            pct         = round(net/grm_full*100,1) if grm_full else 0
            nc_clr      = clr if net>=0 else "#F85149"
            col.markdown(f"""<div class='metric-card' style='padding:12px'>
                <div class='mc-label' style='color:{clr}'>{name}</div>
                <div style='font-size:18px;font-weight:700;font-family:monospace;
                     color:{nc_clr}'>${net:.2f}/bbl</div>
                <div style='font-size:10px;color:#8B949E;margin-top:3px'>
                    {pct:+.1f}% of GRM</div>
                <div style='height:1px;background:#30363D;margin:6px 0'></div>
                <div style='font-size:10px;color:#8B949E'>${price_gal:.3f}/gal</div>
                <div style='font-size:10px;color:#8B949E'>${price_gal*42:.2f}/bbl</div>
                <div style='font-size:9px;color:#484F58;margin-top:3px'>
                    {round(yld*100,1)}% of barrel</div>
            </div>""", unsafe_allow_html=True)
        st.caption(
            f"Net contribution = product revenue − allocated crude cost · "
            f"{round(_sal*100,1)}% saleable · {round(y_ru*100,1)}% refinery fuel use · "
            f"total product revenue ${total_rev:.2f}/bbl vs crude ${cr_:.2f}/bbl")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── PANEL 4: Today's Prices (card style, $/gal and $/bbl) ────────────
        st.markdown("<div class='sec-hdr'>Today's Prices — Input & Output</div>",
                    unsafe_allow_html=True)
        price_data = [
            # (label, $/gal, $/bbl, type, color)
            ("WTI Crude",    cr_/42,       cr_,          "INPUT",  "#F85149"),
            ("Retail Gas",   ret_g,         ret_g*42,     "RETAIL", "#8B949E"),
            ("Whsl Gas",     ws_g,          ws_g*42,      "OUTPUT", "#4A90D9"),
            ("Retail Diesel",ret_d,         ret_d*42,     "RETAIL", "#8B949E"),
            ("Whsl Diesel",  ws_d,          ws_d*42,      "OUTPUT", "#E8A020"),
            ("Jet Fuel",     jet_p,         jet_p*42,     "OUTPUT", "#5A9E3A"),
            ("Bunker Fuel",  bnk_p,         bnk_p*42,     "OUTPUT", "#8B4FBF"),
            ("Asphalt",      asp_p,         asp_p*42,     "OUTPUT", "#CC7722"),
            ("LPG/Other",    lpg_p,         lpg_p*42,     "OUTPUT", "#3AA6B9"),
        ]
        pcols2 = st.columns(len(price_data))
        for col,(lbl,gal,bbl,typ,clr) in zip(pcols2, price_data):
            badge_bg = "#2A0D0D" if typ=="INPUT" else ("#1A1A2A" if typ=="RETAIL" else "#0D1A0D")
            badge_clr= "#F85149" if typ=="INPUT" else ("#8B949E" if typ=="RETAIL" else "#3FB950")
            col.markdown(f"""<div class='metric-card' style='padding:10px'>
                <div style='font-size:8px;font-weight:600;letter-spacing:1px;
                     background:{badge_bg};color:{badge_clr};
                     border-radius:3px;padding:1px 5px;display:inline-block;
                     margin-bottom:4px'>{typ}</div>
                <div style='font-size:10px;color:#8B949E;margin-bottom:3px'>{lbl}</div>
                <div style='font-size:14px;font-weight:700;font-family:monospace;
                     color:{clr}'>${gal:.3f}<span style='font-size:9px;color:#484F58'>/gal</span></div>
                <div style='font-size:12px;font-weight:600;font-family:monospace;
                     color:{clr}'>${bbl:.2f}<span style='font-size:9px;color:#484F58'>/bbl</span></div>
            </div>""", unsafe_allow_html=True)
        st.caption(
            f"Gas & diesel: AAA daily survey · Crude: CME settle · "
            f"Jet/Bunker/Asphalt/LPG: Google Sheet (updated {spec_date}) · "
            f"INPUT = cost · OUTPUT = revenue · RETAIL = reference only")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── PANEL 5: Operations / Volume View ─────────────────────────────────
        st.markdown("<div class='sec-hdr'>Operations View — Barrels & Volume</div>",
                    unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px;color:#8B949E;margin-bottom:8px'>"
                    f"At <b style='color:#E6EDF3'>{tp:,} bbl/day</b> throughput · "
                    f"30-day month · Asphalt in short tons (÷6.3 bbl/ton)</div>",
                    unsafe_allow_html=True)

        # Volume bar chart — inputs vs outputs
        INPUTS_VOL  = [("Light Crude Input", crude_bbl_day, "#F85149")]
        OUTPUTS_VOL = [
            ("Gasoline",  gas_bbl_day, "#4A90D9"),
            ("Diesel",    die_bbl_day, "#E8A020"),
            ("Jet Fuel",  jet_bbl_day, "#5A9E3A"),
            ("Bunker",    bnk_bbl_day, "#8B4FBF"),
            ("Asphalt",   asp_bbl_day, "#CC7722"),
            ("LPG/Other", lpg_bbl_day, "#3AA6B9"),
            ("Ref. Use/Loss",ref_bbl_day,"#484F58"),
        ]
        fig_vol = go.Figure()
        for (lbl,val,clr) in INPUTS_VOL:
            fig_vol.add_trace(go.Bar(
                name=lbl, x=["Daily (bbl)","Monthly (bbl)"],
                y=[val, val*30], marker_color=clr,
                text=[f"{val:,.0f}",f"{val*30:,.0f}"],
                textposition="outside",textfont=dict(size=9,color="#E6EDF3")))
        for (lbl,val,clr) in OUTPUTS_VOL:
            fig_vol.add_trace(go.Bar(
                name=lbl, x=["Daily (bbl)","Monthly (bbl)"],
                y=[val, val*30], marker_color=clr,
                text=[f"{val:,.0f}",f"{val*30:,.0f}"],
                textposition="inside",textfont=dict(size=9,color="#E6EDF3")))
        fig_vol.update_layout(
            barmode="group",
            paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
            font_color="#E6EDF3",
            xaxis=dict(gridcolor="#21262D"),
            yaxis=dict(title="Barrels",gridcolor="#21262D"),
            legend=dict(bgcolor="#161B22",font=dict(size=9),
                        orientation="h",yanchor="bottom",y=1.02),
            margin=dict(l=0,r=0,t=30,b=0),height=300)
        st.plotly_chart(fig_vol, use_container_width=True)

        # Operations table — one row per stream
        ops_rows = [
            # stream, type, bbl/day, gal/day, bbl/mo, $/gal, $/bbl, rev_cost/mo_mm
            ("Light Crude",  "INPUT",  crude_bbl_day, crude_bbl_day*42,
             crude_bbl_mo,   cr_/42,   cr_,
             -round(cr_*crude_bbl_mo/1e6,2)),
            ("Gasoline",     "OUTPUT", gas_bbl_day,   gas_gal_day,
             gas_bbl_mo,     ws_g,     ws_g*42,
             round(ws_g*42*gas_bbl_mo/1e6,2)),
            ("Diesel/ULSD",  "OUTPUT", die_bbl_day,   die_gal_day,
             die_bbl_mo,     ws_d,     ws_d*42,
             round(ws_d*42*die_bbl_mo/1e6,2)),
            ("Jet Fuel",     "OUTPUT", jet_bbl_day,   jet_gal_day,
             jet_bbl_day*30, jet_p,    jet_p*42,
             round(jet_p*42*jet_bbl_day*30/1e6,2)),
            ("Bunker Fuel",  "OUTPUT", bnk_bbl_day,   bnk_gal_day,
             bnk_bbl_day*30, bnk_p,    bnk_p*42,
             round(bnk_p*42*bnk_bbl_day*30/1e6,2)),
            ("Asphalt",      "OUTPUT (tons)", asp_bbl_day, f"{asp_ton_day:.0f} t/day",
             asp_bbl_day*30, asp_p,    asp_p*42,
             round(asp_p*42*asp_bbl_day*30/1e6,2)),
            ("LPG/Other",    "OUTPUT", lpg_bbl_day,   lpg_gal_day,
             lpg_bbl_day*30, lpg_p,    lpg_p*42,
             round(lpg_p*42*lpg_bbl_day*30/1e6,2)),
            ("Refinery Use", "LOSS",   ref_bbl_day,   "—",
             ref_bbl_day*30, "—",      "—",   0),
        ]
        ops_df = pd.DataFrame(ops_rows, columns=[
            "Stream","Type","bbl/day","gal/day","bbl/month",
            "$/gal","$/bbl","Revenue/Cost ($MM/mo)"])
        # Format numeric columns
        for c in ["bbl/day","bbl/month"]:
            ops_df[c] = ops_df[c].apply(
                lambda x: f"{int(x):,}" if isinstance(x,(int,float)) else x)
        for c in ["gal/day"]:
            ops_df[c] = ops_df[c].apply(
                lambda x: f"{int(x):,}" if isinstance(x,(int,float)) else x)
        for c in ["$/gal","$/bbl"]:
            ops_df[c] = ops_df[c].apply(
                lambda x: f"${x:.3f}" if isinstance(x,float) else x)
        ops_df["Revenue/Cost ($MM/mo)"] = ops_df["Revenue/Cost ($MM/mo)"].apply(
            lambda x: f"+${x:.2f}MM" if isinstance(x,float) and x>0
                      else (f"-${abs(x):.2f}MM" if isinstance(x,float) and x<0 else "—"))
        st.dataframe(ops_df, use_container_width=True, hide_index=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── PANEL 6: Stress test ──────────────────────────────────────────────
        st.markdown("<div class='sec-hdr'>What If… — 3-2-1 Crack Spread Stress Test</div>",
                    unsafe_allow_html=True)
        crude_b = r.get("crude_light", cr_)
        gas_b   = r.get("wholesale_gas",  ws_g)
        die_b   = r.get("wholesale_diesel",ws_d)
        base    = s321 or 0

        st_left, st_right = st.columns([1,1], gap="large")
        with st_left:
            scenarios = [
                ("Crude +25%",    crude_b*1.25, gas_b,      die_b),
                ("Products +25%", crude_b,      gas_b*1.25, die_b*1.25),
                ("Crude −25%",    crude_b*0.75, gas_b,      die_b),
                ("Products −25%", crude_b,      gas_b*0.75, die_b*0.75),
            ]
            r1c1,r1c2 = st.columns(2)
            r2c1,r2c2 = st.columns(2)
            for col,(lbl,c,g,d) in zip([r1c1,r1c2,r2c1,r2c2],scenarios):
                val   = round(_c321(c,g,d),2)
                delta = round(val-base,2)
                grm_mo= round(val*tp*30/1e6,2)
                is_up = delta >= 0
                bg    = "#0D2A1A" if is_up else "#2A0D0D"
                clr2  = "#3FB950" if is_up else "#F85149"
                sign  = "▲" if is_up else "▼"
                col.markdown(f"""
                <div style='background:{bg};border-radius:8px;padding:16px;
                     text-align:center;margin-bottom:6px'>
                  <div style='font-size:9px;color:{clr2};letter-spacing:1px;
                       text-transform:uppercase;font-weight:600'>{lbl}</div>
                  <div style='font-size:10px;color:#8B949E;margin:4px 0'>
                      Base 3-2-1: ${base:.2f}</div>
                  <div style='font-size:26px;font-weight:700;
                       font-family:monospace;color:{clr2}'>${val:.2f}</div>
                  <div style='font-size:11px;font-weight:600;color:{clr2}'>
                      {sign} {sign_str(delta)}/bbl</div>
                  <div style='font-size:10px;color:{clr2};margin-top:3px'>
                      GRM/mo: ${grm_mo:.1f}MM</div>
                </div>""", unsafe_allow_html=True)

        with st_right:
            AREA_BAR = {
                "Gasoline":("#4A90D9",gc_),"Diesel":("#E8A020",dc_),
                "Jet":("#5A9E3A",jc_),"Bunker":("#8B4FBF",bc_),
                "Asphalt":("#CC7722",ac_),"LPG":("#3AA6B9",lc_),
            }
            fig_bar = go.Figure()
            for prod,(clr2,val) in AREA_BAR.items():
                fig_bar.add_trace(go.Bar(
                    name=prod,x=["Revenue"],y=[val],
                    marker_color=clr2,
                    text=[f"${val:.1f}"],textposition="inside",
                    textfont=dict(size=9,color="#E6EDF3")))
            fig_bar.add_hline(y=cr_,line_color="#F85149",
                line_width=2,line_dash="solid",
                annotation_text=f"Crude ${cr_:.2f}/bbl",
                annotation_font_color="#F85149",annotation_font_size=10)
            fig_bar.update_layout(
                barmode="stack",
                title=dict(text="Revenue by Product vs Crude Cost ($/bbl)",
                           font=dict(color="#E6EDF3",size=12)),
                paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                yaxis=dict(title="$/bbl",gridcolor="#21262D"),
                xaxis=dict(gridcolor="#21262D"),
                legend=dict(bgcolor="#161B22",font=dict(size=9),
                            orientation="h",yanchor="bottom",y=1.05),
                margin=dict(l=0,r=0,t=36,b=0),height=320)
            st.plotly_chart(fig_bar, use_container_width=True)

        # ── Cost Transparency Panel ───────────────────────────────────────────
        _render_cost_transparency(n, r.get("spread_full"), tp, live_mode=True)

        # ── CSV download ───────────────────────────────────────────────────────
        st.markdown("---")
        dl_row = {
            "Location":           sel,
            "Throughput (bbl/d)": tp,
            "Retail Gas ($/gal)": r.get("retail_gas"),
            "Federal Tax":        r.get("federal_tax_gas"),
            "State Tax":          r.get("state_tax_gas"),
            "Pre-tax Gas":        r.get("pretax_gas"),
            "Distribution":       r.get("dist_margin"),
            "Wholesale Gas":      r.get("wholesale_gas"),
            "Wholesale Diesel":   r.get("wholesale_diesel"),
            "Light Crude ($/bbl)":r.get("crude_light"),
            "Heavy Crude":        r.get("crude_heavy"),
            "Jet ($/gal)":        jet_p,
            "Bunker ($/gal)":     bnk_p,
            "Asphalt ($/gal)":    asp_p,
            "LPG/Other ($/gal)":  lpg_p,
            "3-2-1 ($/bbl)":      r.get("spread_321"),
            "2-1-1 ($/bbl)":      r.get("spread_211"),
            "5-3-2 ($/bbl)":      r.get("spread_532"),
            "Full Yield GRM":     r.get("spread_full"),
            "Monthly GRM ($MM)":  pnl_v,
            "Crude bbl/day":      crude_bbl_day,
            "Gas bbl/day":        gas_bbl_day,
            "Diesel bbl/day":     die_bbl_day,
            "Jet bbl/day":        jet_bbl_day,
            "Bunker bbl/day":     bnk_bbl_day,
            "Asphalt tons/day":   asp_ton_day,
            "LPG bbl/day":        lpg_bbl_day,
            "Specialty Updated":  spec_date,
            "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        st.download_button(
            f"⬇️ Download {short} Today CSV",
            data=pd.DataFrame([dl_row]).to_csv(index=False),
            file_name=f"rogue_{short.replace(' ','_').lower()}_today.csv",
            mime="text/csv")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — FORWARD VIEW
    # Layout: Calculator (all visible) → Strip preview → Charts → Volume
    # ══════════════════════════════════════════════════════════════════════════
    with tab_fwd:
        rbob_spot = live_spot.get("rbob_gal",0) or 0
        ulsd_spot = live_spot.get("ulsd_gal",0) or 0
        wti_spot  = live_spot.get("wti_bbl", 0) or 0

        # ── CME anchor banner ─────────────────────────────────────────────────
        st.markdown(
            f"<div style='background:#161B22;border:1px solid #30363D;"
            f"border-radius:8px;padding:12px 16px;margin-bottom:14px'>"
            f"<span style='font-size:10px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:1px'>CME Spot Reference — Basis Anchor</span><br>"
            f"<span style='font-family:monospace;color:#E6EDF3'>"
            f"WTI {fmt_bbl(wti_spot)} &nbsp;·&nbsp; "
            f"RBOB {fmt_gal(rbob_spot)} &nbsp;·&nbsp; "
            f"ULSD {fmt_gal(ulsd_spot)}"
            f"</span><br>"
            f"<span style='font-size:10px;color:#484F58'>"
            f"CME strip drives WTI/RBOB/ULSD month-by-month. "
            f"Adjust basis below to model location differentials.</span>"
            f"</div>",
            unsafe_allow_html=True)

        # ── RESET BUTTON ──────────────────────────────────────────────────────
        if st.button("↺ Reset to Config Defaults", key=f"fwd_reset_{n}"):
            spec2 = sheet_prices.get(n, {})
            ulsd2 = live_spot.get("ulsd_gal",3.5) or 3.5
            wti2  = live_spot.get("wti_bbl",80)   or 80
            st.session_state.update({
                f"fwd_light_qual_{n}":   float(loc_cfg.get("light_quality_diff",    loc_cfg.get("light_diff",0))),
                f"fwd_light_tariff_{n}": float(loc_cfg.get("light_transport_tariff",2.50)),
                f"fwd_heavy_qual_{n}":   float(loc_cfg.get("heavy_quality_diff",    loc_cfg.get("heavy_diff",0))),
                f"fwd_heavy_tariff_{n}": float(loc_cfg.get("heavy_transport_tariff",2.50)),
                f"fwd_light_pct_{n}":    80.0,
                f"fwd_gas_basis_{n}":   float(loc_cfg.get("gas_diff",0)),
                f"fwd_die_basis_{n}":   float(loc_cfg.get("diesel_diff",0)),
                f"fwd_jet_{n}":         spec2.get("jet_gal",   ulsd2*1.05),
                f"fwd_jet_delta_{n}":   0.0,
                f"fwd_bunker_{n}":      spec2.get("bunker_gal",ulsd2*0.70),
                f"fwd_bunker_delta_{n}":0.0,
                f"fwd_asphalt_{n}":     spec2.get("asphalt_gal",ulsd2*0.60),
                f"fwd_asphalt_delta_{n}":0.0,
                f"fwd_lpg_{n}":         spec2.get("lpg_gal",round(wti2*0.50/42,3)),
                f"fwd_lpg_delta_{n}":   0.0,
                f"fwd_dist_{n}":        0.35,
            })
            st.rerun()

        # ── SECTION A: Crude slate — fully decomposed cost inputs ───────────────
        st.markdown(
            "<div style='background:#2A0D0D;border-radius:6px;padding:6px 12px;"
            "margin-bottom:8px;font-size:10px;color:#F85149'>"
            "🔴 CRUDE INLET COST — quality differential + pipeline/marine tariff "
            "= delivered cost at refinery gate · blended across light/heavy slate"
            "</div>",
            unsafe_allow_html=True)

        # Row 1: Light crude decomposition
        la1,la2,la3 = st.columns(3)
        la1.markdown("<div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
                     "letter-spacing:1px;margin-bottom:4px'>LIGHT CRUDE</div>",
                     unsafe_allow_html=True)
        light_qual = la1.number_input(
            "Quality diff vs WTI ($/bbl)",
            min_value=-20.0, max_value=20.0,
            value=float(st.session_state.get(f"fwd_light_qual_{n}",
                        loc_cfg.get("light_quality_diff", loc_cfg.get("light_diff",0)))),
            step=0.25, format="%.2f", key=f"fp_lq_{n}")
        st.session_state[f"fwd_light_qual_{n}"] = light_qual
        la1.caption(f"Crude grade premium/discount vs WTI light sweet")

        light_tariff = la2.number_input(
            "Pipeline/marine tariff ($/bbl)",
            min_value=0.0, max_value=20.0,
            value=float(st.session_state.get(f"fwd_light_tariff_{n}",
                        loc_cfg.get("light_transport_tariff", 2.50))),
            step=0.25, format="%.2f", key=f"fp_lt_{n}")
        st.session_state[f"fwd_light_tariff_{n}"] = light_tariff
        la2.caption(f"Field to refinery gate · default $2.50/bbl")

        light_pct = la3.number_input(
            "Light crude % of slate",
            min_value=0.0, max_value=100.0,
            value=float(st.session_state.get(f"fwd_light_pct_{n}", 80.0)),
            step=5.0, format="%.0f", key=f"fp_lp_{n}")
        st.session_state[f"fwd_light_pct_{n}"] = light_pct
        heavy_pct = 100.0 - light_pct
        light_total = round(light_qual + light_tariff, 2)
        eff_light_spot = round(wti_spot + light_total, 2)
        la3.caption(f"Heavy: {heavy_pct:.0f}% | Total light diff: {light_total:+.2f}/bbl")

        # Row 2: Heavy crude decomposition
        lb1,lb2,lb3 = st.columns(3)
        lb1.markdown("<div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
                     "letter-spacing:1px;margin-bottom:4px'>HEAVY CRUDE</div>",
                     unsafe_allow_html=True)
        heavy_qual = lb1.number_input(
            "Quality diff vs WTI ($/bbl) ",
            min_value=-20.0, max_value=20.0,
            value=float(st.session_state.get(f"fwd_heavy_qual_{n}",
                        loc_cfg.get("heavy_quality_diff", loc_cfg.get("heavy_diff",0)))),
            step=0.25, format="%.2f", key=f"fp_hq_{n}")
        st.session_state[f"fwd_heavy_qual_{n}"] = heavy_qual
        lb1.caption(f"Heavy sour discount vs WTI")

        heavy_tariff = lb2.number_input(
            "Pipeline/marine tariff ($/bbl) ",
            min_value=0.0, max_value=20.0,
            value=float(st.session_state.get(f"fwd_heavy_tariff_{n}",
                        loc_cfg.get("heavy_transport_tariff", 2.50))),
            step=0.25, format="%.2f", key=f"fp_ht_{n}")
        st.session_state[f"fwd_heavy_tariff_{n}"] = heavy_tariff
        lb2.caption(f"Field to refinery gate · default $2.50/bbl")

        heavy_total = round(heavy_qual + heavy_tariff, 2)
        eff_heavy_spot = round(wti_spot + heavy_total, 2)
        lb3.markdown(
            f"<div style='padding-top:28px;font-size:11px;color:#8B949E'>"
            f"Eff. spot heavy: ${eff_heavy_spot:.2f}/bbl<br>"
            f"({heavy_pct:.0f}% of slate)</div>",
            unsafe_allow_html=True)

        # Blended crude cost — core output of slate math
        light_f = light_pct / 100.0
        heavy_f = heavy_pct / 100.0
        blended_crude_diff = round(light_f * light_total + heavy_f * heavy_total, 4)
        blended_crude_spot = round(wti_spot + blended_crude_diff, 2)

        st.markdown(
            f"<div style='background:#21262D;border:1px solid #F85149;"
            f"border-radius:6px;padding:10px 16px;margin:8px 0 12px 0'>"
            f"<div style='display:flex;gap:32px;align-items:flex-start'>"
            f"<div>"
            f"<div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:1px'>Blended Delivered Crude Cost</div>"
            f"<div style='font-size:24px;font-weight:700;font-family:monospace;"
            f"color:#F85149'>${blended_crude_spot:.2f}/bbl</div>"
            f"</div>"
            f"<div style='font-size:11px;color:#8B949E;line-height:1.8'>"
            f"WTI spot: {fmt_bbl(wti_spot)}<br>"
            f"+ Blended diff: {blended_crude_diff:+.2f}/bbl<br>"
            f"= Delivered gate cost"
            f"</div>"
            f"<div style='font-size:11px;color:#8B949E;line-height:1.8'>"
            f"Light ({light_pct:.0f}%): quality {light_qual:+.2f} + tariff "
            f"+{light_tariff:.2f} = {light_total:+.2f}/bbl → ${eff_light_spot:.2f}/bbl<br>"
            f"Heavy ({heavy_pct:.0f}%): quality {heavy_qual:+.2f} + tariff "
            f"+{heavy_tariff:.2f} = {heavy_total:+.2f}/bbl → ${eff_heavy_spot:.2f}/bbl"
            f"</div>"
            f"</div></div>",
            unsafe_allow_html=True)

        # Product basis
        st.markdown(
            "<div style='background:#0D1A2A;border-radius:6px;padding:6px 12px;"
            "margin-bottom:8px;font-size:10px;color:#4A90D9'>"
            "🔵 PRODUCT MARKET BASIS — location differential vs NYMEX benchmark"
            "</div>",
            unsafe_allow_html=True)
        b4,b5 = st.columns(2)
        gas_basis = b4.number_input(
            "Gasoline vs RBOB ($/gal)",
            min_value=-1.0, max_value=1.0,
            value=float(st.session_state.get(f"fwd_gas_basis_{n}", loc_cfg.get("gas_diff",0))),
            step=0.01, format="%.3f", key=f"fp_gb_{n}")
        st.session_state[f"fwd_gas_basis_{n}"] = gas_basis
        b4.caption(f"Config: {loc_cfg.get('gas_diff',0):+.3f} | Eff. spot: ${rbob_spot+gas_basis:.3f}/gal | ${(rbob_spot+gas_basis)*42:.2f}/bbl")

        die_basis = b5.number_input(
            "Diesel vs ULSD ($/gal)",
            min_value=-1.0, max_value=1.0,
            value=float(st.session_state.get(f"fwd_die_basis_{n}", loc_cfg.get("diesel_diff",0))),
            step=0.01, format="%.3f", key=f"fp_db_{n}")
        st.session_state[f"fwd_die_basis_{n}"] = die_basis
        b5.caption(f"Config: {loc_cfg.get('diesel_diff',0):+.3f} | Eff. spot: ${ulsd_spot+die_basis:.3f}/gal | ${(ulsd_spot+die_basis)*42:.2f}/bbl")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── SECTION B: Specialty forward — green = OUTPUT REVENUES ───────────
        st.markdown(
            "<div style='background:#0D2A1A;border-radius:6px;padding:6px 12px;"
            "margin-bottom:8px;font-size:10px;color:#3FB950'>"
            "🟢 SPECIALTY PRODUCT FORWARD PRICES — output revenues · "
            "current Google Sheet price = baseline · delta = your forward adjustment"
            "</div>",
            unsafe_allow_html=True)

        sp1,sp2,sp3,sp4 = st.columns(4)
        jet_base    = float(st.session_state.get(f"fwd_jet_{n}",     spec.get("jet_gal",    4.07)))
        bnk_base    = float(st.session_state.get(f"fwd_bunker_{n}",  spec.get("bunker_gal", 2.52)))
        asp_base    = float(st.session_state.get(f"fwd_asphalt_{n}", spec.get("asphalt_gal",2.16)))
        lpg_base    = float(st.session_state.get(f"fwd_lpg_{n}",     spec.get("lpg_gal",    0.95)))

        jet_delta = sp1.number_input(
            f"Jet delta vs ${jet_base:.2f} today ($/gal)",
            min_value=-3.0, max_value=3.0,
            value=float(st.session_state.get(f"fwd_jet_delta_{n}", 0.0)),
            step=0.05, format="%.2f", key=f"fp_jd_{n}")
        st.session_state[f"fwd_jet_delta_{n}"] = jet_delta
        eff_jet = jet_base + jet_delta
        sp1.caption(f"Forward: ${eff_jet:.3f}/gal | ${eff_jet*42:.2f}/bbl")

        bnk_delta = sp2.number_input(
            f"Bunker delta vs ${bnk_base:.2f} today ($/gal)",
            min_value=-2.0, max_value=2.0,
            value=float(st.session_state.get(f"fwd_bunker_delta_{n}", 0.0)),
            step=0.05, format="%.2f", key=f"fp_bd_{n}")
        st.session_state[f"fwd_bunker_delta_{n}"] = bnk_delta
        eff_bunker = bnk_base + bnk_delta
        sp2.caption(f"Forward: ${eff_bunker:.3f}/gal | ${eff_bunker*42:.2f}/bbl")

        asp_delta = sp3.number_input(
            f"Asphalt delta vs ${asp_base:.2f} today ($/gal)",
            min_value=-2.0, max_value=2.0,
            value=float(st.session_state.get(f"fwd_asphalt_delta_{n}", 0.0)),
            step=0.05, format="%.2f", key=f"fp_ad_{n}")
        st.session_state[f"fwd_asphalt_delta_{n}"] = asp_delta
        eff_asphalt = asp_base + asp_delta
        sp3.caption(f"Forward: ${eff_asphalt:.3f}/gal | ${eff_asphalt*42:.2f}/bbl")

        lpg_delta = sp4.number_input(
            f"LPG delta vs ${lpg_base:.2f} today ($/gal)",
            min_value=-1.0, max_value=1.0,
            value=float(st.session_state.get(f"fwd_lpg_delta_{n}", 0.0)),
            step=0.01, format="%.2f", key=f"fp_ld_{n}")
        st.session_state[f"fwd_lpg_delta_{n}"] = lpg_delta
        eff_lpg = lpg_base + lpg_delta
        sp4.caption(f"Forward: ${eff_lpg:.3f}/gal | ${eff_lpg*42:.2f}/bbl")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── SECTION C: Refinery config — grey = CONVERSION ───────────────────
        st.markdown(
            "<div style='background:#1A1A2A;border-radius:6px;padding:6px 12px;"
            "margin-bottom:8px;font-size:10px;color:#8B949E'>"
            "⚙️ REFINERY CONFIGURATION — throughput & yield fractions "
            "(determines barrels of each product produced)"
            "</div>",
            unsafe_allow_html=True)

        YLBLS = {
            "gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
            "bunker":"Bunker","asphalt":"Asphalt",
            "lpg_other":"LPG/Other","refinery_use":"Ref. Use",
        }
        c1,c2,c3,c4,c5,c6,c7,c8 = st.columns(8)
        fwd_tp = int(c1.number_input(
            "Throughput (bbl/d)", 0, 500000,
            int(st.session_state.get(f"fwd_tp_{n}", 30000)),
            1000, key=f"fp_tp_{n}"))
        st.session_state[f"fwd_tp_{n}"] = fwd_tp
        fwd_dist = float(c2.number_input(
            "Dist margin ($/gal)", 0.0, 1.0,
            float(st.session_state.get(f"fwd_dist_{n}", 0.35)),
            0.01, "%.2f", key=f"fp_dist_{n}"))
        st.session_state[f"fwd_dist_{n}"] = fwd_dist

        fwd_yields = {}
        total_y = 0.0
        for col, (k, lbl) in zip([c3,c4,c5,c6,c7,c8], list(YLBLS.items())):
            default = round(YIELD_DEFAULTS.get(k,0)*100, 1)
            val = col.number_input(
                f"{lbl} (%)", 0.0, 100.0,
                float(st.session_state.get(f"fwd_y_{k}_{n}", default)),
                0.5, "%.1f", key=f"fp_y_{k}_{n}")
            st.session_state[f"fwd_y_{k}_{n}"] = val
            fwd_yields[k] = round(val/100, 6)
            total_y += val
        yc = "#3FB950" if total_y <= 100 else "#F85149"
        st.markdown(
            f"<span style='color:{yc};font-size:11px'>Yield total: {total_y:.1f}%</span>",
            unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Compute forward curve ─────────────────────────────────────────────
        # Use blended crude diff (light% × light_basis + heavy% × heavy_basis)
        loc_fwd = compute_forward_crack(
            strip=strip,
            crude_diff=blended_crude_diff, gas_diff=gas_basis,
            diesel_diff=die_basis,
            jet_fwd=eff_jet, bunker_fwd=eff_bunker,
            asphalt_fwd=eff_asphalt, lpg_fwd=eff_lpg,
            yields=fwd_yields)

        if not loc_fwd:
            st.info("Forward curve data not available. Check CME connection.")
        else:
            fwd_ok     = [row for row in loc_fwd if row.get("crack_321")]
            months     = [row["month"]       for row in fwd_ok]
            wti_fwd    = [row["wti"]         for row in fwd_ok]
            rbob_f     = [row.get("rbob",0)  for row in fwd_ok]
            ulsd_f     = [row.get("ulsd",0)  for row in fwd_ok]
            crack_vals = [row.get("crack_321") for row in fwd_ok]
            full_vals  = [row.get("crack_full") for row in fwd_ok]

            y_g2  = fwd_yields.get("gasoline",  0.445)
            y_d2  = fwd_yields.get("ulsd",      0.290)
            y_j2  = fwd_yields.get("jet",       0.110)
            y_b2  = fwd_yields.get("bunker",    0.035)
            y_a2  = fwd_yields.get("asphalt",   0.025)
            y_l2  = fwd_yields.get("lpg_other", 0.040)
            y_ru2 = fwd_yields.get("refinery_use",0.055)

            gas_rev = [round((rb+gas_basis)*y_g2*42, 2) for rb in rbob_f]
            die_rev = [round((ul+die_basis)*y_d2*42, 2) for ul in ulsd_f]
            jet_rev = [round(eff_jet    *y_j2*42, 2)] * len(months)
            bnk_rev = [round(eff_bunker *y_b2*42, 2)] * len(months)
            asp_rev = [round(eff_asphalt*y_a2*42, 2)] * len(months)
            lpg_rev = [round(eff_lpg    *y_l2*42, 2)] * len(months)
            grm_list= [round(v*fwd_tp*30/1e6,2) if v else None for v in crack_vals]

            # Price strip preview (next 6 months)
            st.markdown("<div class='sec-hdr'>Effective Forward Price Strip — Next 6 Months</div>",
                        unsafe_allow_html=True)
            if wti_fwd:
                strip_df = pd.DataFrame({
                    "Month":              months[:6],
                    "WTI+Blend ($/bbl)":  [f"${v+blended_crude_diff:.2f}"  for v in wti_fwd[:6]],
                    "RBOB+Basis ($/gal)": [f"${v+gas_basis:.3f}"    for v in rbob_f[:6]],
                    "ULSD+Basis ($/gal)": [f"${v+die_basis:.3f}"    for v in ulsd_f[:6]],
                    "Jet fwd ($/gal)":    [f"${eff_jet:.3f}"]    * 6,
                    "Bunker fwd ($/gal)": [f"${eff_bunker:.3f}"]  * 6,
                    "Asphalt fwd ($/gal)":[f"${eff_asphalt:.3f}"] * 6,
                    "LPG fwd ($/gal)":    [f"${eff_lpg:.3f}"]     * 6,
                    "3-2-1 GRM ($/bbl)":  [f"${v:.2f}" if v else "—" for v in crack_vals[:6]],
                    "Full Yield ($/bbl)": [f"${v:.2f}" if v else "—" for v in full_vals[:6]],
                    f"GRM $MM/mo ({fwd_tp//1000}k bbl/d)": [f"${v:.1f}MM" if v else "—" for v in grm_list[:6]],
                })
                st.dataframe(strip_df, use_container_width=True, hide_index=True)
                st.caption(
                    "WTI/RBOB/ULSD from CME settle strip + your basis adjustments · "
                    "Specialty products flat at forward assumption · "
                    "Green/amber/red = STRONG/MODERATE/THIN margin")

            st.markdown("<br>", unsafe_allow_html=True)

            # Chart 1: Area chart
            st.markdown("<div class='sec-hdr'>Forward Product Revenue vs Crude Cost</div>",
                        unsafe_allow_html=True)
            AREA_COLORS = {
                "Gasoline":  "rgba(74,144,217,0.75)",
                "Diesel":    "rgba(232,160,32,0.75)",
                "Jet Fuel":  "rgba(90,158,58,0.75)",
                "Bunker":    "rgba(139,79,191,0.75)",
                "Asphalt":   "rgba(204,119,34,0.75)",
                "LPG/Other": "rgba(58,166,185,0.75)",
            }
            fig_fwd = go.Figure()
            for name, vals in [
                ("Gasoline",  gas_rev), ("Diesel",    die_rev),
                ("Jet Fuel",  jet_rev), ("Bunker",    bnk_rev),
                ("Asphalt",   asp_rev), ("LPG/Other", lpg_rev),
            ]:
                fig_fwd.add_trace(go.Scatter(
                    x=months, y=vals, name=name,
                    mode="none", fill="tonexty",
                    fillcolor=AREA_COLORS[name],
                    stackgroup="one", line=dict(width=0)))
            # Adjust wti_fwd by blended diff for chart display
            wti_blend_fwd = [round(v+blended_crude_diff,2) for v in wti_fwd]
            fig_fwd.add_trace(go.Scatter(
                x=months, y=wti_blend_fwd, name="Blended Crude Cost",
                line=dict(color="#FFFFFF", width=2.5), mode="lines"))
            fig_fwd.add_trace(go.Scatter(
                x=months, y=crack_vals, name="3-2-1 Crack ($/bbl)",
                line=dict(color="#F85149", width=2, dash="dot"), yaxis="y2"))
            fig_fwd.update_layout(
                paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                xaxis=dict(gridcolor="#21262D", tickangle=-45),
                yaxis=dict(title="Product Revenue ($/bbl)", gridcolor="#21262D"),
                yaxis2=dict(
                    title=dict(text="3-2-1 Crack ($/bbl)", font=dict(color="#F85149")),
                    overlaying="y", side="right", showgrid=False,
                    tickfont=dict(color="#F85149")),
                legend=dict(bgcolor="#161B22", font=dict(size=10),
                            orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=0,r=60,t=30,b=0), height=380,
                hovermode="x unified")
            if months and wti_fwd:
                fig_fwd.add_annotation(
                    x=months[len(months)//2],
                    y=wti_blend_fwd[len(wti_blend_fwd)//2]+5,
                    text="↑ Gap = Margin", showarrow=False,
                    font=dict(color="#FFFFFF", size=10),
                    bgcolor="rgba(0,0,0,0.5)")
            st.plotly_chart(fig_fwd, use_container_width=True)
            st.caption(
                "Stacked areas = product revenues · "
                "Gas & diesel driven by CME strip + basis · "
                "Specialty products (jet/bunker/asphalt/LPG) held flat · "
                "White line = crude cost · Gap above white = margin · "
                "Red dashed (right axis) = 3-2-1 crack spread")

            # Chart 2: Stress ±20%
            fov = [v for v in full_vals if v is not None]
            fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
            if fov:
                fwd_dn = compute_forward_crack(
                    strip=strip,
                    crude_diff=blended_crude_diff+(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff=gas_basis-0.20, diesel_diff=die_basis-0.20,
                    jet_fwd=eff_jet*0.80, bunker_fwd=eff_bunker*0.80,
                    asphalt_fwd=eff_asphalt*0.80, lpg_fwd=eff_lpg*0.80,
                    yields=fwd_yields)
                fwd_up = compute_forward_crack(
                    strip=strip,
                    crude_diff=blended_crude_diff-(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff=gas_basis+0.20, diesel_diff=die_basis+0.20,
                    jet_fwd=eff_jet*1.20, bunker_fwd=eff_bunker*1.20,
                    asphalt_fwd=eff_asphalt*1.20, lpg_fwd=eff_lpg*1.20,
                    yields=fwd_yields)
                sdn=[row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
                sup=[row.get("crack_full") for row in fwd_up if row.get("crack_full")]
                mdn=[row["month"] for row in fwd_dn if row.get("crack_full")]
                mup=[row["month"] for row in fwd_up if row.get("crack_full")]

                st.markdown("<div class='sec-hdr'>Forward GRM Stress Test ±20%</div>",
                            unsafe_allow_html=True)
                fig_st = go.Figure()
                if sdn and len(sdn)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mdn+mdn[::-1], y=sdn+fov[::-1], fill="toself",
                        fillcolor="rgba(248,81,73,0.12)",
                        line=dict(width=0), name="Downside −20%", hoverinfo="skip"))
                if sup and len(sup)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mup+mup[::-1], y=sup+fov[::-1], fill="toself",
                        fillcolor="rgba(63,185,80,0.10)",
                        line=dict(width=0), name="Upside +20%", hoverinfo="skip"))
                fig_st.add_trace(go.Scatter(
                    x=fmo, y=fov, name="Full Yield GRM — Base",
                    line=dict(color="#E8A020", width=2.5),
                    mode="lines+markers", marker=dict(size=5)))
                if sdn:
                    fig_st.add_trace(go.Scatter(
                        x=mdn, y=sdn, name="Downside boundary",
                        line=dict(color="#F85149", width=1.5, dash="dash")))
                if sup:
                    fig_st.add_trace(go.Scatter(
                        x=mup, y=sup, name="Upside boundary",
                        line=dict(color="#3FB950", width=1.5, dash="dash")))
                fig_st.add_hline(y=15, line_dash="dot", line_color="#8B949E",
                    opacity=0.5, annotation_text="~Breakeven $15/bbl",
                    annotation_font_color="#8B949E", annotation_font_size=9)
                fig_st.update_layout(
                    title=dict(text="Full Yield GRM — Forward Stress ±20%",
                               font=dict(color="#E6EDF3", size=13)),
                    paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
                    font_color="#E6EDF3",
                    xaxis=dict(gridcolor="#21262D", tickangle=-45),
                    yaxis=dict(title="Full Yield GRM ($/bbl)", gridcolor="#21262D"),
                    legend=dict(bgcolor="#161B22", font=dict(size=10),
                                orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(l=0,r=0,t=40,b=0), height=320)
                st.plotly_chart(fig_st, use_container_width=True)
                st.caption(
                    "Base = Full Yield GRM at your basis assumptions · "
                    "Red = downside (crude +20%, products −20%) · "
                    "Green = upside (crude −20%, products +20%) · "
                    "Band width = margin sensitivity to ±20% price moves")

            # Chart 3: Monthly GRM bar
            st.markdown("<div class='sec-hdr'>Monthly GRM ($MM) — Forward View</div>",
                        unsafe_allow_html=True)
            fig_grm_mo = go.Figure()
            fig_grm_mo.add_trace(go.Bar(
                x=months, y=grm_list,
                marker_color=[spread_color(v) for v in crack_vals],
                text=[f"${v:.1f}MM" if v else "—" for v in grm_list],
                textposition="outside",
                textfont=dict(size=9, color="#E6EDF3"),
                name="Monthly GRM ($MM)"))
            fig_grm_mo.add_hline(y=0, line_color="#484F58", line_width=1)
            fig_grm_mo.update_layout(
                title=dict(
                    text=f"Monthly Gross Refining Margin @ {fwd_tp:,} bbl/day",
                    font=dict(color="#E6EDF3", size=12)),
                paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                xaxis=dict(gridcolor="#21262D", tickangle=-45),
                yaxis=dict(title="$MM/month", gridcolor="#21262D"),
                margin=dict(l=0,r=0,t=36,b=0), height=280, showlegend=False)
            st.plotly_chart(fig_grm_mo, use_container_width=True)

            # Operations / volume view
            st.markdown(
                f"<div class='sec-hdr'>Forward Operations View — "
                f"Volumes at {fwd_tp:,} bbl/day</div>",
                unsafe_allow_html=True)
            f_gas_bbl  = round(fwd_tp * y_g2)
            f_die_bbl  = round(fwd_tp * y_d2)
            f_jet_bbl  = round(fwd_tp * y_j2)
            f_bnk_bbl  = round(fwd_tp * y_b2)
            f_asp_bbl  = round(fwd_tp * y_a2)
            f_lpg_bbl  = round(fwd_tp * y_l2)
            f_ref_bbl  = round(fwd_tp * y_ru2)
            f_asp_tons = round(f_asp_bbl / 6.3, 1)

            f_light_bbl = round(fwd_tp * light_f)
            f_heavy_bbl = round(fwd_tp * heavy_f)
            fwd_ops_rows = [
                ("Light Crude",  "🔴 INPUT (cost)",   f_light_bbl, f"{f_light_bbl*42:,.0f}",
                 f"{f_light_bbl*30:,.0f}", f"WTI+{light_total:+.2f} = ${eff_light_spot:.2f}/bbl",
                 f"{light_pct:.0f}% of slate"),
                ("Heavy Crude",  "🔴 INPUT (cost)",   f_heavy_bbl, f"{f_heavy_bbl*42:,.0f}",
                 f"{f_heavy_bbl*30:,.0f}", f"WTI+{heavy_total:+.2f} = ${eff_heavy_spot:.2f}/bbl",
                 f"{heavy_pct:.0f}% of slate"),
                ("Blended Crude","🔴 TOTAL INPUT",    fwd_tp,      f"{fwd_tp*42:,.0f}",
                 f"{fwd_tp*30:,.0f}", f"Blended = ${blended_crude_spot:.2f}/bbl",
                 f"Weighted avg of slate"),
                ("Gasoline",     "🟢 OUTPUT (rev)",   f_gas_bbl, f"{f_gas_bbl*42:,.0f}",
                 f"{f_gas_bbl*30:,.0f}",f"CME RBOB+{gas_basis:+.3f}/gal",
                 f"Strip-driven price"),
                ("Diesel/ULSD",  "🟢 OUTPUT (rev)",   f_die_bbl, f"{f_die_bbl*42:,.0f}",
                 f"{f_die_bbl*30:,.0f}",f"CME ULSD+{die_basis:+.3f}/gal",
                 f"Strip-driven price"),
                ("Jet Fuel",     "🟢 OUTPUT (rev)",   f_jet_bbl, f"{f_jet_bbl*42:,.0f}",
                 f"{f_jet_bbl*30:,.0f}",f"${eff_jet:.3f}/gal flat",
                 f"${eff_jet*42:.2f}/bbl"),
                ("Bunker Fuel",  "🟢 OUTPUT (rev)",   f_bnk_bbl, f"{f_bnk_bbl*42:,.0f}",
                 f"{f_bnk_bbl*30:,.0f}",f"${eff_bunker:.3f}/gal flat",
                 f"${eff_bunker*42:.2f}/bbl"),
                ("Asphalt",      "🟢 OUTPUT (rev)",   f_asp_bbl, f"{f_asp_tons:.0f} t/day",
                 f"{f_asp_bbl*30:,.0f}",f"${eff_asphalt:.3f}/gal flat",
                 f"${eff_asphalt*42:.2f}/bbl | ÷6.3 bbl/ton"),
                ("LPG/Other",    "🟢 OUTPUT (rev)",   f_lpg_bbl, f"{f_lpg_bbl*42:,.0f}",
                 f"{f_lpg_bbl*30:,.0f}",f"${eff_lpg:.3f}/gal flat",
                 f"${eff_lpg*42:.2f}/bbl"),
                ("Refinery Use", "⚫ LOSS (no rev)",  f_ref_bbl, "—",
                 f"{f_ref_bbl*30:,.0f}","Burned onsite",
                 "Fuel gas + processing losses"),
            ]
            fwd_ops_df = pd.DataFrame(fwd_ops_rows, columns=[
                "Stream", "Type", "bbl/day",
                "gal or tons/day", "bbl/month",
                "Forward Price", "Notes"])
            fwd_ops_df["bbl/day"] = fwd_ops_df["bbl/day"].apply(
                lambda x: f"{int(x):,}" if isinstance(x,(int,float)) else x)
            st.dataframe(fwd_ops_df, use_container_width=True, hide_index=True)
            st.caption(
                "Gas & diesel priced from CME forward strip + location basis · "
                "Specialty products flat at your forward assumption · "
                "Asphalt in short tons (6.3 bbl/short ton) · "
                "bbl/month = daily × 30")

            # Full forward GRM table + download
            fwd_df = pd.DataFrame({
                "Month":               months,
                "WTI+Blend ($/bbl)":   [round(v+blended_crude_diff, 2) for v in wti_fwd],
                "RBOB+Basis ($/gal)":  [round(v+gas_basis,   3) for v in rbob_f],
                "ULSD+Basis ($/gal)":  [round(v+die_basis,   3) for v in ulsd_f],
                "Jet Fwd ($/gal)":     [eff_jet]     * len(months),
                "Bunker Fwd ($/gal)":  [eff_bunker]  * len(months),
                "Asphalt Fwd ($/gal)": [eff_asphalt] * len(months),
                "LPG Fwd ($/gal)":     [eff_lpg]     * len(months),
                "3-2-1 GRM ($/bbl)":   crack_vals,
                "Full Yield ($/bbl)":  full_vals,
                f"GRM $MM/mo @ {fwd_tp//1000}k bbl/d": grm_list,
            })
            with st.expander("📋 Full Forward GRM Table + Download"):
                st.dataframe(fwd_df, use_container_width=True, hide_index=True)
                st.download_button(
                    f"⬇️ Download {short} Forward CSV",
                    data=fwd_df.to_csv(index=False),
                    file_name=f"rogue_{short.replace(' ','_').lower()}_forward.csv",
                    mime="text/csv")



# ══════════════════════════════════════════════════════════════════════════════
# METHODOLOGY
# ══════════════════════════════════════════════════════════════════════════════
def show_methodology():
    with st.expander("📋 Methodology & Data Sources", expanded=False):
        st.markdown("""
<div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

### What this tool calculates
**Gross Refining Margin (GRM)** = Σ(Product Price × Yield × 42) − Crude Cost.
Operating costs ($4–8/bbl) are **not** deducted.

### Two views
**Today:** 100% live data. Read-only. AAA gas/diesel daily, CME crude,
Google Sheet specialty prices.

**Forward:** Basis-driven model. CME forward strip provides WTI/RBOB/ULSD
month-by-month. You adjust *basis* (location differential vs NYMEX benchmark)
and specialty product forward assumptions. All other prices follow the curve.

### Price sources
| Input | Source | Frequency |
|---|---|---|
| Retail gas & diesel | AAA Fuel Gauge metro survey | Daily |
| WTI, RBOB, ULSD spot | CME first-month settle | Daily |
| WTI, RBOB, ULSD forward | CME settle strip (local xlsx) | Daily |
| Jet, Bunker, Asphalt, LPG | Google Sheet (per location) | Weekly |
| Federal excise tax | IRS — fixed since Oct 1993 | Static |
| State excise taxes | FTA + EIA, Jul 2025 | Semiannual |

### Price waterfall
Retail pump (AAA) − Federal excise ($0.184 gas / $0.244 diesel) − State excise
− Distribution ($0.35/gal default) = Wholesale / refinery gate price

### State excise taxes (Jul 2025)
AK $0.0895 · TX $0.200 · OK $0.190 · ND $0.230 · UT $0.385 · LA $0.200 · NM $0.229/$0.270

### Full Yield defaults (EIA 2024 national average)
Gas 44.5% · Diesel 29.0% · Jet 11.0% · Bunker 3.5% · Asphalt 2.5% · LPG/Other 4.0% · Ref. Use 5.5% = 100%
Source: EIA PSM 2024 / eia.gov/todayinenergy/detail.php?id=64786

### Not captured
Opex ($3–8/bbl) · RINs · Blendstock costs · Pipeline tariffs · Carbon · Hedging

</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    check_password()

    st.markdown(
        "<h2 style='color:#E6EDF3;margin-bottom:2px;margin-top:-8px'>"
        "🏭 Rogue Refinery Economics</h2>"
        "<p style='color:#8B949E;margin-bottom:10px;font-size:12px'>"
        "Portfolio intelligence · CME forward curves · Gross Refining Margin</p>",
        unsafe_allow_html=True)

    with st.sidebar:
        st.markdown(
            "<div style='text-align:center;padding:10px 0'>"
            "<span style='font-size:26px'>🏭</span><br>"
            "<span style='color:#E8A020;font-weight:700;font-size:13px;"
            "letter-spacing:2px'>ROGUE REFINERY</span><br>"
            "<span style='color:#8B949E;font-size:10px;letter-spacing:1px'>"
            "ECONOMICS DASHBOARD</span></div>",
            unsafe_allow_html=True)
        st.markdown("---")
        if st.button("📋 Management Report", use_container_width=True):
            st.session_state["view"] = "report"
            st.rerun()
        if st.button("🔄 Refresh All Data", use_container_width=True):
            get_cme.clear(); get_spot.clear()
            get_lp.clear();  get_spec.clear()
            get_specialty_sheet.clear()
            auth = st.session_state.get("auth")
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            if auth: st.session_state["auth"] = auth
            st.rerun()
        st.markdown("---")
        st.caption(
            "**Today:** live prices — read only.\n\n"
            "**Forward:** CME strip + location basis.\n\n"
            "Specialty prices (jet/bunker/asphalt/LPG) updated "
            "weekly via Google Sheet.")

    with st.spinner("Loading market data..."):
        strip        = get_cme()
        lp           = get_lp()
        sheet_prices = get_specialty_sheet()
        live_spot    = get_spot()

    live_margins, _, _ = build_live_margins(lp, sheet_prices)
    render_ticker(live_spot, live_margins)

    view = st.session_state.get("view","portfolio")
    if view == "portfolio":
        show_portfolio(live_margins)
        show_methodology()
    elif view == "report":
        show_management_report(live_margins, strip, sheet_prices, live_spot)
    else:
        show_detail(live_margins, strip, sheet_prices, live_spot)

    st.markdown(
        f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
        f"AAA Fuel Gauge · EIA API · CME local xlsx · Google Sheet · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()


# ══════════════════════════════════════════════════════════════════════════════
# MANAGEMENT REPORT
# ══════════════════════════════════════════════════════════════════════════════
def _fwd_averages(strip, loc_cfg, n, sheet_prices, live_spot):
    """
    Compute forward crack averages for a location using session state
    basis values if set, otherwise config defaults.
    Returns dict with keys: months_3, months_6, months_12, months_24
    Each value: {crack_321, crack_full, net_margin, grm_mm}
    """
    # Pull basis from session state (user may have tuned in dashboard)
    # Fall back to config defaults if not set
    light_qual    = st.session_state.get(f"fwd_light_qual_{n}",
                    loc_cfg.get("light_quality_diff",    loc_cfg.get("light_diff",0)))
    light_tariff  = st.session_state.get(f"fwd_light_tariff_{n}",
                    loc_cfg.get("light_transport_tariff", 2.50))
    heavy_qual    = st.session_state.get(f"fwd_heavy_qual_{n}",
                    loc_cfg.get("heavy_quality_diff",    loc_cfg.get("heavy_diff",0)))
    heavy_tariff  = st.session_state.get(f"fwd_heavy_tariff_{n}",
                    loc_cfg.get("heavy_transport_tariff", 2.50))
    light_pct     = st.session_state.get(f"fwd_light_pct_{n}", 80.0)
    light_f       = light_pct / 100.0
    heavy_f       = 1.0 - light_f
    light_total   = light_qual + light_tariff
    heavy_total   = heavy_qual + heavy_tariff
    blended_diff  = round(light_f * light_total + heavy_f * heavy_total, 4)

    gas_basis     = st.session_state.get(f"fwd_gas_basis_{n}",  loc_cfg.get("gas_diff",0))
    die_basis     = st.session_state.get(f"fwd_die_basis_{n}",  loc_cfg.get("diesel_diff",0))

    spec          = sheet_prices.get(n, {})
    ulsd          = live_spot.get("ulsd_gal",3.5) or 3.5
    wti           = live_spot.get("wti_bbl",80)   or 80

    jet_base      = st.session_state.get(f"fwd_jet_{n}",     spec.get("jet_gal",    ulsd*1.05))
    jet_delta     = st.session_state.get(f"fwd_jet_delta_{n}", 0.0)
    bnk_base      = st.session_state.get(f"fwd_bunker_{n}",  spec.get("bunker_gal", ulsd*0.70))
    bnk_delta     = st.session_state.get(f"fwd_bunker_delta_{n}", 0.0)
    asp_base      = st.session_state.get(f"fwd_asphalt_{n}", spec.get("asphalt_gal",ulsd*0.60))
    asp_delta     = st.session_state.get(f"fwd_asphalt_delta_{n}", 0.0)
    lpg_base      = st.session_state.get(f"fwd_lpg_{n}",     spec.get("lpg_gal",round(wti*0.50/42,3)))
    lpg_delta     = st.session_state.get(f"fwd_lpg_delta_{n}", 0.0)

    eff_jet       = jet_base + jet_delta
    eff_bunker    = bnk_base + bnk_delta
    eff_asphalt   = asp_base + asp_delta
    eff_lpg       = lpg_base + lpg_delta

    fwd_yields    = {k: round(st.session_state.get(f"fwd_y_{k}_{n}",
                    YIELD_DEFAULTS.get(k,0)*100)/100, 6)
                    for k in YIELD_DEFAULTS}

    tp            = int(st.session_state.get(f"fwd_tp_{n}", loc_cfg.get("throughput",30000)))

    # Opex deductions from session state
    total_deductions = sum(
        float(st.session_state.get(k, d)) for k,d in [
            (f"ct_opex_{n}",           4.00),
            (f"ct_prod_transport_{n}",  0.50),
            (f"ct_blendstock_{n}",      1.20),
            (f"ct_rin_{n}",             0.80),
            (f"ct_maintenance_{n}",     0.75),
        ]
    )

    loc_fwd = compute_forward_crack(
        strip=strip, crude_diff=blended_diff,
        gas_diff=gas_basis, diesel_diff=die_basis,
        jet_fwd=eff_jet, bunker_fwd=eff_bunker,
        asphalt_fwd=eff_asphalt, lpg_fwd=eff_lpg,
        yields=fwd_yields)

    if not loc_fwd:
        return None

    valid = [r for r in loc_fwd if r.get("crack_321") is not None]
    if not valid:
        return None

    def _avg(rows, field):
        vals = [r.get(field) for r in rows if r.get(field) is not None]
        return round(sum(vals)/len(vals), 2) if vals else None

    def _period(rows):
        c321  = _avg(rows, "crack_321")
        cfull = _avg(rows, "crack_full")
        net   = round(cfull - total_deductions, 2) if cfull else None
        grm_mm= round(cfull * tp * 30 / 1e6, 2)  if cfull else None
        net_mm= round(net   * tp * 30 / 1e6, 2)  if net   else None
        return {"crack_321": c321, "crack_full": cfull,
                "net": net, "grm_mm": grm_mm, "net_mm": net_mm}

    return {
        "3mo":  _period(valid[:3]),
        "6mo":  _period(valid[:6]),
        "12mo": _period(valid[:12]),
        "24mo": _period(valid[:24]),
        "monthly": valid,
        "deductions": total_deductions,
        "tp": tp,
    }


def show_management_report(live_margins, strip, sheet_prices, live_spot):
    """
    Management Report — scrolling one-card-per-location view.
    Read-only. Uses live data for Today, session state basis for Forward.
    """
    # ── Header ────────────────────────────────────────────────────────────────
    rpt_top, rpt_back = st.columns([5,1])
    with rpt_back:
        if st.button("← Dashboard", use_container_width=True):
            st.session_state["view"] = "portfolio"
            st.rerun()
    with rpt_top:
        st.markdown(
            f"<h3 style='color:#E6EDF3;margin:0'>📋 Management Report</h3>"
            f"<p style='color:#8B949E;font-size:11px;margin:2px 0 10px 0'>"
            f"All locations · Live market prices · "
            f"{datetime.now().strftime('%B %d, %Y %H:%M')} UTC</p>",
            unsafe_allow_html=True)

    # ── Portfolio summary table ───────────────────────────────────────────────
    st.markdown("<div class='sec-hdr'>Portfolio Summary</div>",
                unsafe_allow_html=True)

    summary_rows = []
    for r in live_margins:
        n   = r["display"]
        loc = next((l for l in LOCATIONS if l["display"]==n), {})
        tp  = r.get("throughput",30000)
        sfull = r.get("spread_full")
        deductions = sum(
            float(st.session_state.get(k, d)) for k,d in [
                (f"ct_opex_{n}",4.00),(f"ct_prod_transport_{n}",0.50),
                (f"ct_blendstock_{n}",1.20),(f"ct_rin_{n}",0.80),
                (f"ct_maintenance_{n}",0.75),
            ])
        net = round(sfull - deductions, 2) if sfull else None
        grm_mm = fmt_grm(sfull, tp)
        net_mm = round(net * tp * 30 / 1e6, 2) if net else None

        fwd = _fwd_averages(strip, loc, n, sheet_prices, live_spot)
        f12 = fwd["12mo"]["crack_full"] if fwd else None

        summary_rows.append({
            "Location":             n.split("—")[-1].split(",")[0].strip(),
            "Today GRM ($/bbl)":    f"${sfull:.2f}" if sfull else "—",
            "Est. Net ($/bbl)":     f"${net:.2f}"   if net   else "—",
            "GRM/mo ($MM)":         f"${grm_mm:.1f}MM" if grm_mm else "—",
            "12mo Fwd Full Yield":  f"${f12:.2f}"   if f12   else "—",
            "Status":               spread_label(sfull),
        })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True,
                 hide_index=True)

    st.markdown("---")

    # ── One card per location ─────────────────────────────────────────────────
    for r in live_margins:
        n   = r["display"]
        loc = next((l for l in LOCATIONS if l["display"]==n), {})
        tp  = r.get("throughput",30000)
        spec= r.get("specialty",{})

        s321  = r.get("spread_321")
        sfull = r.get("spread_full")
        s211  = r.get("spread_211")
        s532  = r.get("spread_532")
        cr_   = r.get("crude_light",0) or 0
        ws_g  = r.get("wholesale_gas",0) or 0
        ws_d  = r.get("wholesale_diesel",0) or 0
        jet_p = spec.get("jet_gal",    SPECIALTY_DEFAULTS["jet_gal"])
        bnk_p = spec.get("bunker_gal", SPECIALTY_DEFAULTS["bunker_gal"])
        asp_p = spec.get("asphalt_gal",SPECIALTY_DEFAULTS["asphalt_gal"])
        lpg_p = spec.get("lpg_gal",    SPECIALTY_DEFAULTS.get("lpg_gal",0.95))

        yields = {k: v for k, v in YIELD_DEFAULTS.items()}
        y_g = yields.get("gasoline",0.445);  y_d = yields.get("ulsd",0.290)
        y_j = yields.get("jet",0.110);       y_b = yields.get("bunker",0.035)
        y_a = yields.get("asphalt",0.025);   y_l = yields.get("lpg_other",0.040)
        _sal = y_g+y_d+y_j+y_b+y_a+y_l

        gc_=round(ws_g*y_g*42,2); dc_=round(ws_d*y_d*42,2)
        jc_=round(jet_p*y_j*42,2);bc_=round(bnk_p*y_b*42,2)
        ac_=round(asp_p*y_a*42,2);lc_=round(lpg_p*y_l*42,2)
        total_rev = gc_+dc_+jc_+bc_+ac_+lc_
        grm_full  = round(total_rev - cr_, 2)
        pnl_v     = fmt_grm(s321, tp)

        # Opex deductions
        opex_items = [
            ("Refinery Opex",        f"ct_opex_{n}",           4.00),
            ("Product Transport",    f"ct_prod_transport_{n}",  0.50),
            ("Blendstock Costs",     f"ct_blendstock_{n}",      1.20),
            ("RIN Obligations",      f"ct_rin_{n}",             0.80),
            ("Maintenance & T/A",    f"ct_maintenance_{n}",     0.75),
        ]
        total_ded = sum(float(st.session_state.get(k,d)) for _,k,d in opex_items)
        net_margin= round(grm_full - total_ded, 2) if grm_full else None
        net_mm    = round(net_margin * tp * 30 / 1e6, 2) if net_margin else None

        # Forward averages
        fwd = _fwd_averages(strip, loc, n, sheet_prices, live_spot)

        clr = spread_color(sfull)
        short = n.split("—")[-1].split(",")[0].strip()

        # ── Location header ───────────────────────────────────────────────────
        st.markdown(
            f"<div style='background:#161B22;border:1px solid {clr};"
            f"border-radius:10px;padding:16px 20px;margin-bottom:12px'>"
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:center;flex-wrap:wrap;gap:12px'>"
            f"<div>"
            f"<div style='font-size:11px;color:#8B949E;text-transform:uppercase;"
            f"letter-spacing:2px;margin-bottom:4px'>{n}</div>"
            f"<div style='font-size:36px;font-weight:700;font-family:monospace;"
            f"color:{clr};line-height:1'>{'$'+str(grm_full)+'/bbl' if grm_full else '—'}</div>"
            f"<div style='font-size:12px;color:{clr};letter-spacing:1px;margin-top:2px'>"
            f"FULL YIELD GRM · {spread_label(grm_full)}</div>"
            f"</div>"
            f"<div style='display:flex;gap:20px;flex-wrap:wrap'>"
            f"<div style='text-align:center'>"
            f"<div style='font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px'>3-2-1 Ref</div>"
            f"<div style='font-size:20px;font-weight:700;font-family:monospace;color:{spread_color(s321)}'>"
            f"{'$'+str(s321) if s321 else '—'}</div></div>"
            f"<div style='text-align:center'>"
            f"<div style='font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px'>Est. Net</div>"
            f"<div style='font-size:20px;font-weight:700;font-family:monospace;"
            f"color:{spread_color(net_margin)}'>"
            f"{'$'+str(net_margin)+'/bbl' if net_margin else '—'}</div></div>"
            f"<div style='text-align:center'>"
            f"<div style='font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px'>GRM/mo</div>"
            f"<div style='font-size:20px;font-weight:700;font-family:monospace;color:#3FB950'>"
            f"{'$'+str(pnl_v)+'MM' if pnl_v else '—'}</div></div>"
            f"<div style='text-align:center'>"
            f"<div style='font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px'>Net/mo</div>"
            f"<div style='font-size:20px;font-weight:700;font-family:monospace;"
            f"color:{spread_color(net_margin)}'>"
            f"{'$'+str(net_mm)+'MM' if net_mm else '—'}</div></div>"
            f"</div></div></div>",
            unsafe_allow_html=True)

        col_left, col_right = st.columns([1,1], gap="large")

        with col_left:
            # ── Revenue breakdown horizontal bar ──────────────────────────────
            st.markdown("<div class='sec-hdr'>Revenue Contribution by Product</div>",
                        unsafe_allow_html=True)
            PROD_DATA = [
                ("Gasoline", gc_, "#4A90D9"),
                ("Diesel",   dc_, "#E8A020"),
                ("Jet Fuel", jc_, "#5A9E3A"),
                ("Bunker",   bc_, "#8B4FBF"),
                ("Asphalt",  ac_, "#CC7722"),
                ("LPG/Other",lc_, "#3AA6B9"),
            ]
            bar_html = "<div style='margin-top:4px'>"
            for prod, val, clr2 in PROD_DATA:
                pct = round(val/total_rev*100,1) if total_rev else 0
                w   = max(pct, 2)
                bar_html += (
                    f"<div style='display:flex;align-items:center;margin-bottom:5px;gap:8px'>"
                    f"<div style='width:80px;font-size:10px;color:#8B949E;text-align:right'>{prod}</div>"
                    f"<div style='flex:1;background:#21262D;border-radius:3px;height:18px'>"
                    f"<div style='width:{w}%;background:{clr2};border-radius:3px;height:18px;"
                    f"display:flex;align-items:center;padding-left:6px'>"
                    f"<span style='font-size:10px;font-weight:600;color:#E6EDF3'>{pct}%</span>"
                    f"</div></div>"
                    f"<div style='width:60px;font-size:10px;color:#E6EDF3;font-family:monospace'>"
                    f"${val:.1f}</div>"
                    f"</div>"
                )
            bar_html += "</div>"
            st.markdown(bar_html, unsafe_allow_html=True)
            st.caption("$/bbl contribution · % of total product revenue")

            # ── GRM → Net waterfall table ─────────────────────────────────────
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='sec-hdr'>Gross → Net Margin Waterfall</div>",
                        unsafe_allow_html=True)
            wf_rows = [("Gross Refining Margin", grm_full, "#E8A020", True)]
            running = grm_full or 0
            for label, key, default in opex_items:
                val = float(st.session_state.get(key, default))
                running = round(running - val, 2)
                wf_rows.append((f"  − {label}", -val, "#F85149", False))
            wf_rows.append(("Est. Net Margin", net_margin, spread_color(net_margin), True))

            wf_html = "<div style='font-family:monospace;font-size:12px'>"
            for label, val, clr2, is_total in wf_rows:
                weight = "700" if is_total else "400"
                border = f"border-top:1px solid #30363D;margin-top:4px;padding-top:4px" if is_total else ""
                wf_html += (
                    f"<div style='display:flex;justify-content:space-between;"
                    f"padding:3px 0;{border}'>"
                    f"<span style='color:#{'E6EDF3' if is_total else '8B949E'};font-weight:{weight}'>"
                    f"{label}</span>"
                    f"<span style='color:{clr2};font-weight:{weight}'>"
                    f"{'$'+str(abs(val))+'  ' if val and val<0 else ('$'+str(val)+'/bbl' if val else '—')}"
                    f"</span></div>"
                )
            wf_html += "</div>"
            st.markdown(wf_html, unsafe_allow_html=True)
            st.caption("Est. Net Margin uses benchmark opex · adjust in Cost Transparency panel")

        with col_right:
            # ── Stress test 2×2 ───────────────────────────────────────────────
            st.markdown("<div class='sec-hdr'>Stress Test — 3-2-1 Crack Spread</div>",
                        unsafe_allow_html=True)
            crude_b = r.get("crude_light", cr_)
            gas_b   = r.get("wholesale_gas",  ws_g)
            die_b   = r.get("wholesale_diesel",ws_d)
            base    = s321 or 0
            scenarios = [
                ("Crude +25%",    crude_b*1.25, gas_b,      die_b),
                ("Products +25%", crude_b,      gas_b*1.25, die_b*1.25),
                ("Crude −25%",    crude_b*0.75, gas_b,      die_b),
                ("Products −25%", crude_b,      gas_b*0.75, die_b*0.75),
            ]
            r1c1,r1c2 = st.columns(2)
            r2c1,r2c2 = st.columns(2)
            for col,(lbl,c,g,d) in zip([r1c1,r1c2,r2c1,r2c2],scenarios):
                val   = round(_c321(c,g,d),2)
                delta = round(val-base,2)
                is_up = delta >= 0
                bg    = "#0D2A1A" if is_up else "#2A0D0D"
                clr2  = "#3FB950" if is_up else "#F85149"
                sign  = "▲" if is_up else "▼"
                col.markdown(f"""
                <div style='background:{bg};border-radius:8px;padding:12px;
                     text-align:center;margin-bottom:6px'>
                  <div style='font-size:9px;color:{clr2};letter-spacing:1px;
                       text-transform:uppercase;font-weight:600'>{lbl}</div>
                  <div style='font-size:10px;color:#8B949E;margin:2px 0'>
                      Base: ${base:.2f}</div>
                  <div style='font-size:22px;font-weight:700;
                       font-family:monospace;color:{clr2}'>${val:.2f}</div>
                  <div style='font-size:11px;color:{clr2}'>{sign} {sign_str(delta)}/bbl</div>
                </div>""", unsafe_allow_html=True)

            # ── Forward averages table ────────────────────────────────────────
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='sec-hdr'>Forward Economics — Period Averages</div>",
                        unsafe_allow_html=True)
            if fwd:
                periods = [("3 Month",fwd["3mo"]),("6 Month",fwd["6mo"]),
                           ("12 Month",fwd["12mo"]),("24 Month",fwd["24mo"])]
                fwd_html = (
                    "<table style='width:100%;border-collapse:collapse;"
                    "font-size:11px;font-family:monospace'>"
                    "<tr>"
                    "<th style='color:#8B949E;font-weight:400;text-align:left;"
                    "padding:4px 8px 4px 0'>Period</th>"
                    "<th style='color:#8B949E;font-weight:400;text-align:right;"
                    "padding:4px 4px'>3-2-1</th>"
                    "<th style='color:#8B949E;font-weight:400;text-align:right;"
                    "padding:4px 4px'>Full Yield</th>"
                    "<th style='color:#8B949E;font-weight:400;text-align:right;"
                    "padding:4px 4px'>Est. Net</th>"
                    "<th style='color:#8B949E;font-weight:400;text-align:right;"
                    "padding:4px 0'>GRM/mo</th>"
                    "</tr>"
                )
                for period, p in periods:
                    c321_v = f"${p['crack_321']:.2f}" if p.get("crack_321") else "—"
                    cfull_v= f"${p['crack_full']:.2f}" if p.get("crack_full") else "—"
                    net_v  = f"${p['net']:.2f}" if p.get("net") else "—"
                    mm_v   = f"${p['grm_mm']:.1f}MM" if p.get("grm_mm") else "—"
                    net_clr= spread_color(p.get("net"))
                    fwd_html += (
                        f"<tr style='border-top:1px solid #21262D'>"
                        f"<td style='color:#E6EDF3;padding:5px 8px 5px 0'>{period}</td>"
                        f"<td style='color:{spread_color(p.get('crack_321'))};text-align:right;"
                        f"padding:5px 4px'>{c321_v}</td>"
                        f"<td style='color:{spread_color(p.get('crack_full'))};text-align:right;"
                        f"padding:5px 4px'>{cfull_v}</td>"
                        f"<td style='color:{net_clr};text-align:right;"
                        f"padding:5px 4px'>{net_v}</td>"
                        f"<td style='color:#3FB950;text-align:right;"
                        f"padding:5px 0'>{mm_v}</td>"
                        f"</tr>"
                    )
                fwd_html += "</table>"
                st.markdown(fwd_html, unsafe_allow_html=True)

                # Sparkline — forward Full Yield GRM trend
                months_all  = [row["month"] for row in fwd["monthly"] if row.get("crack_full")]
                fullvals_all= [row["crack_full"] for row in fwd["monthly"] if row.get("crack_full")]
                if fullvals_all:
                    fig_spark = go.Figure()
                    fig_spark.add_trace(go.Scatter(
                        x=months_all, y=fullvals_all,
                        mode="lines",
                        line=dict(color=spread_color(fullvals_all[0]), width=2),
                        fill="tozeroy",
                        fillcolor="rgba(63,185,80,0.08)" if fullvals_all[0]>=25
                                  else "rgba(232,160,32,0.08)",
                    ))
                    fig_spark.add_hline(y=15, line_dash="dot",
                        line_color="#484F58", opacity=0.5)
                    fig_spark.update_layout(
                        paper_bgcolor="#0D1117", plot_bgcolor="#0D1117",
                        margin=dict(l=0,r=0,t=4,b=0), height=80,
                        showlegend=False,
                        xaxis=dict(visible=False),
                        yaxis=dict(visible=False))
                    st.plotly_chart(fig_spark, use_container_width=True)
                st.caption(
                    f"Basis: config defaults"
                    f"{' (may reflect dashboard overrides)' if st.session_state.get(f'_fwd_init_{n}') else ''}"
                    f" · deductions ${fwd['deductions']:.2f}/bbl")
            else:
                st.info("Forward curve not available.")

        st.markdown("---")

    # Footer
    st.markdown(
        f"<div style='color:#484F58;font-size:10px;text-align:center;margin-top:4px'>"
        f"Rogue Refinery Economics · Management Report · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC · "
        f"GRM is gross margin before opex · Net margin uses benchmark estimates"
        f"</div>",
        unsafe_allow_html=True)



# # app.py — Rogue Refinery Economics v6
# # Today tab: clean 3-panel layout, no clutter
# # Forward tab: basis-driven inputs against CME curve
# import streamlit as st
# import streamlit.components.v1 as components
# import pandas as pd
# import plotly.graph_objects as go
# from datetime import datetime

# from config import (
#     LOCATIONS, YIELD_DEFAULTS, SPECIALTY_DEFAULTS,
#     EIA_API_KEY, FRED_API_KEY,
# )
# from fetchers.prices import (
#     fetch_spot_prices,
#     fetch_cme_forward_curve,
#     compute_forward_crack,
#     fetch_location_prices,
#     fetch_specialty_prices,
# )
# from engine.location_margins import compute_location_margins
# from engine.crack import crack_321 as _c321


# def _scroll_top():
#     components.html("""<script>
#     (function(){function s(){var e=['[data-testid="stAppViewContainer"]',
#     '[data-testid="stMain"]','.main','body'];
#     for(var i=0;i<e.length;i++){var el=window.parent.document.querySelector(e[i]);
#     if(el)el.scrollTop=0;}window.parent.scrollTo(0,0);}
#     s();setTimeout(s,150);setTimeout(s,400);})();
#     </script>""", height=0)


# st.set_page_config(page_title="Rogue Refinery Economics",
#                    page_icon="🏭", layout="wide")

# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:12px 0 8px 0}
# .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
#   padding:14px 16px;cursor:pointer}
# .loc-card:hover{border-color:#E8A020}
# .loc-card-name{font-size:11px;color:#8B949E;text-transform:uppercase;
#   letter-spacing:1px;margin-bottom:4px}
# .loc-card-spread{font-size:26px;font-weight:700;font-family:monospace}
# .loc-card-badge{display:inline-block;font-size:9px;font-weight:600;
#   letter-spacing:1px;padding:2px 8px;border-radius:4px;margin-top:4px}
# .loc-card-pnl{font-size:11px;color:#8B949E;margin-top:4px}
# .badge-strong{background:#0D2A1A;color:#3FB950}
# .badge-moderate{background:#2A1F08;color:#E8A020}
# .badge-thin{background:#2A0D0D;color:#F85149}
# /* Headline GRM card — larger, more visual weight */
# .grm-hero{background:#161B22;border:1px solid #E8A020;border-radius:12px;
#   padding:28px 20px;text-align:center}
# .grm-hero-label{font-size:10px;color:#8B949E;text-transform:uppercase;
#   letter-spacing:2px;margin-bottom:8px}
# .grm-hero-value{font-size:52px;font-weight:700;font-family:monospace;
#   line-height:1;margin-bottom:6px}
# .grm-hero-sub{font-size:12px;color:#8B949E}
# /* Supporting metric cards */
# .metric-card{background:#161B22;border:1px solid #30363D;border-radius:8px;
#   padding:16px;text-align:center}
# .mc-label{font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px}
# .mc-value{font-size:22px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .mc-sub{font-size:10px;color:#8B949E;margin-top:2px}
# /* Price reference table */
# .price-row{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
# .price-chip{background:#161B22;border:1px solid #21262D;border-radius:6px;
#   padding:6px 12px;display:inline-flex;align-items:center;gap:8px}
# .price-chip-label{font-size:9px;color:#8B949E;text-transform:uppercase;
#   letter-spacing:1px}
# .price-chip-value{font-size:13px;font-weight:600;color:#E6EDF3;font-family:monospace}
# /* Basis input label */
# .basis-label{font-size:10px;color:#8B949E;margin-bottom:2px}
# .basis-note{font-size:10px;color:#484F58;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# .block-container{padding-top:0.3rem !important;padding-bottom:0 !important}
# [data-testid="stAppViewContainer"]>[data-testid="stVerticalBlock"]{padding-top:0 !important}
# h2,h3{margin-top:0 !important}
# [data-testid="stSidebar"]{background:#161B22}
# div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;border-radius:8px}
# p,.stMarkdown p,.stText{color:#E6EDF3 !important}
# .stDataFrame{color:#E6EDF3 !important}
# [data-testid="stMetricValue"]{color:#E6EDF3 !important}
# [data-testid="stMetricLabel"]{color:#8B949E !important}
# caption,.stCaption{color:#8B949E !important}
# label,.stSelectbox label,.stNumberInput label,.stToggle label{color:#8B949E !important}
# </style>
# """, unsafe_allow_html=True)


# # ── Helpers ────────────────────────────────────────────────────────────────────
# def spread_color(v):
#     if v is None: return "#8B949E"
#     return "#3FB950" if v >= 25 else ("#E8A020" if v >= 12 else "#F85149")

# def spread_label(v):
#     if v is None: return "—"
#     return "STRONG" if v >= 25 else ("MODERATE" if v >= 12 else "THIN")

# def spread_badge_class(v):
#     if v is None: return "badge-thin"
#     return "badge-strong" if v >= 25 else ("badge-moderate" if v >= 12 else "badge-thin")

# def fmt_bbl(v):  return f"${v:.2f}" if v is not None else "—"
# def fmt_gal(v):  return f"${v:.3f}" if v is not None else "—"

# def fmt_grm(spread, throughput):
#     if spread is None or not throughput: return None
#     return round(spread * throughput * 30 / 1_000_000, 2)

# def sign_str(v):
#     if v is None: return "—"
#     return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"

# def chips(items):
#     """Render a row of price chips as HTML."""
#     html = "<div class='price-row'>"
#     for label, val in items:
#         html += (f"<div class='price-chip'>"
#                  f"<span class='price-chip-label'>{label}</span>"
#                  f"<span class='price-chip-value'>{val}</span></div>")
#     html += "</div>"
#     return html


# # ── Password ───────────────────────────────────────────────────────────────────
# def check_password():
#     try:
#         correct = st.secrets.get("APP_PASSWORD")
#     except Exception:
#         return
#     if not correct: return
#     if not st.session_state.get("auth"):
#         st.title("🏭 Rogue Refinery Economics")
#         pwd = st.text_input("Password", type="password")
#         if st.button("Login"):
#             if pwd == correct:
#                 st.session_state["auth"] = True
#                 st.rerun()
#             else:
#                 st.error("Incorrect password")
#         st.stop()


# # ── Cached fetchers ────────────────────────────────────────────────────────────
# GSHEET_URL = (
#     "https://docs.google.com/spreadsheets/d/e/"
#     "2PACX-1vTfw6hAiE418gmKF2Ut0qRV2xCTex3fB4wY4IUwoR_5x5bRDpPxPbGwCaJunbjXDhHAeu-h_lQhUKiB"
#     "/pub?gid=0&single=true&output=csv"
# )

# @st.cache_data(ttl=3600)
# def get_specialty_sheet() -> dict:
#     import requests, csv, io
#     try:
#         r = requests.get(GSHEET_URL, timeout=10)
#         r.raise_for_status()
#         reader = csv.DictReader(io.StringIO(r.text))
#         result = {}
#         for row in reader:
#             loc = row.get("location","").strip()
#             if not loc: continue
#             result[loc] = {
#                 "jet_gal":     float(row.get("jet_gal",     SPECIALTY_DEFAULTS["jet_gal"])),
#                 "bunker_gal":  float(row.get("bunker_gal",  SPECIALTY_DEFAULTS["bunker_gal"])),
#                 "asphalt_gal": float(row.get("asphalt_gal", SPECIALTY_DEFAULTS["asphalt_gal"])),
#                 "lpg_gal":     float(row.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal",0.95))),
#                 "last_updated":row.get("last_updated","—"),
#             }
#         return result
#     except Exception as e:
#         print(f"  Google Sheet fetch failed: {e}")
#         return {}

# @st.cache_data(ttl=3600)
# def get_cme():  return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot(): return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():   return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec(): return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Build live margins ─────────────────────────────────────────────────────────
# def build_live_margins(lp, sheet_prices):
#     live_spot = get_spot()
#     eia_spec  = get_spec()
#     yields    = {k: v for k, v in YIELD_DEFAULTS.items()}
#     rows      = []
#     for loc in LOCATIONS:
#         n    = loc["display"]
#         spec = sheet_prices.get(n, {})
#         ulsd = live_spot.get("ulsd_gal", 3.5) or 3.5
#         wti  = live_spot.get("wti_bbl",  80)  or 80
#         location_specialty = {
#             "jet_gal":     spec.get("jet_gal",     eia_spec.get("jet_gal")     or ulsd*1.05),
#             "bunker_gal":  spec.get("bunker_gal",  eia_spec.get("bunker_gal")  or ulsd*0.70),
#             "asphalt_gal": spec.get("asphalt_gal", eia_spec.get("asphalt_gal") or ulsd*0.60),
#             "lpg_gal":     spec.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal",0.95)),
#         }
#         margin_list = compute_location_margins(
#             locations=[dict(loc)], spot_prices=live_spot,
#             location_prices=lp, specialty=location_specialty,
#             yields=yields, dist_margin_gal=0.35)
#         if margin_list:
#             r = margin_list[0]
#             r["throughput"]   = loc.get("throughput", 30000)
#             r["pnl"]          = fmt_grm(r.get("spread_321"), r["throughput"])
#             r["specialty"]    = location_specialty
#             r["spec_updated"] = spec.get("last_updated","—")
#             rows.append(r)
#     return rows, live_spot, yields


# # ── Forward state init ─────────────────────────────────────────────────────────
# def init_fwd_state(n, loc_cfg, sheet_prices, live_spot):
#     """
#     Initialise forward tab session state.
#     Basis fields auto-populate from location config (light_diff etc).
#     Specialty prices from Google Sheet.
#     CME absolute prices are NOT stored — they come from the strip at render time.
#     """
#     if st.session_state.get(f"_fwd_init_{n}"): return
#     spec = sheet_prices.get(n, {})
#     ulsd = live_spot.get("ulsd_gal", 3.5) or 3.5
#     wti  = live_spot.get("wti_bbl",  80)  or 80
#     st.session_state.update({
#         # Crude basis — decomposed: quality diff + transport tariff from config
#         f"fwd_light_qual_{n}":    float(loc_cfg.get("light_quality_diff",    loc_cfg.get("light_diff",0.0))),
#         f"fwd_light_tariff_{n}":  float(loc_cfg.get("light_transport_tariff",2.50)),
#         f"fwd_heavy_qual_{n}":    float(loc_cfg.get("heavy_quality_diff",    loc_cfg.get("heavy_diff",0.0))),
#         f"fwd_heavy_tariff_{n}":  float(loc_cfg.get("heavy_transport_tariff",2.50)),
#         f"fwd_light_pct_{n}":     80.0,   # % of slate = light crude (default 80%)
#         # Cost transparency opex items ($/bbl) — for net margin display
#         f"ct_opex_{n}":           4.00,
#         f"ct_prod_transport_{n}": 0.50,
#         f"ct_blendstock_{n}":     1.20,
#         f"ct_rin_{n}":            0.80,
#         f"ct_maintenance_{n}":    0.75,
#         # Product basis vs NYMEX
#         f"fwd_gas_basis_{n}":   float(loc_cfg.get("gas_diff",     0.0)),
#         f"fwd_die_basis_{n}":   float(loc_cfg.get("diesel_diff",  0.0)),
#         # Specialty — flat forward assumption from Google Sheet
#         f"fwd_jet_{n}":         spec.get("jet_gal",     ulsd*1.05),
#         f"fwd_jet_delta_{n}":   0.0,   # $/gal vs current
#         f"fwd_bunker_{n}":      spec.get("bunker_gal",  ulsd*0.70),
#         f"fwd_bunker_delta_{n}":0.0,
#         f"fwd_asphalt_{n}":     spec.get("asphalt_gal", ulsd*0.60),
#         f"fwd_asphalt_delta_{n}":0.0,
#         f"fwd_lpg_{n}":         spec.get("lpg_gal",     round(wti*0.50/42,3)),
#         f"fwd_lpg_delta_{n}":   0.0,
#         f"fwd_dist_{n}":        0.35,
#         f"fwd_tp_{n}":          loc_cfg.get("throughput", 30000),
#     })
#     for k, v in YIELD_DEFAULTS.items():
#         if f"fwd_y_{k}_{n}" not in st.session_state:
#             st.session_state[f"fwd_y_{k}_{n}"] = round(v * 100, 1)
#     st.session_state[f"_fwd_init_{n}"] = True


# # ── Ticker ─────────────────────────────────────────────────────────────────────
# def render_ticker(live_spot, live_margins):
#     wti  = live_spot.get("wti_bbl")
#     rbob = live_spot.get("rbob_gal")
#     ulsd = live_spot.get("ulsd_gal")
#     sp   = [r["spread_321"] for r in live_margins if r.get("spread_321")]
#     pavg = round(sum(sp)/len(sp),2) if sp else None
#     grm  = sum(r["pnl"] for r in live_margins if r.get("pnl"))
#     pc   = spread_color(pavg)
#     st.markdown(f"""
#     <div class="ticker-bar">
#       <div class="ticker-item"><span class="ticker-label">WTI Crude</span>
#         <span class="ticker-value">{fmt_bbl(wti)}</span>
#         <span class="ticker-label">per barrel</span></div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item"><span class="ticker-label">RBOB</span>
#         <span class="ticker-value">{fmt_gal(rbob)}</span>
#         <span class="ticker-label">per gallon</span></div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item"><span class="ticker-label">ULSD</span>
#         <span class="ticker-value">{fmt_gal(ulsd)}</span>
#         <span class="ticker-label">per gallon</span></div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item"><span class="ticker-label">RBOB $/bbl</span>
#         <span class="ticker-value">{fmt_bbl(round(rbob*42,2) if rbob else None)}</span>
#         <span class="ticker-label">×42</span></div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item"><span class="ticker-label">Portfolio Avg 3-2-1</span>
#         <span class="ticker-value" style="color:{pc}">{"$"+str(pavg)+"/bbl" if pavg else "—"}</span>
#         <span class="ticker-label" style="color:{pc}">{spread_label(pavg)}</span></div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item"><span class="ticker-label">Portfolio GRM/mo</span>
#         <span class="ticker-value" style="color:#3FB950">{"$"+str(round(grm,1))+"MM" if grm else "—"}</span>
#         <span class="ticker-label">before opex</span></div>
#     </div>""", unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # COST TRANSPARENCY PANEL
# # ══════════════════════════════════════════════════════════════════════════════
# def _render_cost_transparency(n, grm_bbl, tp, live_mode=True):
#     """
#     Investment committee cost transparency panel.
#     Shows what IS and IS NOT included in GRM, with editable opex deductions
#     and a live estimated net margin calculation.
#     """
#     with st.expander(
#         "💼 Cost Transparency — What's in GRM vs What's Not (Investment Committee View)",
#         expanded=False):

#         st.markdown(
#             "<div style='font-size:11px;color:#8B949E;margin-bottom:12px'>"
#             "GRM is a <b>gross</b> margin — it does not include operating costs. "
#             "The items below are common deductions to arrive at net margin. "
#             "Adjust to your actual cost structure.</div>",
#             unsafe_allow_html=True)

#         col_in, col_out = st.columns(2)

#         with col_in:
#             st.markdown(
#                 "<div style='background:#0D2A1A;border-radius:6px;padding:10px 14px;"
#                 "margin-bottom:8px'>"
#                 "<div style='font-size:10px;font-weight:600;color:#3FB950;"
#                 "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
#                 "✅ INCLUDED IN GRM</div>",
#                 unsafe_allow_html=True)
#             included_items = [
#                 ("Crude quality differential",   "Crude grade premium/discount vs WTI"),
#                 ("Crude pipeline/marine tariff",  "Field to refinery gate transport"),
#                 ("Federal & state fuel taxes",    "Stripped from AAA retail prices"),
#                 ("Distribution margin",           "Terminal to pump ($0.35/gal default)"),
#                 ("Refinery fuel & losses",        "~5.5% of barrel burned onsite"),
#             ]
#             for item, desc in included_items:
#                 st.markdown(
#                     f"<div style='margin-bottom:6px'>"
#                     f"<span style='font-size:11px;color:#E6EDF3'>{item}</span><br>"
#                     f"<span style='font-size:10px;color:#484F58'>{desc}</span>"
#                     f"</div>",
#                     unsafe_allow_html=True)
#             st.markdown("</div>", unsafe_allow_html=True)

#         with col_out:
#             st.markdown(
#                 "<div style='background:#2A0D0D;border-radius:6px;padding:10px 14px;"
#                 "margin-bottom:8px'>"
#                 "<div style='font-size:10px;font-weight:600;color:#F85149;"
#                 "text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>"
#                 "❌ NOT IN GRM — deduct for net margin</div>",
#                 unsafe_allow_html=True)

#             OPEX_ITEMS = [
#                 (f"ct_opex_{n}",            "Refinery opex ($/bbl)",            4.00,
#                  "Labor, utilities, catalysts, chemicals"),
#                 (f"ct_prod_transport_{n}",   "Product transport ($/bbl)",         0.50,
#                  "Pipeline/truck from refinery to terminal"),
#                 (f"ct_blendstock_{n}",       "Blendstock costs ($/bbl)",          1.20,
#                  "Ethanol, butane, MTBE, additives"),
#                 (f"ct_rin_{n}",              "RIN obligations ($/bbl)",           0.80,
#                  "Renewable fuel standard compliance"),
#                 (f"ct_maintenance_{n}",      "Maintenance & turnaround ($/bbl)",  0.75,
#                  "Annualized capex, scheduled downtime"),
#             ]
#             total_deductions = 0.0
#             for key, label, default, desc in OPEX_ITEMS:
#                 val = st.number_input(
#                     label, min_value=0.0, max_value=20.0,
#                     value=float(st.session_state.get(key, default)),
#                     step=0.25, format="%.2f", key=f"ctp_{key}")
#                 st.session_state[key] = val
#                 total_deductions += val
#                 st.caption(desc)
#             st.markdown("</div>", unsafe_allow_html=True)

#         net_margin = round((grm_bbl or 0) - total_deductions, 2) if grm_bbl else None
#         net_grm_mm = round(net_margin * tp * 30 / 1e6, 2) if (net_margin and tp) else None
#         net_clr    = ("#3FB950" if net_margin and net_margin >= 10
#                       else ("#E8A020" if net_margin and net_margin >= 0
#                       else "#F85149"))

#         net_mm_html = (
#             f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#             f"letter-spacing:1px'>Net GRM / Month</div>"
#             f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
#             f"color:{net_clr}'>${net_grm_mm:.1f}MM</div></div>"
#         ) if net_grm_mm else ""

#         st.markdown(
#             f"<div style='background:#161B22;border:1px solid #30363D;"
#             f"border-radius:8px;padding:14px 18px;margin-top:8px'>"
#             f"<div style='display:flex;gap:24px;align-items:center;flex-wrap:wrap'>"
#             f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#             f"letter-spacing:1px'>Gross Refining Margin</div>"
#             f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
#             f"color:#E8A020'>${(grm_bbl or 0):.2f}/bbl</div></div>"
#             f"<div style='font-size:22px;color:#484F58'>−</div>"
#             f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#             f"letter-spacing:1px'>Est. Total Deductions</div>"
#             f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
#             f"color:#F85149'>${total_deductions:.2f}/bbl</div></div>"
#             f"<div style='font-size:22px;color:#484F58'>=</div>"
#             f"<div><div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#             f"letter-spacing:1px'>Est. Net Margin</div>"
#             f"<div style='font-size:22px;font-weight:700;font-family:monospace;"
#             f"color:{net_clr}'>{'$'+str(net_margin)+'/bbl' if net_margin is not None else '—'}</div></div>"
#             f"{net_mm_html}"
#             f"</div>"
#             f"<div style='font-size:10px;color:#484F58;margin-top:8px'>"
#             f"⚠️ Estimated net margin uses industry benchmark defaults. "
#             f"Adjust deduction items to your actual cost structure. "
#             f"Not a substitute for detailed project-level financial modeling.</div>"
#             f"</div>",
#             unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # PORTFOLIO PAGE
# # ══════════════════════════════════════════════════════════════════════════════
# LOC_COORDS = {
#     "Alaska — Port Mackenzie":  (61.35,-150.02),
#     "Greenport — Austin, TX":   (30.27, -97.74),
#     "Victoria, TX":             (28.81, -97.00),
#     "Duncan, OK":               (34.50, -97.96),
#     "Dewey, OK":                (36.80, -95.93),
#     "North Dakota — Stampede":  (48.40,-101.30),
#     "Big Spring, TX":           (32.25,-101.48),
#     "Utah":                     (40.76,-111.89),
#     "SE New Mexico":            (33.39,-104.52),
#     "Louisiana":                (30.22, -92.02),
#     "Puerto Rico":              (18.22, -66.59),
# }

# def show_portfolio(live_margins):
#     valid = [r for r in live_margins if r.get("spread_321")]
#     if valid:
#         best  = max(valid, key=lambda x: x["spread_321"])
#         worst = min(valid, key=lambda x: x["spread_321"])
#         total = sum(r["pnl"] for r in valid if r.get("pnl"))
#         sc1,sc2,sc3 = st.columns(3)
#         sc1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Best Margin Today</div>
#             <div class='mc-value' style='color:#3FB950'>${best["spread_321"]:.2f}/bbl</div>
#             <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Thinnest Margin Today</div>
#             <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
#               ${worst["spread_321"]:.2f}/bbl</div>
#             <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Total Portfolio GRM / Month</div>
#             <div class='mc-value' style='color:#3FB950'>
#               {"$"+str(round(total,1))+"MM" if total else "—"}</div>
#             <div class='mc-sub'>before opex · full yield basis</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map — 3-2-1 Crack Spread</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in live_margins:
#         c = LOC_COORDS.get(r["display"],(39.5,-98.35))
#         s = r.get("spread_321")
#         spec = r.get("specialty",{})
#         map_rows.append({
#             "name":  r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat":c[0],"lon":c[1],"spread":s,"color":spread_color(s),
#             "hover":(
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield GRM: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"GRM/mo: {'$'+str(r['pnl'])+'MM' if r.get('pnl') else '—'}<br>"
#                 f"Jet: ${spec.get('jet_gal','—')}/gal · Bunker: ${spec.get('bunker_gal','—')}/gal"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"],lon=df_m["lon"],mode="markers+text",
#         marker=dict(size=20,color=df_m["color"].tolist(),
#                     line=dict(width=2,color="#0D1117"),opacity=0.90),
#         text=df_m["short"],textposition="top center",
#         textfont=dict(size=10,color="#E6EDF3"),
#         hovertext=df_m["hover"],hoverinfo="text"))
#     for _,row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9],lon=[row["lon"]],mode="text",
#                 text=[f"${row['spread']:.0f}"],
#                 textfont=dict(size=10,color=row["color"],family="monospace"),
#                 hoverinfo="skip",showlegend=False))
#     fig_m.update_layout(
#         geo=dict(scope="world",showland=True,landcolor="#1C2128",
#                  showocean=True,oceancolor="#0D1117",
#                  showlakes=True,lakecolor="#0D1117",
#                  showcountries=True,countrycolor="#30363D",
#                  showcoastlines=True,coastlinecolor="#30363D",
#                  showframe=False,bgcolor="#0D1117",
#                  center=dict(lat=45,lon=-100),projection_scale=1.4,
#                  lonaxis_range=[-175,-50],lataxis_range=[10,78]),
#         paper_bgcolor="#0D1117",margin=dict(l=0,r=0,t=0,b=0),
#         height=400,showlegend=False)
#     for lbl,clr,ya in [("● STRONG ≥$25","#3FB950",0.13),
#                         ("● MODERATE $12–25","#E8A020",0.09),
#                         ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     IN_CONSTRUCTION  = {"Victoria, TX","Duncan, OK"}
#     DEVELOPMENT_ORDER = [
#         ("Alaska — Port Mackenzie","Port Mackenzie","AK"),
#         ("Greenport — Austin, TX", "Austin",       "TX"),
#         ("Big Spring, TX",         "Big Spring",   "TX"),
#         ("Dewey, OK",              "Dewey",        "OK"),
#         ("North Dakota — Stampede","Stampede",     "ND"),
#         ("Utah",                   "Utah",         "UT"),
#         ("SE New Mexico",          "SE New Mexico","NM"),
#         ("Louisiana",              "Louisiana",    "LA"),
#         ("Puerto Rico",            "Puerto Rico",  "PR"),
#     ]
#     margin_map = {r["display"]: r for r in live_margins}

#     def _card(r, key):
#         s     = r.get("spread_321")
#         clr   = spread_color(s)
#         badge = spread_badge_class(s)
#         pnl_s = f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—"
#         short = r["display"].split("—")[-1].split(",")[0].strip()
#         st.markdown(f"""<div class='loc-card'>
#             <div class='loc-card-name'>{short}</div>
#             <div class='loc-card-spread' style='color:{clr}'>
#                 {"$"+str(s)+"/bbl" if s else "—"}</div>
#             <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
#             <div class='loc-card-pnl'>{pnl_s}</div>
#         </div>""", unsafe_allow_html=True)
#         if st.button("Open →", key=key, use_container_width=True):
#             st.session_state["view"]    = "detail"
#             st.session_state["sel_loc"] = r["display"]
#             st.rerun()

#     st.markdown("<div class='sec-hdr'>In Construction</div>", unsafe_allow_html=True)
#     constr = [r for r in live_margins if r["display"] in IN_CONSTRUCTION]
#     cc = st.columns(4)
#     for i,r in enumerate(constr):
#         with cc[i%4]: _card(r, f"btn_con_{i}")

#     st.markdown("<br>", unsafe_allow_html=True)
#     st.markdown("<div class='sec-hdr'>Development Locations</div>", unsafe_allow_html=True)
#     dev = [(dn,sl,st_) for dn,sl,st_ in DEVELOPMENT_ORDER if dn in margin_map]
#     dc  = st.columns(4)
#     for i,(dn,sl,_) in enumerate(dev):
#         with dc[i%4]: _card(margin_map[dn], f"btn_dev_{i}")

#     # Portfolio download
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
#                 unsafe_allow_html=True)
#     dl_rows = []
#     for r in live_margins:
#         tp  = r.get("throughput",30000)
#         gm  = fmt_grm(r.get("spread_321"),tp)
#         spec= r.get("specialty",{})
#         dl_rows.append({
#             "Location":              r["display"],
#             "Source":                r.get("source","—"),
#             "Throughput (bbl/day)":  tp,
#             "Light Crude ($/bbl)":   r.get("crude_light"),
#             "Heavy Crude ($/bbl)":   r.get("crude_heavy"),
#             "Gasoline - Retail":     r.get("retail_gas"),
#             "Gasoline - Pre-tax":    r.get("pretax_gas"),
#             "Gasoline - Wholesale":  r.get("wholesale_gas"),
#             "Diesel - Retail":       r.get("retail_diesel"),
#             "Diesel - Wholesale":    r.get("wholesale_diesel"),
#             "Jet Fuel ($/gal)":      spec.get("jet_gal"),
#             "Bunker ($/gal)":        spec.get("bunker_gal"),
#             "Asphalt ($/gal)":       spec.get("asphalt_gal"),
#             "LPG/Other ($/gal)":     spec.get("lpg_gal"),
#             "3-2-1 ($/bbl)":         r.get("spread_321"),
#             "2-1-1 ($/bbl)":         r.get("spread_211"),
#             "5-3-2 ($/bbl)":         r.get("spread_532"),
#             "Full Yield GRM ($/bbl)":r.get("spread_full"),
#             "Monthly GRM ($MM)":     gm,
#             "Annual GRM ($MM)":      round(gm*12,2) if gm else None,
#             "Specialty Updated":     r.get("spec_updated","—"),
#             "As Of":                 datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })
#     df_dl = pd.DataFrame(dl_rows)
#     dc1,dc2 = st.columns([1,2])
#     with dc1:
#         st.download_button("⬇️ Download All Locations CSV",
#             data=df_dl.to_csv(index=False),
#             file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
#             mime="text/csv",use_container_width=True)
#     with dc2:
#         st.dataframe(df_dl[[
#             "Location","Light Crude ($/bbl)",
#             "Gasoline - Retail","Gasoline - Wholesale",
#             "Diesel - Retail","Diesel - Wholesale",
#             "Jet Fuel ($/gal)","Bunker ($/gal)",
#             "3-2-1 ($/bbl)","Full Yield GRM ($/bbl)","Monthly GRM ($MM)",
#         ]],use_container_width=True,hide_index=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # LOCATION DETAIL — two tabs
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(live_margins, strip, sheet_prices, live_spot):
#     _scroll_top()
#     sel = st.session_state.get("sel_loc","")
#     r   = next((m for m in live_margins if m["display"]==sel), None)
#     loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})

#     bc,tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321 = r.get("spread_321") if r else None
#         clr  = spread_color(s321)
#         short= sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
#             f"<span style='color:{clr};font-family:monospace'>"
#             f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
#             f"</h3>",unsafe_allow_html=True)
#     if not r:
#         st.warning("No data for this location.")
#         return

#     n         = sel
#     tp        = r.get("throughput",30000)
#     spec      = r.get("specialty",{})
#     spec_date = r.get("spec_updated","—")
#     init_fwd_state(n, loc_cfg, sheet_prices, live_spot)
#     st.markdown("---")
#     tab_today, tab_fwd = st.tabs(["📊 Today", "📈 Forward View"])

#     # ══════════════════════════════════════════════════════════════════════════
#     # TAB 1 — TODAY  (Financial + Operations views)
#     # ══════════════════════════════════════════════════════════════════════════
#     with tab_today:
#         sfull  = r.get("spread_full")
#         ws_g   = r.get("wholesale_gas",   0) or 0
#         ws_d   = r.get("wholesale_diesel", 0) or 0
#         ret_g  = r.get("retail_gas",  0) or 0
#         ret_d  = r.get("retail_diesel",0) or 0
#         cr_    = r.get("crude_light",  0) or 0
#         jet_p  = spec.get("jet_gal",    SPECIALTY_DEFAULTS["jet_gal"])
#         bnk_p  = spec.get("bunker_gal", SPECIALTY_DEFAULTS["bunker_gal"])
#         asp_p  = spec.get("asphalt_gal",SPECIALTY_DEFAULTS["asphalt_gal"])
#         lpg_p  = spec.get("lpg_gal",    SPECIALTY_DEFAULTS.get("lpg_gal",0.95))

#         yields = {k: v for k, v in YIELD_DEFAULTS.items()}
#         y_g  = yields.get("gasoline",  0.445)
#         y_d  = yields.get("ulsd",      0.290)
#         y_j  = yields.get("jet",       0.110)
#         y_b  = yields.get("bunker",    0.035)
#         y_a  = yields.get("asphalt",   0.025)
#         y_l  = yields.get("lpg_other", 0.040)
#         y_ru = yields.get("refinery_use",0.055)
#         _sal = y_g+y_d+y_j+y_b+y_a+y_l

#         gc_ = round(ws_g  *y_g*42,2)
#         dc_ = round(ws_d  *y_d*42,2)
#         jc_ = round(jet_p *y_j*42,2)
#         bc_ = round(bnk_p *y_b*42,2)
#         ac_ = round(asp_p *y_a*42,2)
#         lc_ = round(lpg_p *y_l*42,2)
#         total_rev = gc_+dc_+jc_+bc_+ac_+lc_
#         grm_full  = round(total_rev - cr_, 2)

#         # ── Throughput input (top of Today tab — drives all volume calcs) ─────
#         tp_col, _ = st.columns([1,3])
#         with tp_col:
#             tp_today = st.number_input(
#                 "Throughput (bbl/day)",
#                 min_value=0, max_value=500000,
#                 value=int(st.session_state.get(f"today_tp_{n}",
#                           r.get("throughput", 30000))),
#                 step=1000, key=f"today_tp_input_{n}")
#             st.session_state[f"today_tp_{n}"] = int(tp_today)

#         tp   = tp_today
#         pnl_v = fmt_grm(s321, tp)

#         # ── Volume calculations ───────────────────────────────────────────────
#         # bbl/day
#         crude_bbl_day  = tp
#         gas_bbl_day    = round(tp * y_g, 0)
#         die_bbl_day    = round(tp * y_d, 0)
#         jet_bbl_day    = round(tp * y_j, 0)
#         bnk_bbl_day    = round(tp * y_b, 0)
#         asp_bbl_day    = round(tp * y_a, 0)
#         lpg_bbl_day    = round(tp * y_l, 0)
#         ref_bbl_day    = round(tp * y_ru,0)
#         # gal/day (×42)
#         gas_gal_day    = gas_bbl_day * 42
#         die_gal_day    = die_bbl_day * 42
#         jet_gal_day    = jet_bbl_day * 42
#         bnk_gal_day    = bnk_bbl_day * 42
#         lpg_gal_day    = lpg_bbl_day * 42
#         # Asphalt: convert to short tons (approx 6.3 bbl/short ton for liquid asphalt)
#         asp_ton_day    = round(asp_bbl_day / 6.3, 1)
#         # Monthly (×30)
#         crude_bbl_mo   = crude_bbl_day * 30
#         gas_bbl_mo     = gas_bbl_day   * 30
#         die_bbl_mo     = die_bbl_day   * 30

#         # ── PANEL 1: Hero GRM + supporting metrics ────────────────────────────
#         hero_col, supp_col = st.columns([2, 3], gap="large")

#         with hero_col:
#             grm_clr = spread_color(grm_full)
#             st.markdown(f"""
#             <div class='grm-hero'>
#               <div class='grm-hero-label'>Refinery Crack Spread — Full Yield</div>
#               <div class='grm-hero-value' style='color:{grm_clr}'>
#                 ${grm_full:.2f}
#               </div>
#               <div style='font-size:14px;font-weight:600;color:{grm_clr};
#                           letter-spacing:2px;margin-bottom:12px'>
#                 per barrel · {spread_label(grm_full)}
#               </div>
#               <div style='background:#21262D;border-radius:8px;padding:10px;
#                           display:inline-block;width:100%;box-sizing:border-box'>
#                 <div style='font-size:9px;color:#8B949E;text-transform:uppercase;
#                             letter-spacing:1px'>Monthly GRM</div>
#                 <div style='font-size:28px;font-weight:700;font-family:monospace;
#                             color:#3FB950'>
#                   {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
#                 </div>
#                 <div style='font-size:10px;color:#8B949E'>{f"{tp:,} bbl/day · before opex"}</div>
#               </div>
#             </div>
#             """, unsafe_allow_html=True)

#         with supp_col:
#             sa1,sa2 = st.columns(2)
#             sa1.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>3-2-1 Reference Spread</div>
#                 <div class='mc-value' style='color:{spread_color(s321)}'>
#                     {"$"+str(s321)+"/bbl" if s321 else "—"}</div>
#                 <div class='mc-sub'>2 gas + 1 diesel benchmark</div>
#             </div>""", unsafe_allow_html=True)
#             sa2.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>Annual GRM Run-Rate</div>
#                 <div class='mc-value' style='color:#3FB950'>
#                     {"$"+str(round(pnl_v*12,1))+"MM" if pnl_v else "—"}</div>
#                 <div class='mc-sub'>{f"at {tp:,} bbl/day"}</div>
#             </div>""", unsafe_allow_html=True)

#             st.markdown("<br>", unsafe_allow_html=True)
#             sb1,sb2,sb3 = st.columns(3)
#             sb1.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>2-1-1 Spread</div>
#                 <div class='mc-value' style='color:{spread_color(r.get("spread_211"))};font-size:18px'>
#                     {"$"+str(r.get("spread_211"))+"/bbl" if r.get("spread_211") else "—"}</div>
#                 <div class='mc-sub'>1 gas + 1 diesel</div>
#             </div>""", unsafe_allow_html=True)
#             sb2.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>5-3-2 Spread</div>
#                 <div class='mc-value' style='color:{spread_color(r.get("spread_532"))};font-size:18px'>
#                     {"$"+str(r.get("spread_532"))+"/bbl" if r.get("spread_532") else "—"}</div>
#                 <div class='mc-sub'>3 gas + 2 diesel</div>
#             </div>""", unsafe_allow_html=True)
#             sb3.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>Crude Cost</div>
#                 <div class='mc-value' style='color:#F85149;font-size:18px'>
#                     ${cr_:.2f}/bbl</div>
#                 <div class='mc-sub'>WTI + location diff</div>
#             </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── PANEL 2: Waterfall ────────────────────────────────────────────────
#         st.markdown("<div class='sec-hdr'>Where Does the Margin Come From? — $/bbl</div>",
#                     unsafe_allow_html=True)
#         fig_wf = go.Figure(go.Waterfall(
#             orientation="v",
#             measure=["absolute","relative","relative","relative",
#                      "relative","relative","relative","total"],
#             x=["− Crude","+ Gasoline","+ Diesel","+ Jet",
#                "+ Bunker","+ Asphalt","+ LPG","= GRM"],
#             y=[-cr_, gc_, dc_, jc_, bc_, ac_, lc_, 0],
#             text=[f"-${cr_:.2f}",f"+${gc_:.2f}",f"+${dc_:.2f}",
#                   f"+${jc_:.2f}",f"+${bc_:.2f}",f"+${ac_:.2f}",
#                   f"+${lc_:.2f}",f"${grm_full:.2f}"],
#             textposition="outside",
#             textfont=dict(size=11,color="#E6EDF3"),
#             connector=dict(line=dict(color="#30363D",width=1)),
#             decreasing=dict(marker_color="#F85149"),
#             increasing=dict(marker_color="#3FB950"),
#             totals=dict(marker_color="#E8A020"),
#         ))
#         fig_wf.update_layout(
#             paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#             font_color="#E6EDF3",
#             yaxis=dict(title="$/bbl",gridcolor="#21262D",tickfont=dict(size=11)),
#             xaxis=dict(gridcolor="#21262D",tickangle=0,tickfont=dict(size=11)),
#             margin=dict(l=0,r=0,t=8,b=0),height=340,showlegend=False)
#         st.plotly_chart(fig_wf, use_container_width=True)

#         # ── PANEL 3: Product contribution cards (always visible) ──────────────
#         st.markdown("<div class='sec-hdr'>Product Contribution to GRM</div>",
#                     unsafe_allow_html=True)
#         PRODUCTS = [
#             ("Gasoline", gc_,y_g,"#4A90D9",ws_g),
#             ("Diesel",   dc_,y_d,"#E8A020",ws_d),
#             ("Jet Fuel", jc_,y_j,"#5A9E3A",jet_p),
#             ("Bunker",   bc_,y_b,"#8B4FBF",bnk_p),
#             ("Asphalt",  ac_,y_a,"#CC7722",asp_p),
#             ("LPG/Other",lc_,y_l,"#3AA6B9",lpg_p),
#         ]
#         pcols = st.columns(6)
#         for col,(name,rev,yld,clr,price_gal) in zip(pcols,PRODUCTS):
#             crude_alloc = round(cr_*(yld/_sal) if _sal>0 else 0,2)
#             net         = round(rev-crude_alloc,2)
#             pct         = round(net/grm_full*100,1) if grm_full else 0
#             nc_clr      = clr if net>=0 else "#F85149"
#             col.markdown(f"""<div class='metric-card' style='padding:12px'>
#                 <div class='mc-label' style='color:{clr}'>{name}</div>
#                 <div style='font-size:18px;font-weight:700;font-family:monospace;
#                      color:{nc_clr}'>${net:.2f}/bbl</div>
#                 <div style='font-size:10px;color:#8B949E;margin-top:3px'>
#                     {pct:+.1f}% of GRM</div>
#                 <div style='height:1px;background:#30363D;margin:6px 0'></div>
#                 <div style='font-size:10px;color:#8B949E'>${price_gal:.3f}/gal</div>
#                 <div style='font-size:10px;color:#8B949E'>${price_gal*42:.2f}/bbl</div>
#                 <div style='font-size:9px;color:#484F58;margin-top:3px'>
#                     {round(yld*100,1)}% of barrel</div>
#             </div>""", unsafe_allow_html=True)
#         st.caption(
#             f"Net contribution = product revenue − allocated crude cost · "
#             f"{round(_sal*100,1)}% saleable · {round(y_ru*100,1)}% refinery fuel use · "
#             f"total product revenue ${total_rev:.2f}/bbl vs crude ${cr_:.2f}/bbl")

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── PANEL 4: Today's Prices (card style, $/gal and $/bbl) ────────────
#         st.markdown("<div class='sec-hdr'>Today's Prices — Input & Output</div>",
#                     unsafe_allow_html=True)
#         price_data = [
#             # (label, $/gal, $/bbl, type, color)
#             ("WTI Crude",    cr_/42,       cr_,          "INPUT",  "#F85149"),
#             ("Retail Gas",   ret_g,         ret_g*42,     "RETAIL", "#8B949E"),
#             ("Whsl Gas",     ws_g,          ws_g*42,      "OUTPUT", "#4A90D9"),
#             ("Retail Diesel",ret_d,         ret_d*42,     "RETAIL", "#8B949E"),
#             ("Whsl Diesel",  ws_d,          ws_d*42,      "OUTPUT", "#E8A020"),
#             ("Jet Fuel",     jet_p,         jet_p*42,     "OUTPUT", "#5A9E3A"),
#             ("Bunker Fuel",  bnk_p,         bnk_p*42,     "OUTPUT", "#8B4FBF"),
#             ("Asphalt",      asp_p,         asp_p*42,     "OUTPUT", "#CC7722"),
#             ("LPG/Other",    lpg_p,         lpg_p*42,     "OUTPUT", "#3AA6B9"),
#         ]
#         pcols2 = st.columns(len(price_data))
#         for col,(lbl,gal,bbl,typ,clr) in zip(pcols2, price_data):
#             badge_bg = "#2A0D0D" if typ=="INPUT" else ("#1A1A2A" if typ=="RETAIL" else "#0D1A0D")
#             badge_clr= "#F85149" if typ=="INPUT" else ("#8B949E" if typ=="RETAIL" else "#3FB950")
#             col.markdown(f"""<div class='metric-card' style='padding:10px'>
#                 <div style='font-size:8px;font-weight:600;letter-spacing:1px;
#                      background:{badge_bg};color:{badge_clr};
#                      border-radius:3px;padding:1px 5px;display:inline-block;
#                      margin-bottom:4px'>{typ}</div>
#                 <div style='font-size:10px;color:#8B949E;margin-bottom:3px'>{lbl}</div>
#                 <div style='font-size:14px;font-weight:700;font-family:monospace;
#                      color:{clr}'>${gal:.3f}<span style='font-size:9px;color:#484F58'>/gal</span></div>
#                 <div style='font-size:12px;font-weight:600;font-family:monospace;
#                      color:{clr}'>${bbl:.2f}<span style='font-size:9px;color:#484F58'>/bbl</span></div>
#             </div>""", unsafe_allow_html=True)
#         st.caption(
#             f"Gas & diesel: AAA daily survey · Crude: CME settle · "
#             f"Jet/Bunker/Asphalt/LPG: Google Sheet (updated {spec_date}) · "
#             f"INPUT = cost · OUTPUT = revenue · RETAIL = reference only")

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── PANEL 5: Operations / Volume View ─────────────────────────────────
#         st.markdown("<div class='sec-hdr'>Operations View — Barrels & Volume</div>",
#                     unsafe_allow_html=True)
#         st.markdown(f"<div style='font-size:11px;color:#8B949E;margin-bottom:8px'>"
#                     f"At <b style='color:#E6EDF3'>{tp:,} bbl/day</b> throughput · "
#                     f"30-day month · Asphalt in short tons (÷6.3 bbl/ton)</div>",
#                     unsafe_allow_html=True)

#         # Volume bar chart — inputs vs outputs
#         INPUTS_VOL  = [("Light Crude Input", crude_bbl_day, "#F85149")]
#         OUTPUTS_VOL = [
#             ("Gasoline",  gas_bbl_day, "#4A90D9"),
#             ("Diesel",    die_bbl_day, "#E8A020"),
#             ("Jet Fuel",  jet_bbl_day, "#5A9E3A"),
#             ("Bunker",    bnk_bbl_day, "#8B4FBF"),
#             ("Asphalt",   asp_bbl_day, "#CC7722"),
#             ("LPG/Other", lpg_bbl_day, "#3AA6B9"),
#             ("Ref. Use/Loss",ref_bbl_day,"#484F58"),
#         ]
#         fig_vol = go.Figure()
#         for (lbl,val,clr) in INPUTS_VOL:
#             fig_vol.add_trace(go.Bar(
#                 name=lbl, x=["Daily (bbl)","Monthly (bbl)"],
#                 y=[val, val*30], marker_color=clr,
#                 text=[f"{val:,.0f}",f"{val*30:,.0f}"],
#                 textposition="outside",textfont=dict(size=9,color="#E6EDF3")))
#         for (lbl,val,clr) in OUTPUTS_VOL:
#             fig_vol.add_trace(go.Bar(
#                 name=lbl, x=["Daily (bbl)","Monthly (bbl)"],
#                 y=[val, val*30], marker_color=clr,
#                 text=[f"{val:,.0f}",f"{val*30:,.0f}"],
#                 textposition="inside",textfont=dict(size=9,color="#E6EDF3")))
#         fig_vol.update_layout(
#             barmode="group",
#             paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#             font_color="#E6EDF3",
#             xaxis=dict(gridcolor="#21262D"),
#             yaxis=dict(title="Barrels",gridcolor="#21262D"),
#             legend=dict(bgcolor="#161B22",font=dict(size=9),
#                         orientation="h",yanchor="bottom",y=1.02),
#             margin=dict(l=0,r=0,t=30,b=0),height=300)
#         st.plotly_chart(fig_vol, use_container_width=True)

#         # Operations table — one row per stream
#         ops_rows = [
#             # stream, type, bbl/day, gal/day, bbl/mo, $/gal, $/bbl, rev_cost/mo_mm
#             ("Light Crude",  "INPUT",  crude_bbl_day, crude_bbl_day*42,
#              crude_bbl_mo,   cr_/42,   cr_,
#              -round(cr_*crude_bbl_mo/1e6,2)),
#             ("Gasoline",     "OUTPUT", gas_bbl_day,   gas_gal_day,
#              gas_bbl_mo,     ws_g,     ws_g*42,
#              round(ws_g*42*gas_bbl_mo/1e6,2)),
#             ("Diesel/ULSD",  "OUTPUT", die_bbl_day,   die_gal_day,
#              die_bbl_mo,     ws_d,     ws_d*42,
#              round(ws_d*42*die_bbl_mo/1e6,2)),
#             ("Jet Fuel",     "OUTPUT", jet_bbl_day,   jet_gal_day,
#              jet_bbl_day*30, jet_p,    jet_p*42,
#              round(jet_p*42*jet_bbl_day*30/1e6,2)),
#             ("Bunker Fuel",  "OUTPUT", bnk_bbl_day,   bnk_gal_day,
#              bnk_bbl_day*30, bnk_p,    bnk_p*42,
#              round(bnk_p*42*bnk_bbl_day*30/1e6,2)),
#             ("Asphalt",      "OUTPUT (tons)", asp_bbl_day, f"{asp_ton_day:.0f} t/day",
#              asp_bbl_day*30, asp_p,    asp_p*42,
#              round(asp_p*42*asp_bbl_day*30/1e6,2)),
#             ("LPG/Other",    "OUTPUT", lpg_bbl_day,   lpg_gal_day,
#              lpg_bbl_day*30, lpg_p,    lpg_p*42,
#              round(lpg_p*42*lpg_bbl_day*30/1e6,2)),
#             ("Refinery Use", "LOSS",   ref_bbl_day,   "—",
#              ref_bbl_day*30, "—",      "—",   0),
#         ]
#         ops_df = pd.DataFrame(ops_rows, columns=[
#             "Stream","Type","bbl/day","gal/day","bbl/month",
#             "$/gal","$/bbl","Revenue/Cost ($MM/mo)"])
#         # Format numeric columns
#         for c in ["bbl/day","bbl/month"]:
#             ops_df[c] = ops_df[c].apply(
#                 lambda x: f"{int(x):,}" if isinstance(x,(int,float)) else x)
#         for c in ["gal/day"]:
#             ops_df[c] = ops_df[c].apply(
#                 lambda x: f"{int(x):,}" if isinstance(x,(int,float)) else x)
#         for c in ["$/gal","$/bbl"]:
#             ops_df[c] = ops_df[c].apply(
#                 lambda x: f"${x:.3f}" if isinstance(x,float) else x)
#         ops_df["Revenue/Cost ($MM/mo)"] = ops_df["Revenue/Cost ($MM/mo)"].apply(
#             lambda x: f"+${x:.2f}MM" if isinstance(x,float) and x>0
#                       else (f"-${abs(x):.2f}MM" if isinstance(x,float) and x<0 else "—"))
#         st.dataframe(ops_df, use_container_width=True, hide_index=True)

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── PANEL 6: Stress test ──────────────────────────────────────────────
#         st.markdown("<div class='sec-hdr'>What If… — 3-2-1 Crack Spread Stress Test</div>",
#                     unsafe_allow_html=True)
#         crude_b = r.get("crude_light", cr_)
#         gas_b   = r.get("wholesale_gas",  ws_g)
#         die_b   = r.get("wholesale_diesel",ws_d)
#         base    = s321 or 0

#         st_left, st_right = st.columns([1,1], gap="large")
#         with st_left:
#             scenarios = [
#                 ("Crude +25%",    crude_b*1.25, gas_b,      die_b),
#                 ("Products +25%", crude_b,      gas_b*1.25, die_b*1.25),
#                 ("Crude −25%",    crude_b*0.75, gas_b,      die_b),
#                 ("Products −25%", crude_b,      gas_b*0.75, die_b*0.75),
#             ]
#             r1c1,r1c2 = st.columns(2)
#             r2c1,r2c2 = st.columns(2)
#             for col,(lbl,c,g,d) in zip([r1c1,r1c2,r2c1,r2c2],scenarios):
#                 val   = round(_c321(c,g,d),2)
#                 delta = round(val-base,2)
#                 grm_mo= round(val*tp*30/1e6,2)
#                 is_up = delta >= 0
#                 bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                 clr2  = "#3FB950" if is_up else "#F85149"
#                 sign  = "▲" if is_up else "▼"
#                 col.markdown(f"""
#                 <div style='background:{bg};border-radius:8px;padding:16px;
#                      text-align:center;margin-bottom:6px'>
#                   <div style='font-size:9px;color:{clr2};letter-spacing:1px;
#                        text-transform:uppercase;font-weight:600'>{lbl}</div>
#                   <div style='font-size:10px;color:#8B949E;margin:4px 0'>
#                       Base 3-2-1: ${base:.2f}</div>
#                   <div style='font-size:26px;font-weight:700;
#                        font-family:monospace;color:{clr2}'>${val:.2f}</div>
#                   <div style='font-size:11px;font-weight:600;color:{clr2}'>
#                       {sign} {sign_str(delta)}/bbl</div>
#                   <div style='font-size:10px;color:{clr2};margin-top:3px'>
#                       GRM/mo: ${grm_mo:.1f}MM</div>
#                 </div>""", unsafe_allow_html=True)

#         with st_right:
#             AREA_BAR = {
#                 "Gasoline":("#4A90D9",gc_),"Diesel":("#E8A020",dc_),
#                 "Jet":("#5A9E3A",jc_),"Bunker":("#8B4FBF",bc_),
#                 "Asphalt":("#CC7722",ac_),"LPG":("#3AA6B9",lc_),
#             }
#             fig_bar = go.Figure()
#             for prod,(clr2,val) in AREA_BAR.items():
#                 fig_bar.add_trace(go.Bar(
#                     name=prod,x=["Revenue"],y=[val],
#                     marker_color=clr2,
#                     text=[f"${val:.1f}"],textposition="inside",
#                     textfont=dict(size=9,color="#E6EDF3")))
#             fig_bar.add_hline(y=cr_,line_color="#F85149",
#                 line_width=2,line_dash="solid",
#                 annotation_text=f"Crude ${cr_:.2f}/bbl",
#                 annotation_font_color="#F85149",annotation_font_size=10)
#             fig_bar.update_layout(
#                 barmode="stack",
#                 title=dict(text="Revenue by Product vs Crude Cost ($/bbl)",
#                            font=dict(color="#E6EDF3",size=12)),
#                 paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                 xaxis=dict(gridcolor="#21262D"),
#                 legend=dict(bgcolor="#161B22",font=dict(size=9),
#                             orientation="h",yanchor="bottom",y=1.05),
#                 margin=dict(l=0,r=0,t=36,b=0),height=320)
#             st.plotly_chart(fig_bar, use_container_width=True)

#         # ── Cost Transparency Panel ───────────────────────────────────────────
#         _render_cost_transparency(n, r.get("spread_full"), tp, live_mode=True)

#         # ── CSV download ───────────────────────────────────────────────────────
#         st.markdown("---")
#         dl_row = {
#             "Location":           sel,
#             "Throughput (bbl/d)": tp,
#             "Retail Gas ($/gal)": r.get("retail_gas"),
#             "Federal Tax":        r.get("federal_tax_gas"),
#             "State Tax":          r.get("state_tax_gas"),
#             "Pre-tax Gas":        r.get("pretax_gas"),
#             "Distribution":       r.get("dist_margin"),
#             "Wholesale Gas":      r.get("wholesale_gas"),
#             "Wholesale Diesel":   r.get("wholesale_diesel"),
#             "Light Crude ($/bbl)":r.get("crude_light"),
#             "Heavy Crude":        r.get("crude_heavy"),
#             "Jet ($/gal)":        jet_p,
#             "Bunker ($/gal)":     bnk_p,
#             "Asphalt ($/gal)":    asp_p,
#             "LPG/Other ($/gal)":  lpg_p,
#             "3-2-1 ($/bbl)":      r.get("spread_321"),
#             "2-1-1 ($/bbl)":      r.get("spread_211"),
#             "5-3-2 ($/bbl)":      r.get("spread_532"),
#             "Full Yield GRM":     r.get("spread_full"),
#             "Monthly GRM ($MM)":  pnl_v,
#             "Crude bbl/day":      crude_bbl_day,
#             "Gas bbl/day":        gas_bbl_day,
#             "Diesel bbl/day":     die_bbl_day,
#             "Jet bbl/day":        jet_bbl_day,
#             "Bunker bbl/day":     bnk_bbl_day,
#             "Asphalt tons/day":   asp_ton_day,
#             "LPG bbl/day":        lpg_bbl_day,
#             "Specialty Updated":  spec_date,
#             "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
#         }
#         st.download_button(
#             f"⬇️ Download {short} Today CSV",
#             data=pd.DataFrame([dl_row]).to_csv(index=False),
#             file_name=f"rogue_{short.replace(' ','_').lower()}_today.csv",
#             mime="text/csv")

#     # ══════════════════════════════════════════════════════════════════════════
#     # TAB 2 — FORWARD VIEW
#     # Layout: Calculator (all visible) → Strip preview → Charts → Volume
#     # ══════════════════════════════════════════════════════════════════════════
#     with tab_fwd:
#         rbob_spot = live_spot.get("rbob_gal",0) or 0
#         ulsd_spot = live_spot.get("ulsd_gal",0) or 0
#         wti_spot  = live_spot.get("wti_bbl", 0) or 0

#         # ── CME anchor banner ─────────────────────────────────────────────────
#         st.markdown(
#             f"<div style='background:#161B22;border:1px solid #30363D;"
#             f"border-radius:8px;padding:12px 16px;margin-bottom:14px'>"
#             f"<span style='font-size:10px;color:#8B949E;text-transform:uppercase;"
#             f"letter-spacing:1px'>CME Spot Reference — Basis Anchor</span><br>"
#             f"<span style='font-family:monospace;color:#E6EDF3'>"
#             f"WTI {fmt_bbl(wti_spot)} &nbsp;·&nbsp; "
#             f"RBOB {fmt_gal(rbob_spot)} &nbsp;·&nbsp; "
#             f"ULSD {fmt_gal(ulsd_spot)}"
#             f"</span><br>"
#             f"<span style='font-size:10px;color:#484F58'>"
#             f"CME strip drives WTI/RBOB/ULSD month-by-month. "
#             f"Adjust basis below to model location differentials.</span>"
#             f"</div>",
#             unsafe_allow_html=True)

#         # ── RESET BUTTON ──────────────────────────────────────────────────────
#         if st.button("↺ Reset to Config Defaults", key=f"fwd_reset_{n}"):
#             spec2 = sheet_prices.get(n, {})
#             ulsd2 = live_spot.get("ulsd_gal",3.5) or 3.5
#             wti2  = live_spot.get("wti_bbl",80)   or 80
#             st.session_state.update({
#                 f"fwd_light_qual_{n}":   float(loc_cfg.get("light_quality_diff",    loc_cfg.get("light_diff",0))),
#                 f"fwd_light_tariff_{n}": float(loc_cfg.get("light_transport_tariff",2.50)),
#                 f"fwd_heavy_qual_{n}":   float(loc_cfg.get("heavy_quality_diff",    loc_cfg.get("heavy_diff",0))),
#                 f"fwd_heavy_tariff_{n}": float(loc_cfg.get("heavy_transport_tariff",2.50)),
#                 f"fwd_light_pct_{n}":    80.0,
#                 f"fwd_gas_basis_{n}":   float(loc_cfg.get("gas_diff",0)),
#                 f"fwd_die_basis_{n}":   float(loc_cfg.get("diesel_diff",0)),
#                 f"fwd_jet_{n}":         spec2.get("jet_gal",   ulsd2*1.05),
#                 f"fwd_jet_delta_{n}":   0.0,
#                 f"fwd_bunker_{n}":      spec2.get("bunker_gal",ulsd2*0.70),
#                 f"fwd_bunker_delta_{n}":0.0,
#                 f"fwd_asphalt_{n}":     spec2.get("asphalt_gal",ulsd2*0.60),
#                 f"fwd_asphalt_delta_{n}":0.0,
#                 f"fwd_lpg_{n}":         spec2.get("lpg_gal",round(wti2*0.50/42,3)),
#                 f"fwd_lpg_delta_{n}":   0.0,
#                 f"fwd_dist_{n}":        0.35,
#             })
#             st.rerun()

#         # ── SECTION A: Crude slate — fully decomposed cost inputs ───────────────
#         st.markdown(
#             "<div style='background:#2A0D0D;border-radius:6px;padding:6px 12px;"
#             "margin-bottom:8px;font-size:10px;color:#F85149'>"
#             "🔴 CRUDE INLET COST — quality differential + pipeline/marine tariff "
#             "= delivered cost at refinery gate · blended across light/heavy slate"
#             "</div>",
#             unsafe_allow_html=True)

#         # Row 1: Light crude decomposition
#         la1,la2,la3 = st.columns(3)
#         la1.markdown("<div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#                      "letter-spacing:1px;margin-bottom:4px'>LIGHT CRUDE</div>",
#                      unsafe_allow_html=True)
#         light_qual = la1.number_input(
#             "Quality diff vs WTI ($/bbl)",
#             min_value=-20.0, max_value=20.0,
#             value=float(st.session_state.get(f"fwd_light_qual_{n}",
#                         loc_cfg.get("light_quality_diff", loc_cfg.get("light_diff",0)))),
#             step=0.25, format="%.2f", key=f"fp_lq_{n}")
#         st.session_state[f"fwd_light_qual_{n}"] = light_qual
#         la1.caption(f"Crude grade premium/discount vs WTI light sweet")

#         light_tariff = la2.number_input(
#             "Pipeline/marine tariff ($/bbl)",
#             min_value=0.0, max_value=20.0,
#             value=float(st.session_state.get(f"fwd_light_tariff_{n}",
#                         loc_cfg.get("light_transport_tariff", 2.50))),
#             step=0.25, format="%.2f", key=f"fp_lt_{n}")
#         st.session_state[f"fwd_light_tariff_{n}"] = light_tariff
#         la2.caption(f"Field to refinery gate · default $2.50/bbl")

#         light_pct = la3.number_input(
#             "Light crude % of slate",
#             min_value=0.0, max_value=100.0,
#             value=float(st.session_state.get(f"fwd_light_pct_{n}", 80.0)),
#             step=5.0, format="%.0f", key=f"fp_lp_{n}")
#         st.session_state[f"fwd_light_pct_{n}"] = light_pct
#         heavy_pct = 100.0 - light_pct
#         light_total = round(light_qual + light_tariff, 2)
#         eff_light_spot = round(wti_spot + light_total, 2)
#         la3.caption(f"Heavy: {heavy_pct:.0f}% | Total light diff: {light_total:+.2f}/bbl")

#         # Row 2: Heavy crude decomposition
#         lb1,lb2,lb3 = st.columns(3)
#         lb1.markdown("<div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#                      "letter-spacing:1px;margin-bottom:4px'>HEAVY CRUDE</div>",
#                      unsafe_allow_html=True)
#         heavy_qual = lb1.number_input(
#             "Quality diff vs WTI ($/bbl) ",
#             min_value=-20.0, max_value=20.0,
#             value=float(st.session_state.get(f"fwd_heavy_qual_{n}",
#                         loc_cfg.get("heavy_quality_diff", loc_cfg.get("heavy_diff",0)))),
#             step=0.25, format="%.2f", key=f"fp_hq_{n}")
#         st.session_state[f"fwd_heavy_qual_{n}"] = heavy_qual
#         lb1.caption(f"Heavy sour discount vs WTI")

#         heavy_tariff = lb2.number_input(
#             "Pipeline/marine tariff ($/bbl) ",
#             min_value=0.0, max_value=20.0,
#             value=float(st.session_state.get(f"fwd_heavy_tariff_{n}",
#                         loc_cfg.get("heavy_transport_tariff", 2.50))),
#             step=0.25, format="%.2f", key=f"fp_ht_{n}")
#         st.session_state[f"fwd_heavy_tariff_{n}"] = heavy_tariff
#         lb2.caption(f"Field to refinery gate · default $2.50/bbl")

#         heavy_total = round(heavy_qual + heavy_tariff, 2)
#         eff_heavy_spot = round(wti_spot + heavy_total, 2)
#         lb3.markdown(
#             f"<div style='padding-top:28px;font-size:11px;color:#8B949E'>"
#             f"Eff. spot heavy: ${eff_heavy_spot:.2f}/bbl<br>"
#             f"({heavy_pct:.0f}% of slate)</div>",
#             unsafe_allow_html=True)

#         # Blended crude cost — core output of slate math
#         light_f = light_pct / 100.0
#         heavy_f = heavy_pct / 100.0
#         blended_crude_diff = round(light_f * light_total + heavy_f * heavy_total, 4)
#         blended_crude_spot = round(wti_spot + blended_crude_diff, 2)

#         st.markdown(
#             f"<div style='background:#21262D;border:1px solid #F85149;"
#             f"border-radius:6px;padding:10px 16px;margin:8px 0 12px 0'>"
#             f"<div style='display:flex;gap:32px;align-items:flex-start'>"
#             f"<div>"
#             f"<div style='font-size:9px;color:#8B949E;text-transform:uppercase;"
#             f"letter-spacing:1px'>Blended Delivered Crude Cost</div>"
#             f"<div style='font-size:24px;font-weight:700;font-family:monospace;"
#             f"color:#F85149'>${blended_crude_spot:.2f}/bbl</div>"
#             f"</div>"
#             f"<div style='font-size:11px;color:#8B949E;line-height:1.8'>"
#             f"WTI spot: {fmt_bbl(wti_spot)}<br>"
#             f"+ Blended diff: {blended_crude_diff:+.2f}/bbl<br>"
#             f"= Delivered gate cost"
#             f"</div>"
#             f"<div style='font-size:11px;color:#8B949E;line-height:1.8'>"
#             f"Light ({light_pct:.0f}%): quality {light_qual:+.2f} + tariff "
#             f"+{light_tariff:.2f} = {light_total:+.2f}/bbl → ${eff_light_spot:.2f}/bbl<br>"
#             f"Heavy ({heavy_pct:.0f}%): quality {heavy_qual:+.2f} + tariff "
#             f"+{heavy_tariff:.2f} = {heavy_total:+.2f}/bbl → ${eff_heavy_spot:.2f}/bbl"
#             f"</div>"
#             f"</div></div>",
#             unsafe_allow_html=True)

#         # Product basis
#         st.markdown(
#             "<div style='background:#0D1A2A;border-radius:6px;padding:6px 12px;"
#             "margin-bottom:8px;font-size:10px;color:#4A90D9'>"
#             "🔵 PRODUCT MARKET BASIS — location differential vs NYMEX benchmark"
#             "</div>",
#             unsafe_allow_html=True)
#         b4,b5 = st.columns(2)
#         gas_basis = b4.number_input(
#             "Gasoline vs RBOB ($/gal)",
#             min_value=-1.0, max_value=1.0,
#             value=float(st.session_state.get(f"fwd_gas_basis_{n}", loc_cfg.get("gas_diff",0))),
#             step=0.01, format="%.3f", key=f"fp_gb_{n}")
#         st.session_state[f"fwd_gas_basis_{n}"] = gas_basis
#         b4.caption(f"Config: {loc_cfg.get('gas_diff',0):+.3f} | Eff. spot: ${rbob_spot+gas_basis:.3f}/gal | ${(rbob_spot+gas_basis)*42:.2f}/bbl")

#         die_basis = b5.number_input(
#             "Diesel vs ULSD ($/gal)",
#             min_value=-1.0, max_value=1.0,
#             value=float(st.session_state.get(f"fwd_die_basis_{n}", loc_cfg.get("diesel_diff",0))),
#             step=0.01, format="%.3f", key=f"fp_db_{n}")
#         st.session_state[f"fwd_die_basis_{n}"] = die_basis
#         b5.caption(f"Config: {loc_cfg.get('diesel_diff',0):+.3f} | Eff. spot: ${ulsd_spot+die_basis:.3f}/gal | ${(ulsd_spot+die_basis)*42:.2f}/bbl")

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── SECTION B: Specialty forward — green = OUTPUT REVENUES ───────────
#         st.markdown(
#             "<div style='background:#0D2A1A;border-radius:6px;padding:6px 12px;"
#             "margin-bottom:8px;font-size:10px;color:#3FB950'>"
#             "🟢 SPECIALTY PRODUCT FORWARD PRICES — output revenues · "
#             "current Google Sheet price = baseline · delta = your forward adjustment"
#             "</div>",
#             unsafe_allow_html=True)

#         sp1,sp2,sp3,sp4 = st.columns(4)
#         jet_base    = float(st.session_state.get(f"fwd_jet_{n}",     spec.get("jet_gal",    4.07)))
#         bnk_base    = float(st.session_state.get(f"fwd_bunker_{n}",  spec.get("bunker_gal", 2.52)))
#         asp_base    = float(st.session_state.get(f"fwd_asphalt_{n}", spec.get("asphalt_gal",2.16)))
#         lpg_base    = float(st.session_state.get(f"fwd_lpg_{n}",     spec.get("lpg_gal",    0.95)))

#         jet_delta = sp1.number_input(
#             f"Jet delta vs ${jet_base:.2f} today ($/gal)",
#             min_value=-3.0, max_value=3.0,
#             value=float(st.session_state.get(f"fwd_jet_delta_{n}", 0.0)),
#             step=0.05, format="%.2f", key=f"fp_jd_{n}")
#         st.session_state[f"fwd_jet_delta_{n}"] = jet_delta
#         eff_jet = jet_base + jet_delta
#         sp1.caption(f"Forward: ${eff_jet:.3f}/gal | ${eff_jet*42:.2f}/bbl")

#         bnk_delta = sp2.number_input(
#             f"Bunker delta vs ${bnk_base:.2f} today ($/gal)",
#             min_value=-2.0, max_value=2.0,
#             value=float(st.session_state.get(f"fwd_bunker_delta_{n}", 0.0)),
#             step=0.05, format="%.2f", key=f"fp_bd_{n}")
#         st.session_state[f"fwd_bunker_delta_{n}"] = bnk_delta
#         eff_bunker = bnk_base + bnk_delta
#         sp2.caption(f"Forward: ${eff_bunker:.3f}/gal | ${eff_bunker*42:.2f}/bbl")

#         asp_delta = sp3.number_input(
#             f"Asphalt delta vs ${asp_base:.2f} today ($/gal)",
#             min_value=-2.0, max_value=2.0,
#             value=float(st.session_state.get(f"fwd_asphalt_delta_{n}", 0.0)),
#             step=0.05, format="%.2f", key=f"fp_ad_{n}")
#         st.session_state[f"fwd_asphalt_delta_{n}"] = asp_delta
#         eff_asphalt = asp_base + asp_delta
#         sp3.caption(f"Forward: ${eff_asphalt:.3f}/gal | ${eff_asphalt*42:.2f}/bbl")

#         lpg_delta = sp4.number_input(
#             f"LPG delta vs ${lpg_base:.2f} today ($/gal)",
#             min_value=-1.0, max_value=1.0,
#             value=float(st.session_state.get(f"fwd_lpg_delta_{n}", 0.0)),
#             step=0.01, format="%.2f", key=f"fp_ld_{n}")
#         st.session_state[f"fwd_lpg_delta_{n}"] = lpg_delta
#         eff_lpg = lpg_base + lpg_delta
#         sp4.caption(f"Forward: ${eff_lpg:.3f}/gal | ${eff_lpg*42:.2f}/bbl")

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── SECTION C: Refinery config — grey = CONVERSION ───────────────────
#         st.markdown(
#             "<div style='background:#1A1A2A;border-radius:6px;padding:6px 12px;"
#             "margin-bottom:8px;font-size:10px;color:#8B949E'>"
#             "⚙️ REFINERY CONFIGURATION — throughput & yield fractions "
#             "(determines barrels of each product produced)"
#             "</div>",
#             unsafe_allow_html=True)

#         YLBLS = {
#             "gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#             "bunker":"Bunker","asphalt":"Asphalt",
#             "lpg_other":"LPG/Other","refinery_use":"Ref. Use",
#         }
#         c1,c2,c3,c4,c5,c6,c7,c8 = st.columns(8)
#         fwd_tp = int(c1.number_input(
#             "Throughput (bbl/d)", 0, 500000,
#             int(st.session_state.get(f"fwd_tp_{n}", 30000)),
#             1000, key=f"fp_tp_{n}"))
#         st.session_state[f"fwd_tp_{n}"] = fwd_tp
#         fwd_dist = float(c2.number_input(
#             "Dist margin ($/gal)", 0.0, 1.0,
#             float(st.session_state.get(f"fwd_dist_{n}", 0.35)),
#             0.01, "%.2f", key=f"fp_dist_{n}"))
#         st.session_state[f"fwd_dist_{n}"] = fwd_dist

#         fwd_yields = {}
#         total_y = 0.0
#         for col, (k, lbl) in zip([c3,c4,c5,c6,c7,c8], list(YLBLS.items())):
#             default = round(YIELD_DEFAULTS.get(k,0)*100, 1)
#             val = col.number_input(
#                 f"{lbl} (%)", 0.0, 100.0,
#                 float(st.session_state.get(f"fwd_y_{k}_{n}", default)),
#                 0.5, "%.1f", key=f"fp_y_{k}_{n}")
#             st.session_state[f"fwd_y_{k}_{n}"] = val
#             fwd_yields[k] = round(val/100, 6)
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(
#             f"<span style='color:{yc};font-size:11px'>Yield total: {total_y:.1f}%</span>",
#             unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── Compute forward curve ─────────────────────────────────────────────
#         # Use blended crude diff (light% × light_basis + heavy% × heavy_basis)
#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff=blended_crude_diff, gas_diff=gas_basis,
#             diesel_diff=die_basis,
#             jet_fwd=eff_jet, bunker_fwd=eff_bunker,
#             asphalt_fwd=eff_asphalt, lpg_fwd=eff_lpg,
#             yields=fwd_yields)

#         if not loc_fwd:
#             st.info("Forward curve data not available. Check CME connection.")
#         else:
#             fwd_ok     = [row for row in loc_fwd if row.get("crack_321")]
#             months     = [row["month"]       for row in fwd_ok]
#             wti_fwd    = [row["wti"]         for row in fwd_ok]
#             rbob_f     = [row.get("rbob",0)  for row in fwd_ok]
#             ulsd_f     = [row.get("ulsd",0)  for row in fwd_ok]
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             full_vals  = [row.get("crack_full") for row in fwd_ok]

#             y_g2  = fwd_yields.get("gasoline",  0.445)
#             y_d2  = fwd_yields.get("ulsd",      0.290)
#             y_j2  = fwd_yields.get("jet",       0.110)
#             y_b2  = fwd_yields.get("bunker",    0.035)
#             y_a2  = fwd_yields.get("asphalt",   0.025)
#             y_l2  = fwd_yields.get("lpg_other", 0.040)
#             y_ru2 = fwd_yields.get("refinery_use",0.055)

#             gas_rev = [round((rb+gas_basis)*y_g2*42, 2) for rb in rbob_f]
#             die_rev = [round((ul+die_basis)*y_d2*42, 2) for ul in ulsd_f]
#             jet_rev = [round(eff_jet    *y_j2*42, 2)] * len(months)
#             bnk_rev = [round(eff_bunker *y_b2*42, 2)] * len(months)
#             asp_rev = [round(eff_asphalt*y_a2*42, 2)] * len(months)
#             lpg_rev = [round(eff_lpg    *y_l2*42, 2)] * len(months)
#             grm_list= [round(v*fwd_tp*30/1e6,2) if v else None for v in crack_vals]

#             # Price strip preview (next 6 months)
#             st.markdown("<div class='sec-hdr'>Effective Forward Price Strip — Next 6 Months</div>",
#                         unsafe_allow_html=True)
#             if wti_fwd:
#                 strip_df = pd.DataFrame({
#                     "Month":              months[:6],
#                     "WTI+Blend ($/bbl)":  [f"${v+blended_crude_diff:.2f}"  for v in wti_fwd[:6]],
#                     "RBOB+Basis ($/gal)": [f"${v+gas_basis:.3f}"    for v in rbob_f[:6]],
#                     "ULSD+Basis ($/gal)": [f"${v+die_basis:.3f}"    for v in ulsd_f[:6]],
#                     "Jet fwd ($/gal)":    [f"${eff_jet:.3f}"]    * 6,
#                     "Bunker fwd ($/gal)": [f"${eff_bunker:.3f}"]  * 6,
#                     "Asphalt fwd ($/gal)":[f"${eff_asphalt:.3f}"] * 6,
#                     "LPG fwd ($/gal)":    [f"${eff_lpg:.3f}"]     * 6,
#                     "3-2-1 GRM ($/bbl)":  [f"${v:.2f}" if v else "—" for v in crack_vals[:6]],
#                     "Full Yield ($/bbl)": [f"${v:.2f}" if v else "—" for v in full_vals[:6]],
#                     f"GRM $MM/mo ({fwd_tp//1000}k bbl/d)": [f"${v:.1f}MM" if v else "—" for v in grm_list[:6]],
#                 })
#                 st.dataframe(strip_df, use_container_width=True, hide_index=True)
#                 st.caption(
#                     "WTI/RBOB/ULSD from CME settle strip + your basis adjustments · "
#                     "Specialty products flat at forward assumption · "
#                     "Green/amber/red = STRONG/MODERATE/THIN margin")

#             st.markdown("<br>", unsafe_allow_html=True)

#             # Chart 1: Area chart
#             st.markdown("<div class='sec-hdr'>Forward Product Revenue vs Crude Cost</div>",
#                         unsafe_allow_html=True)
#             AREA_COLORS = {
#                 "Gasoline":  "rgba(74,144,217,0.75)",
#                 "Diesel":    "rgba(232,160,32,0.75)",
#                 "Jet Fuel":  "rgba(90,158,58,0.75)",
#                 "Bunker":    "rgba(139,79,191,0.75)",
#                 "Asphalt":   "rgba(204,119,34,0.75)",
#                 "LPG/Other": "rgba(58,166,185,0.75)",
#             }
#             fig_fwd = go.Figure()
#             for name, vals in [
#                 ("Gasoline",  gas_rev), ("Diesel",    die_rev),
#                 ("Jet Fuel",  jet_rev), ("Bunker",    bnk_rev),
#                 ("Asphalt",   asp_rev), ("LPG/Other", lpg_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one", line=dict(width=0)))
#             # Adjust wti_fwd by blended diff for chart display
#             wti_blend_fwd = [round(v+blended_crude_diff,2) for v in wti_fwd]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_blend_fwd, name="Blended Crude Cost",
#                 line=dict(color="#FFFFFF", width=2.5), mode="lines"))
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals, name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149", width=2, dash="dot"), yaxis="y2"))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)", gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="3-2-1 Crack ($/bbl)", font=dict(color="#F85149")),
#                     overlaying="y", side="right", showgrid=False,
#                     tickfont=dict(color="#F85149")),
#                 legend=dict(bgcolor="#161B22", font=dict(size=10),
#                             orientation="h", yanchor="bottom", y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified")
#             if months and wti_fwd:
#                 fig_fwd.add_annotation(
#                     x=months[len(months)//2],
#                     y=wti_blend_fwd[len(wti_blend_fwd)//2]+5,
#                     text="↑ Gap = Margin", showarrow=False,
#                     font=dict(color="#FFFFFF", size=10),
#                     bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = product revenues · "
#                 "Gas & diesel driven by CME strip + basis · "
#                 "Specialty products (jet/bunker/asphalt/LPG) held flat · "
#                 "White line = crude cost · Gap above white = margin · "
#                 "Red dashed (right axis) = 3-2-1 crack spread")

#             # Chart 2: Stress ±20%
#             fov = [v for v in full_vals if v is not None]
#             fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
#             if fov:
#                 fwd_dn = compute_forward_crack(
#                     strip=strip,
#                     crude_diff=blended_crude_diff+(wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff=gas_basis-0.20, diesel_diff=die_basis-0.20,
#                     jet_fwd=eff_jet*0.80, bunker_fwd=eff_bunker*0.80,
#                     asphalt_fwd=eff_asphalt*0.80, lpg_fwd=eff_lpg*0.80,
#                     yields=fwd_yields)
#                 fwd_up = compute_forward_crack(
#                     strip=strip,
#                     crude_diff=blended_crude_diff-(wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff=gas_basis+0.20, diesel_diff=die_basis+0.20,
#                     jet_fwd=eff_jet*1.20, bunker_fwd=eff_bunker*1.20,
#                     asphalt_fwd=eff_asphalt*1.20, lpg_fwd=eff_lpg*1.20,
#                     yields=fwd_yields)
#                 sdn=[row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
#                 sup=[row.get("crack_full") for row in fwd_up if row.get("crack_full")]
#                 mdn=[row["month"] for row in fwd_dn if row.get("crack_full")]
#                 mup=[row["month"] for row in fwd_up if row.get("crack_full")]

#                 st.markdown("<div class='sec-hdr'>Forward GRM Stress Test ±20%</div>",
#                             unsafe_allow_html=True)
#                 fig_st = go.Figure()
#                 if sdn and len(sdn)==len(fov):
#                     fig_st.add_trace(go.Scatter(
#                         x=mdn+mdn[::-1], y=sdn+fov[::-1], fill="toself",
#                         fillcolor="rgba(248,81,73,0.12)",
#                         line=dict(width=0), name="Downside −20%", hoverinfo="skip"))
#                 if sup and len(sup)==len(fov):
#                     fig_st.add_trace(go.Scatter(
#                         x=mup+mup[::-1], y=sup+fov[::-1], fill="toself",
#                         fillcolor="rgba(63,185,80,0.10)",
#                         line=dict(width=0), name="Upside +20%", hoverinfo="skip"))
#                 fig_st.add_trace(go.Scatter(
#                     x=fmo, y=fov, name="Full Yield GRM — Base",
#                     line=dict(color="#E8A020", width=2.5),
#                     mode="lines+markers", marker=dict(size=5)))
#                 if sdn:
#                     fig_st.add_trace(go.Scatter(
#                         x=mdn, y=sdn, name="Downside boundary",
#                         line=dict(color="#F85149", width=1.5, dash="dash")))
#                 if sup:
#                     fig_st.add_trace(go.Scatter(
#                         x=mup, y=sup, name="Upside boundary",
#                         line=dict(color="#3FB950", width=1.5, dash="dash")))
#                 fig_st.add_hline(y=15, line_dash="dot", line_color="#8B949E",
#                     opacity=0.5, annotation_text="~Breakeven $15/bbl",
#                     annotation_font_color="#8B949E", annotation_font_size=9)
#                 fig_st.update_layout(
#                     title=dict(text="Full Yield GRM — Forward Stress ±20%",
#                                font=dict(color="#E6EDF3", size=13)),
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                     yaxis=dict(title="Full Yield GRM ($/bbl)", gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22", font=dict(size=10),
#                                 orientation="h", yanchor="bottom", y=1.02),
#                     margin=dict(l=0,r=0,t=40,b=0), height=320)
#                 st.plotly_chart(fig_st, use_container_width=True)
#                 st.caption(
#                     "Base = Full Yield GRM at your basis assumptions · "
#                     "Red = downside (crude +20%, products −20%) · "
#                     "Green = upside (crude −20%, products +20%) · "
#                     "Band width = margin sensitivity to ±20% price moves")

#             # Chart 3: Monthly GRM bar
#             st.markdown("<div class='sec-hdr'>Monthly GRM ($MM) — Forward View</div>",
#                         unsafe_allow_html=True)
#             fig_grm_mo = go.Figure()
#             fig_grm_mo.add_trace(go.Bar(
#                 x=months, y=grm_list,
#                 marker_color=[spread_color(v) for v in crack_vals],
#                 text=[f"${v:.1f}MM" if v else "—" for v in grm_list],
#                 textposition="outside",
#                 textfont=dict(size=9, color="#E6EDF3"),
#                 name="Monthly GRM ($MM)"))
#             fig_grm_mo.add_hline(y=0, line_color="#484F58", line_width=1)
#             fig_grm_mo.update_layout(
#                 title=dict(
#                     text=f"Monthly Gross Refining Margin @ {fwd_tp:,} bbl/day",
#                     font=dict(color="#E6EDF3", size=12)),
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="$MM/month", gridcolor="#21262D"),
#                 margin=dict(l=0,r=0,t=36,b=0), height=280, showlegend=False)
#             st.plotly_chart(fig_grm_mo, use_container_width=True)

#             # Operations / volume view
#             st.markdown(
#                 f"<div class='sec-hdr'>Forward Operations View — "
#                 f"Volumes at {fwd_tp:,} bbl/day</div>",
#                 unsafe_allow_html=True)
#             f_gas_bbl  = round(fwd_tp * y_g2)
#             f_die_bbl  = round(fwd_tp * y_d2)
#             f_jet_bbl  = round(fwd_tp * y_j2)
#             f_bnk_bbl  = round(fwd_tp * y_b2)
#             f_asp_bbl  = round(fwd_tp * y_a2)
#             f_lpg_bbl  = round(fwd_tp * y_l2)
#             f_ref_bbl  = round(fwd_tp * y_ru2)
#             f_asp_tons = round(f_asp_bbl / 6.3, 1)

#             f_light_bbl = round(fwd_tp * light_f)
#             f_heavy_bbl = round(fwd_tp * heavy_f)
#             fwd_ops_rows = [
#                 ("Light Crude",  "🔴 INPUT (cost)",   f_light_bbl, f"{f_light_bbl*42:,.0f}",
#                  f"{f_light_bbl*30:,.0f}", f"WTI+{light_total:+.2f} = ${eff_light_spot:.2f}/bbl",
#                  f"{light_pct:.0f}% of slate"),
#                 ("Heavy Crude",  "🔴 INPUT (cost)",   f_heavy_bbl, f"{f_heavy_bbl*42:,.0f}",
#                  f"{f_heavy_bbl*30:,.0f}", f"WTI+{heavy_total:+.2f} = ${eff_heavy_spot:.2f}/bbl",
#                  f"{heavy_pct:.0f}% of slate"),
#                 ("Blended Crude","🔴 TOTAL INPUT",    fwd_tp,      f"{fwd_tp*42:,.0f}",
#                  f"{fwd_tp*30:,.0f}", f"Blended = ${blended_crude_spot:.2f}/bbl",
#                  f"Weighted avg of slate"),
#                 ("Gasoline",     "🟢 OUTPUT (rev)",   f_gas_bbl, f"{f_gas_bbl*42:,.0f}",
#                  f"{f_gas_bbl*30:,.0f}",f"CME RBOB+{gas_basis:+.3f}/gal",
#                  f"Strip-driven price"),
#                 ("Diesel/ULSD",  "🟢 OUTPUT (rev)",   f_die_bbl, f"{f_die_bbl*42:,.0f}",
#                  f"{f_die_bbl*30:,.0f}",f"CME ULSD+{die_basis:+.3f}/gal",
#                  f"Strip-driven price"),
#                 ("Jet Fuel",     "🟢 OUTPUT (rev)",   f_jet_bbl, f"{f_jet_bbl*42:,.0f}",
#                  f"{f_jet_bbl*30:,.0f}",f"${eff_jet:.3f}/gal flat",
#                  f"${eff_jet*42:.2f}/bbl"),
#                 ("Bunker Fuel",  "🟢 OUTPUT (rev)",   f_bnk_bbl, f"{f_bnk_bbl*42:,.0f}",
#                  f"{f_bnk_bbl*30:,.0f}",f"${eff_bunker:.3f}/gal flat",
#                  f"${eff_bunker*42:.2f}/bbl"),
#                 ("Asphalt",      "🟢 OUTPUT (rev)",   f_asp_bbl, f"{f_asp_tons:.0f} t/day",
#                  f"{f_asp_bbl*30:,.0f}",f"${eff_asphalt:.3f}/gal flat",
#                  f"${eff_asphalt*42:.2f}/bbl | ÷6.3 bbl/ton"),
#                 ("LPG/Other",    "🟢 OUTPUT (rev)",   f_lpg_bbl, f"{f_lpg_bbl*42:,.0f}",
#                  f"{f_lpg_bbl*30:,.0f}",f"${eff_lpg:.3f}/gal flat",
#                  f"${eff_lpg*42:.2f}/bbl"),
#                 ("Refinery Use", "⚫ LOSS (no rev)",  f_ref_bbl, "—",
#                  f"{f_ref_bbl*30:,.0f}","Burned onsite",
#                  "Fuel gas + processing losses"),
#             ]
#             fwd_ops_df = pd.DataFrame(fwd_ops_rows, columns=[
#                 "Stream", "Type", "bbl/day",
#                 "gal or tons/day", "bbl/month",
#                 "Forward Price", "Notes"])
#             fwd_ops_df["bbl/day"] = fwd_ops_df["bbl/day"].apply(
#                 lambda x: f"{int(x):,}" if isinstance(x,(int,float)) else x)
#             st.dataframe(fwd_ops_df, use_container_width=True, hide_index=True)
#             st.caption(
#                 "Gas & diesel priced from CME forward strip + location basis · "
#                 "Specialty products flat at your forward assumption · "
#                 "Asphalt in short tons (6.3 bbl/short ton) · "
#                 "bbl/month = daily × 30")

#             # Full forward GRM table + download
#             fwd_df = pd.DataFrame({
#                 "Month":               months,
#                 "WTI+Blend ($/bbl)":   [round(v+blended_crude_diff, 2) for v in wti_fwd],
#                 "RBOB+Basis ($/gal)":  [round(v+gas_basis,   3) for v in rbob_f],
#                 "ULSD+Basis ($/gal)":  [round(v+die_basis,   3) for v in ulsd_f],
#                 "Jet Fwd ($/gal)":     [eff_jet]     * len(months),
#                 "Bunker Fwd ($/gal)":  [eff_bunker]  * len(months),
#                 "Asphalt Fwd ($/gal)": [eff_asphalt] * len(months),
#                 "LPG Fwd ($/gal)":     [eff_lpg]     * len(months),
#                 "3-2-1 GRM ($/bbl)":   crack_vals,
#                 "Full Yield ($/bbl)":  full_vals,
#                 f"GRM $MM/mo @ {fwd_tp//1000}k bbl/d": grm_list,
#             })
#             with st.expander("📋 Full Forward GRM Table + Download"):
#                 st.dataframe(fwd_df, use_container_width=True, hide_index=True)
#                 st.download_button(
#                     f"⬇️ Download {short} Forward CSV",
#                     data=fwd_df.to_csv(index=False),
#                     file_name=f"rogue_{short.replace(' ','_').lower()}_forward.csv",
#                     mime="text/csv")



# # ══════════════════════════════════════════════════════════════════════════════
# # METHODOLOGY
# # ══════════════════════════════════════════════════════════════════════════════
# def show_methodology():
#     with st.expander("📋 Methodology & Data Sources", expanded=False):
#         st.markdown("""
# <div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

# ### What this tool calculates
# **Gross Refining Margin (GRM)** = Σ(Product Price × Yield × 42) − Crude Cost.
# Operating costs ($4–8/bbl) are **not** deducted.

# ### Two views
# **Today:** 100% live data. Read-only. AAA gas/diesel daily, CME crude,
# Google Sheet specialty prices.

# **Forward:** Basis-driven model. CME forward strip provides WTI/RBOB/ULSD
# month-by-month. You adjust *basis* (location differential vs NYMEX benchmark)
# and specialty product forward assumptions. All other prices follow the curve.

# ### Price sources
# | Input | Source | Frequency |
# |---|---|---|
# | Retail gas & diesel | AAA Fuel Gauge metro survey | Daily |
# | WTI, RBOB, ULSD spot | CME first-month settle | Daily |
# | WTI, RBOB, ULSD forward | CME settle strip (local xlsx) | Daily |
# | Jet, Bunker, Asphalt, LPG | Google Sheet (per location) | Weekly |
# | Federal excise tax | IRS — fixed since Oct 1993 | Static |
# | State excise taxes | FTA + EIA, Jul 2025 | Semiannual |

# ### Price waterfall
# Retail pump (AAA) − Federal excise ($0.184 gas / $0.244 diesel) − State excise
# − Distribution ($0.35/gal default) = Wholesale / refinery gate price

# ### State excise taxes (Jul 2025)
# AK $0.0895 · TX $0.200 · OK $0.190 · ND $0.230 · UT $0.385 · LA $0.200 · NM $0.229/$0.270

# ### Full Yield defaults (EIA 2024 national average)
# Gas 44.5% · Diesel 29.0% · Jet 11.0% · Bunker 3.5% · Asphalt 2.5% · LPG/Other 4.0% · Ref. Use 5.5% = 100%
# Source: EIA PSM 2024 / eia.gov/todayinenergy/detail.php?id=64786

# ### Not captured
# Opex ($3–8/bbl) · RINs · Blendstock costs · Pipeline tariffs · Carbon · Hedging

# </div>""", unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # MAIN
# # ══════════════════════════════════════════════════════════════════════════════
# def main():
#     check_password()

#     st.markdown(
#         "<h2 style='color:#E6EDF3;margin-bottom:2px;margin-top:-8px'>"
#         "🏭 Rogue Refinery Economics</h2>"
#         "<p style='color:#8B949E;margin-bottom:10px;font-size:12px'>"
#         "Portfolio intelligence · CME forward curves · Gross Refining Margin</p>",
#         unsafe_allow_html=True)

#     with st.sidebar:
#         st.markdown(
#             "<div style='text-align:center;padding:10px 0'>"
#             "<span style='font-size:26px'>🏭</span><br>"
#             "<span style='color:#E8A020;font-weight:700;font-size:13px;"
#             "letter-spacing:2px'>ROGUE REFINERY</span><br>"
#             "<span style='color:#8B949E;font-size:10px;letter-spacing:1px'>"
#             "ECONOMICS DASHBOARD</span></div>",
#             unsafe_allow_html=True)
#         st.markdown("---")
#         if st.button("🔄 Refresh All Data", use_container_width=True):
#             get_cme.clear(); get_spot.clear()
#             get_lp.clear();  get_spec.clear()
#             get_specialty_sheet.clear()
#             auth = st.session_state.get("auth")
#             for k in list(st.session_state.keys()):
#                 del st.session_state[k]
#             if auth: st.session_state["auth"] = auth
#             st.rerun()
#         st.markdown("---")
#         st.caption(
#             "**Today:** live prices — read only.\n\n"
#             "**Forward:** CME strip + location basis.\n\n"
#             "Specialty prices (jet/bunker/asphalt/LPG) updated "
#             "weekly via Google Sheet.")

#     with st.spinner("Loading market data..."):
#         strip        = get_cme()
#         lp           = get_lp()
#         sheet_prices = get_specialty_sheet()
#         live_spot    = get_spot()

#     live_margins, _, _ = build_live_margins(lp, sheet_prices)
#     render_ticker(live_spot, live_margins)

#     view = st.session_state.get("view","portfolio")
#     if view == "portfolio":
#         show_portfolio(live_margins)
#         show_methodology()
#     else:
#         show_detail(live_margins, strip, sheet_prices, live_spot)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
#         f"AAA Fuel Gauge · EIA API · CME local xlsx · Google Sheet · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()

