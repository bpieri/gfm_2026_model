
# app.py — Rogue Refinery Economics v5
# Two-tab per-refinery layout: Today | Forward
# Specialty prices from Google Sheet (jet, bunker, asphalt, lpg per location)
# Edmonton removed — to be added back later
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


# ── Scroll to top on page transition ──────────────────────────────────────────
def _scroll_top():
    components.html("""
        <script>
        (function() {
            function scrollUp() {
                var sel = [
                    '[data-testid="stAppViewContainer"]',
                    '[data-testid="stMain"]',
                    '.main', 'section.main', 'body'
                ];
                for (var i=0; i<sel.length; i++) {
                    var el = window.parent.document.querySelector(sel[i]);
                    if (el) el.scrollTop = 0;
                }
                window.parent.scrollTo(0,0);
            }
            scrollUp();
            setTimeout(scrollUp, 150);
            setTimeout(scrollUp, 400);
        })();
        </script>
    """, height=0)


st.set_page_config(page_title="Rogue Refinery Economics",
                   page_icon="🏭", layout="wide")

st.markdown("""
<style>
.stApp{background:#0D1117}
.ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
  border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.ticker-item{display:flex;flex-direction:column;align-items:center}
.ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
.ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
.ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
.sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
  text-transform:uppercase;margin:10px 0 6px 0}
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
.metric-card{background:#161B22;border:1px solid #30363D;border-radius:8px;
  padding:14px;text-align:center}
.mc-label{font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px}
.mc-value{font-size:20px;font-weight:700;color:#E6EDF3;font-family:monospace}
.mc-sub{font-size:10px;color:#8B949E;margin-top:2px}
.price-pill{display:inline-block;background:#21262D;border:1px solid #30363D;
  border-radius:6px;padding:6px 14px;margin:3px;text-align:center}
.price-pill-label{font-size:9px;color:#8B949E;text-transform:uppercase;
  letter-spacing:1px;display:block}
.price-pill-value{font-size:15px;font-weight:700;color:#E6EDF3;
  font-family:monospace;display:block}
#MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
.block-container{padding-top:0.3rem !important;padding-bottom:0 !important}
[data-testid="stAppViewContainer"]>[data-testid="stVerticalBlock"]{padding-top:0 !important}
h2{margin-top:0 !important}
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
    """
    Fetch per-location specialty prices from Google Sheet.
    Returns {location_display: {jet_gal, bunker_gal, asphalt_gal, lpg_gal, last_updated}}
    Falls back to SPECIALTY_DEFAULTS if sheet unavailable.
    """
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
                "lpg_gal":     float(row.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal", 0.95))),
                "last_updated":row.get("last_updated","—"),
            }
        print(f"  Google Sheet: loaded {len(result)} locations")
        return result
    except Exception as e:
        print(f"  Google Sheet fetch failed: {e} — using defaults")
        return {}

@st.cache_data(ttl=3600)
def get_cme():  return fetch_cme_forward_curve()

@st.cache_data(ttl=3600)
def get_spot(): return fetch_spot_prices(EIA_API_KEY)

@st.cache_data(ttl=3600)
def get_lp():   return fetch_location_prices(LOCATIONS)

@st.cache_data(ttl=86400)
def get_spec(): return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# ── Build live margins (Today tab — no user overrides) ────────────────────────
def build_live_margins(lp, sheet_prices):
    """
    Build margins from 100% live data — no user inputs involved.
    Gas/diesel: AAA retail → tax strip → distribution strip.
    Crude: CME first-month settle + location diff from config.
    Specialty: per-location from Google Sheet, EIA fallback.
    Yields: EIA 2024 defaults from config (not user-adjustable in Today tab).
    """
    live_spot = get_spot()
    eia_spec  = get_spec()

    yields = {k: v for k, v in YIELD_DEFAULTS.items()}

    rows = []
    for loc in LOCATIONS:
        n    = loc["display"]
        spec = sheet_prices.get(n, {})
        location_specialty = {
            "jet_gal":     spec.get("jet_gal",     eia_spec.get("jet_gal")     or live_spot.get("ulsd_gal",3.5)*1.05),
            "bunker_gal":  spec.get("bunker_gal",  eia_spec.get("bunker_gal")  or live_spot.get("ulsd_gal",3.5)*0.70),
            "asphalt_gal": spec.get("asphalt_gal", eia_spec.get("asphalt_gal") or live_spot.get("ulsd_gal",3.5)*0.60),
            "lpg_gal":     spec.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal", 0.95)),
        }
        loc_list = [dict(loc)]
        margin_list = compute_location_margins(
            locations       = loc_list,
            spot_prices     = live_spot,
            location_prices = lp,
            specialty       = location_specialty,
            yields          = yields,
            dist_margin_gal = 0.35,
        )
        if margin_list:
            r = margin_list[0]
            r["throughput"]   = loc.get("throughput", 30000)
            r["pnl"]          = fmt_grm(r.get("spread_321"), r["throughput"])
            r["specialty"]    = location_specialty
            r["spec_updated"] = spec.get("last_updated","—")
            rows.append(r)

    return rows, live_spot, yields


# ── Session state for forward tab inputs ──────────────────────────────────────
def init_fwd_state(loc_display, sheet_prices, live_spot):
    """Initialise per-location forward inputs from live data if not set."""
    n = loc_display
    if st.session_state.get(f"_fwd_init_{n}"): return
    spec = sheet_prices.get(n, {})
    ulsd = live_spot.get("ulsd_gal", 3.50) or 3.50
    wti  = live_spot.get("wti_bbl",  80.0) or 80.0
    st.session_state.update({
        f"fwd_wti_{n}":    wti,
        f"fwd_rbob_{n}":   live_spot.get("rbob_gal", 2.50) or 2.50,
        f"fwd_ulsd_{n}":   ulsd,
        f"fwd_jet_{n}":    spec.get("jet_gal",     ulsd * 1.05),
        f"fwd_bunker_{n}": spec.get("bunker_gal",  ulsd * 0.70),
        f"fwd_asphalt_{n}":spec.get("asphalt_gal", ulsd * 0.60),
        f"fwd_lpg_{n}":    spec.get("lpg_gal",     round(wti*0.50/42,3)),
        f"fwd_dist_{n}":   0.35,
        f"fwd_fcd_{n}":    0.0,
        f"fwd_fgd_{n}":    0.0,
        f"fwd_fdd_{n}":    0.0,
        f"fwd_tp_{n}":     30000,
    })
    for k, v in YIELD_DEFAULTS.items():
        if f"fwd_y_{k}_{n}" not in st.session_state:
            st.session_state[f"fwd_y_{k}_{n}"] = round(v * 100, 1)
    st.session_state[f"_fwd_init_{n}"] = True


# ── Ticker bar ─────────────────────────────────────────────────────────────────
def render_ticker(live_spot, live_margins):
    wti  = live_spot.get("wti_bbl")
    rbob = live_spot.get("rbob_gal")
    ulsd = live_spot.get("ulsd_gal")
    spreads   = [r["spread_321"] for r in live_margins if r.get("spread_321")]
    pavg      = round(sum(spreads)/len(spreads),2) if spreads else None
    total_grm = sum(r["pnl"] for r in live_margins if r.get("pnl"))
    pc = spread_color(pavg)
    st.markdown(f"""
    <div class="ticker-bar">
      <div class="ticker-item">
        <span class="ticker-label">WTI Crude</span>
        <span class="ticker-value">{fmt_bbl(wti)}</span>
        <span class="ticker-label">per barrel</span>
      </div><div class="ticker-divider"></div>
      <div class="ticker-item">
        <span class="ticker-label">RBOB</span>
        <span class="ticker-value">{fmt_gal(rbob)}</span>
        <span class="ticker-label">per gallon</span>
      </div><div class="ticker-divider"></div>
      <div class="ticker-item">
        <span class="ticker-label">ULSD</span>
        <span class="ticker-value">{fmt_gal(ulsd)}</span>
        <span class="ticker-label">per gallon</span>
      </div><div class="ticker-divider"></div>
      <div class="ticker-item">
        <span class="ticker-label">RBOB $/bbl</span>
        <span class="ticker-value">{fmt_bbl(round(rbob*42,2) if rbob else None)}</span>
        <span class="ticker-label">×42</span>
      </div><div class="ticker-divider"></div>
      <div class="ticker-item">
        <span class="ticker-label">Portfolio Avg 3-2-1</span>
        <span class="ticker-value" style="color:{pc}">
          {"$"+str(pavg)+"/bbl" if pavg else "—"}
        </span>
        <span class="ticker-label" style="color:{pc}">{spread_label(pavg)}</span>
      </div><div class="ticker-divider"></div>
      <div class="ticker-item">
        <span class="ticker-label">Portfolio GRM/mo</span>
        <span class="ticker-value" style="color:#3FB950">
          {"$"+str(round(total_grm,1))+"MM" if total_grm else "—"}
        </span>
        <span class="ticker-label">before opex</span>
      </div>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — PORTFOLIO COMMAND VIEW
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

    # Map
    st.markdown("<div class='sec-hdr'>Portfolio Map — 3-2-1 Crack Spread</div>",
                unsafe_allow_html=True)
    map_rows = []
    for r in live_margins:
        c = LOC_COORDS.get(r["display"],(39.5,-98.35))
        s = r.get("spread_321")
        spec = r.get("specialty",{})
        map_rows.append({
            "name":   r["display"],
            "short":  r["display"].split("—")[-1].split(",")[0].strip(),
            "lat":    c[0], "lon": c[1],
            "spread": s, "color": spread_color(s),
            "hover": (
                f"<b>{r['display']}</b><br>"
                f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
                f"Full Yield GRM: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
                f"GRM/mo: {'$'+str(r['pnl'])+'MM' if r.get('pnl') else '—'}<br>"
                f"Jet: ${spec.get('jet_gal','—')}/gal  Bunker: ${spec.get('bunker_gal','—')}/gal<br>"
                f"<i>Click card below to open</i>"
            ),
        })
    df_m = pd.DataFrame(map_rows)
    fig_m = go.Figure()
    fig_m.add_trace(go.Scattergeo(
        lat=df_m["lat"], lon=df_m["lon"], mode="markers+text",
        marker=dict(size=20, color=df_m["color"].tolist(),
                    line=dict(width=2,color="#0D1117"), opacity=0.90),
        text=df_m["short"], textposition="top center",
        textfont=dict(size=10,color="#E6EDF3"),
        hovertext=df_m["hover"], hoverinfo="text"))
    for _, row in df_m.iterrows():
        if row["spread"]:
            fig_m.add_trace(go.Scattergeo(
                lat=[row["lat"]-1.9], lon=[row["lon"]], mode="text",
                text=[f"${row['spread']:.0f}"],
                textfont=dict(size=10,color=row["color"],family="monospace"),
                hoverinfo="skip", showlegend=False))
    fig_m.update_layout(
        geo=dict(scope="world", showland=True, landcolor="#1C2128",
                 showocean=True, oceancolor="#0D1117",
                 showlakes=True, lakecolor="#0D1117",
                 showcountries=True, countrycolor="#30363D",
                 showcoastlines=True, coastlinecolor="#30363D",
                 showframe=False, bgcolor="#0D1117",
                 center=dict(lat=45,lon=-100), projection_scale=1.4,
                 lonaxis_range=[-175,-50], lataxis_range=[10,78]),
        paper_bgcolor="#0D1117", margin=dict(l=0,r=0,t=0,b=0),
        height=400, showlegend=False)
    for lbl,clr,ya in [("● STRONG ≥$25","#3FB950",0.13),
                        ("● MODERATE $12–25","#E8A020",0.09),
                        ("● THIN <$12","#F85149",0.05)]:
        fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
            text=lbl,showarrow=False,font=dict(color=clr,size=10),
            bgcolor="#0D1117",align="left")
    st.plotly_chart(fig_m, use_container_width=True)

    # Location cards
    IN_CONSTRUCTION  = {"Victoria, TX","Duncan, OK"}
    DEVELOPMENT_ORDER = [
        ("Alaska — Port Mackenzie","Port Mackenzie","AK"),
        ("Greenport — Austin, TX", "Austin",        "TX"),
        ("Big Spring, TX",         "Big Spring",    "TX"),
        ("Dewey, OK",              "Dewey",         "OK"),
        ("North Dakota — Stampede","Stampede",      "ND"),
        ("Utah",                   "Utah",          "UT"),
        ("SE New Mexico",          "SE New Mexico", "NM"),
        ("Louisiana",              "Louisiana",     "LA"),
        ("Puerto Rico",            "Puerto Rico",   "PR"),
    ]

    margin_map = {r["display"]: r for r in live_margins}

    def _render_card(r, btn_key):
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
        if st.button("Open →", key=btn_key, use_container_width=True):
            st.session_state["view"]    = "detail"
            st.session_state["sel_loc"] = r["display"]
            st.rerun()

    st.markdown("<div class='sec-hdr'>In Construction</div>", unsafe_allow_html=True)
    constr = [r for r in live_margins if r["display"] in IN_CONSTRUCTION]
    cc = st.columns(4)
    for i,r in enumerate(constr):
        with cc[i%4]: _render_card(r, f"btn_con_{i}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<div class='sec-hdr'>Development Locations</div>", unsafe_allow_html=True)
    dev_items = [(dn,sl,st_) for dn,sl,st_ in DEVELOPMENT_ORDER if dn in margin_map]
    dc = st.columns(4)
    for i,(dn,sl,_) in enumerate(dev_items):
        with dc[i%4]: _render_card(margin_map[dn], f"btn_dev_{i}")

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
            mime="text/csv", use_container_width=True)
    with dc2:
        st.dataframe(df_dl[[
            "Location","Light Crude ($/bbl)",
            "Gasoline - Retail","Gasoline - Wholesale",
            "Diesel - Retail","Diesel - Wholesale",
            "Jet Fuel ($/gal)","Bunker ($/gal)","Asphalt ($/gal)",
            "3-2-1 ($/bbl)","Full Yield GRM ($/bbl)","Monthly GRM ($MM)",
        ]], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — LOCATION DETAIL  (two tabs: Today | Forward)
# ══════════════════════════════════════════════════════════════════════════════
def show_detail(live_margins, strip, sheet_prices, live_spot):
    _scroll_top()
    sel = st.session_state.get("sel_loc","")
    r   = next((m for m in live_margins if m["display"]==sel), None)

    # Back nav + header
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
            f"</h3>", unsafe_allow_html=True)

    if not r:
        st.warning("No data for this location.")
        return

    n    = sel
    spec = r.get("specialty", {})
    tp   = r.get("throughput", 30000)

    # Initialise forward tab state
    init_fwd_state(n, sheet_prices, live_spot)

    st.markdown("---")
    tab_today, tab_fwd = st.tabs(["📊 Today", "📈 Forward View"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — TODAY  (read-only, live data only)
    # ══════════════════════════════════════════════════════════════════════════
    with tab_today:

        # ── Headline crack spread cards ───────────────────────────────────────
        sfull = r.get("spread_full")
        pnl_v = fmt_grm(s321, tp)

        h1,h2,h3,h4 = st.columns(4)
        h1.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>3-2-1 Reference Spread</div>
            <div class='mc-value' style='color:{spread_color(s321)};font-size:22px'>
                {"$"+str(s321)+"/bbl" if s321 else "—"}</div>
            <div class='mc-sub'>2 gas + 1 diesel benchmark</div>
        </div>""", unsafe_allow_html=True)
        h2.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Refinery Crack Spread</div>
            <div class='mc-value' style='color:{spread_color(sfull)};font-size:22px'>
                {"$"+str(sfull)+"/bbl" if sfull else "—"}</div>
            <div class='mc-sub'>Full Yield GRM · all products</div>
        </div>""", unsafe_allow_html=True)
        h3.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>GRM / Month</div>
            <div class='mc-value' style='color:#3FB950;font-size:22px'>
                {"$"+str(pnl_v)+"MM" if pnl_v else "—"}</div>
            <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
        </div>""", unsafe_allow_html=True)
        h4.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Annual GRM Run-Rate</div>
            <div class='mc-value' style='color:#3FB950;font-size:22px'>
                {"$"+str(round(pnl_v*12,1))+"MM" if pnl_v else "—"}</div>
            <div class='mc-sub'>{f"at {tp:,} bbl/day"}</div>
        </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Today's prices pill row ───────────────────────────────────────────
        st.markdown("<div class='sec-hdr'>Today's Prices ($/gal)</div>",
                    unsafe_allow_html=True)

        ws_g  = r.get("wholesale_gas",  0) or 0
        ws_d  = r.get("wholesale_diesel",0) or 0
        ret_g = r.get("retail_gas",     0) or 0
        ret_d = r.get("retail_diesel",  0) or 0
        cr_   = r.get("crude_light",    0) or 0
        jet_p = spec.get("jet_gal",    SPECIALTY_DEFAULTS["jet_gal"])
        bnk_p = spec.get("bunker_gal", SPECIALTY_DEFAULTS["bunker_gal"])
        asp_p = spec.get("asphalt_gal",SPECIALTY_DEFAULTS["asphalt_gal"])
        lpg_p = spec.get("lpg_gal",    SPECIALTY_DEFAULTS.get("lpg_gal",0.95))

        # Build price pills as HTML
        pills = [
            ("WTI Crude",   f"${cr_:.2f}/bbl"),
            ("Light Crude", f"${cr_:.2f}/bbl"),
            ("RBOB",        f"${live_spot.get('rbob_gal',0):.3f}/gal"),
            ("ULSD",        f"${live_spot.get('ulsd_gal',0):.3f}/gal"),
            ("Retail Gas",  f"${ret_g:.3f}/gal"),
            ("Whsl Gas",    f"${ws_g:.3f}/gal"),
            ("Retail Diesel",f"${ret_d:.3f}/gal"),
            ("Whsl Diesel", f"${ws_d:.3f}/gal"),
            ("Jet Fuel",    f"${jet_p:.3f}/gal"),
            ("Bunker",      f"${bnk_p:.3f}/gal"),
            ("Asphalt",     f"${asp_p:.3f}/gal"),
            ("LPG/Other",   f"${lpg_p:.3f}/gal"),
        ]
        pill_html = "<div style='display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px'>"
        for label, val in pills:
            pill_html += (
                f"<div class='price-pill'>"
                f"<span class='price-pill-label'>{label}</span>"
                f"<span class='price-pill-value'>{val}</span>"
                f"</div>"
            )
        pill_html += "</div>"
        st.markdown(pill_html, unsafe_allow_html=True)

        spec_date = r.get("spec_updated","—")
        st.caption(
            f"Gas & diesel: AAA daily · Crude: CME settle · "
            f"Jet/Bunker/Asphalt/LPG: Google Sheet (updated {spec_date})"
        )

        st.markdown("<br>", unsafe_allow_html=True)
        left_col, right_col = st.columns([1,1], gap="large")

        # ── GRM build-up waterfall ────────────────────────────────────────────
        with left_col:
            st.markdown("<div class='sec-hdr'>Where Does the Margin Come From?</div>",
                        unsafe_allow_html=True)
            yields = {k: v for k, v in YIELD_DEFAULTS.items()}
            y_g  = yields.get("gasoline",  0.445)
            y_d  = yields.get("ulsd",      0.290)
            y_j  = yields.get("jet",       0.110)
            y_b  = yields.get("bunker",    0.035)
            y_a  = yields.get("asphalt",   0.025)
            y_l  = yields.get("lpg_other", 0.040)
            y_ru = yields.get("refinery_use",0.055)
            _sal = y_g + y_d + y_j + y_b + y_a + y_l

            gc_ = round(ws_g  * y_g * 42, 2)
            dc_ = round(ws_d  * y_d * 42, 2)
            jc_ = round(jet_p * y_j * 42, 2)
            bc_ = round(bnk_p * y_b * 42, 2)
            ac_ = round(asp_p * y_a * 42, 2)
            lc_ = round(lpg_p * y_l * 42, 2)
            total_rev  = gc_+dc_+jc_+bc_+ac_+lc_
            grm_full   = round(total_rev - cr_, 2)

            fig_wf = go.Figure(go.Waterfall(
                orientation="v",
                measure=["absolute","relative","relative","relative",
                         "relative","relative","relative","total"],
                x=["− Crude","+ Gas","+ Diesel","+ Jet",
                   "+ Bunker","+ Asphalt","+ LPG","= GRM"],
                y=[-cr_, gc_, dc_, jc_, bc_, ac_, lc_, 0],
                text=[f"-${cr_:.2f}",f"+${gc_:.2f}",f"+${dc_:.2f}",
                      f"+${jc_:.2f}",f"+${bc_:.2f}",f"+${ac_:.2f}",
                      f"+${lc_:.2f}",f"${grm_full:.2f}"],
                textposition="outside",
                textfont=dict(size=9,color="#E6EDF3"),
                connector=dict(line=dict(color="#30363D",width=1)),
                decreasing=dict(marker_color="#F85149"),
                increasing=dict(marker_color="#3FB950"),
                totals=dict(marker_color="#E8A020"),
            ))
            fig_wf.update_layout(
                paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                yaxis=dict(title="$/bbl",gridcolor="#21262D"),
                xaxis=dict(gridcolor="#21262D",tickangle=-20),
                margin=dict(l=0,r=0,t=8,b=0),height=320,showlegend=False)
            st.plotly_chart(fig_wf, use_container_width=True)

            # Product contribution cards
            st.markdown("<div class='sec-hdr'>Contribution to GRM</div>",
                        unsafe_allow_html=True)
            PRODUCTS = [
                ("Gas",    gc_, y_g, "#4A90D9"),
                ("Diesel", dc_, y_d, "#E8A020"),
                ("Jet",    jc_, y_j, "#5A9E3A"),
                ("Bunker", bc_, y_b, "#8B4FBF"),
                ("Asphalt",ac_, y_a, "#CC7722"),
                ("LPG",    lc_, y_l, "#3AA6B9"),
            ]
            pcols = st.columns(6)
            for col,(name,rev,yld,clr) in zip(pcols,PRODUCTS):
                crude_alloc = round(cr_*(yld/_sal) if _sal>0 else 0,2)
                net         = round(rev-crude_alloc,2)
                pct         = round(net/grm_full*100,1) if grm_full else 0
                nc_clr      = clr if net>=0 else "#F85149"
                col.markdown(f"""<div class='metric-card' style='padding:10px'>
                    <div class='mc-label' style='color:{clr}'>{name}</div>
                    <div style='font-size:16px;font-weight:700;font-family:monospace;
                         color:{nc_clr}'>{"$"+str(net)+"/bbl"}</div>
                    <div style='font-size:10px;color:#8B949E'>{pct:+.1f}% of GRM</div>
                    <div style='font-size:9px;color:#484F58'>{round(yld*100,1)}% bbl</div>
                </div>""", unsafe_allow_html=True)

            st.markdown(
                f"<div style='font-size:10px;color:#484F58;margin-top:4px'>"
                f"{round(_sal*100,1)}% saleable · {round(y_ru*100,1)}% refinery use · "
                f"total revenue ${total_rev:.2f}/bbl · crude ${cr_:.2f}/bbl</div>",
                unsafe_allow_html=True)

        # ── Stress test 2×2 ───────────────────────────────────────────────────
        with right_col:
            st.markdown("<div class='sec-hdr'>Today's Stress Test</div>",
                        unsafe_allow_html=True)
            base = s321 or 0
            crude_b = r.get("crude_light", cr_)
            gas_b   = r.get("wholesale_gas",  ws_g)
            die_b   = r.get("wholesale_diesel",ws_d)

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
                <div style='background:{bg};border-radius:8px;padding:14px;
                     text-align:center;margin-bottom:6px'>
                  <div style='font-size:9px;color:{clr2};letter-spacing:1px;
                       text-transform:uppercase;font-weight:600'>{lbl}</div>
                  <div style='font-size:10px;color:#8B949E;margin:2px 0'>
                      Base 3-2-1: ${base:.2f}</div>
                  <div style='font-size:22px;font-weight:700;
                       font-family:monospace;color:{clr2}'>${val:.2f}</div>
                  <div style='font-size:13px;font-weight:600;color:{clr2}'>
                      {sign} {sign_str(delta)}/bbl</div>
                </div>""", unsafe_allow_html=True)

            # Stacked revenue bar
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='sec-hdr'>Revenue by Product ($/bbl)</div>",
                        unsafe_allow_html=True)
            AREA_BAR = {
                "Gasoline": ("#4A90D9", gc_),
                "Diesel":   ("#E8A020", dc_),
                "Jet":      ("#5A9E3A", jc_),
                "Bunker":   ("#8B4FBF", bc_),
                "Asphalt":  ("#CC7722", ac_),
                "LPG":      ("#3AA6B9", lc_),
            }
            fig_bar = go.Figure()
            for prod,(clr2,val) in AREA_BAR.items():
                fig_bar.add_trace(go.Bar(
                    name=prod, x=["Revenue"], y=[val],
                    marker_color=clr2,
                    text=[f"${val:.1f}"], textposition="inside",
                    textfont=dict(size=9,color="#E6EDF3")))
            fig_bar.add_hline(y=cr_, line_color="#F85149",
                line_width=2, line_dash="solid",
                annotation_text=f"Crude ${cr_:.2f}/bbl",
                annotation_font_color="#F85149",
                annotation_font_size=9)
            fig_bar.update_layout(
                barmode="stack",
                paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                yaxis=dict(title="$/bbl",gridcolor="#21262D"),
                xaxis=dict(gridcolor="#21262D"),
                legend=dict(bgcolor="#161B22",font=dict(size=9),
                            orientation="h",yanchor="bottom",y=1.02),
                margin=dict(l=0,r=0,t=30,b=0),height=220)
            st.plotly_chart(fig_bar, use_container_width=True)

            # Formula reference
            with st.expander("📐 Simplified formula reference", expanded=False):
                fc1,fc2,fc3 = st.columns(3)
                for fcol,lbl,val,formula in [
                    (fc1,"3-2-1",s321,"(2 gas + 1 diesel − 3 WTI) ÷ 3"),
                    (fc2,"2-1-1",r.get("spread_211"),"(1 gas + 1 diesel − 2 WTI) ÷ 2"),
                    (fc3,"5-3-2",r.get("spread_532"),"(3 gas + 2 diesel − 5 WTI) ÷ 5"),
                ]:
                    fcol.markdown(f"""<div class='metric-card'>
                        <div class='mc-label'>{lbl}</div>
                        <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
                            {"$"+str(val)+"/bbl" if val else "—"}</div>
                        <div class='mc-sub' style='font-size:9px'>{formula}</div>
                    </div>""", unsafe_allow_html=True)

        # Per-location CSV download
        st.markdown("---")
        dl_row = {
            "Location":           sel,
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
            "Throughput (bbl/d)": tp,
            "GRM ($MM/mo)":       pnl_v,
            "Specialty Updated":  spec_date,
            "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        st.download_button(
            f"⬇️ Download {short} Today CSV",
            data=pd.DataFrame([dl_row]).to_csv(index=False),
            file_name=f"rogue_{short.replace(' ','_').lower()}_today.csv",
            mime="text/csv")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — FORWARD VIEW  (user inputs, forward curve)
    # ══════════════════════════════════════════════════════════════════════════
    with tab_fwd:
        st.markdown(
            "<div style='background:#2A1F08;border:1px solid #E8A020;"
            "border-radius:6px;padding:8px 14px;font-size:12px;color:#E8A020;"
            "margin-bottom:12px'>📐 <b>FORWARD MODEL</b> — adjust inputs below "
            "to model future margin scenarios. Today's live prices are the default "
            "starting point.</div>",
            unsafe_allow_html=True)

        # ── Input panels ──────────────────────────────────────────────────────
        with st.expander("⚙️ Price & Yield Assumptions", expanded=True):
            if st.button("↺ Reset to Today's Live Prices", key=f"fwd_reset_{n}"):
                spec2 = sheet_prices.get(n, {})
                ulsd2 = live_spot.get("ulsd_gal",3.5) or 3.5
                wti2  = live_spot.get("wti_bbl",80) or 80
                st.session_state.update({
                    f"fwd_wti_{n}":     wti2,
                    f"fwd_rbob_{n}":    live_spot.get("rbob_gal",2.5) or 2.5,
                    f"fwd_ulsd_{n}":    ulsd2,
                    f"fwd_jet_{n}":     spec2.get("jet_gal",   ulsd2*1.05),
                    f"fwd_bunker_{n}":  spec2.get("bunker_gal",ulsd2*0.70),
                    f"fwd_asphalt_{n}": spec2.get("asphalt_gal",ulsd2*0.60),
                    f"fwd_lpg_{n}":     spec2.get("lpg_gal",   round(wti2*0.50/42,3)),
                    f"fwd_dist_{n}":    0.35,
                    f"fwd_fcd_{n}":     0.0,
                    f"fwd_fgd_{n}":     0.0,
                    f"fwd_fdd_{n}":     0.0,
                })
                st.rerun()

            st.markdown("**Market Price Assumptions**")
            p1,p2,p3,p4 = st.columns(4)
            st.session_state[f"fwd_wti_{n}"]    = p1.number_input(
                "WTI ($/bbl)",20.0,200.0,
                float(st.session_state[f"fwd_wti_{n}"]),0.25,"%.2f",key=f"fp_wti_{n}")
            st.session_state[f"fwd_rbob_{n}"]   = p2.number_input(
                "RBOB ($/gal)",0.5,10.0,
                float(st.session_state[f"fwd_rbob_{n}"]),0.01,"%.3f",key=f"fp_rbob_{n}")
            st.session_state[f"fwd_ulsd_{n}"]   = p3.number_input(
                "ULSD ($/gal)",0.5,10.0,
                float(st.session_state[f"fwd_ulsd_{n}"]),0.01,"%.3f",key=f"fp_ulsd_{n}")
            st.session_state[f"fwd_dist_{n}"]   = p4.number_input(
                "Dist Margin ($/gal)",0.0,1.0,
                float(st.session_state[f"fwd_dist_{n}"]),0.01,"%.2f",key=f"fp_dist_{n}")

            st.markdown("**Specialty Product Prices** (used as flat forward assumption)")
            sp1,sp2,sp3,sp4 = st.columns(4)
            st.session_state[f"fwd_jet_{n}"]    = sp1.number_input(
                "Jet Fuel ($/gal)",0.5,15.0,
                float(st.session_state[f"fwd_jet_{n}"]),0.01,"%.3f",key=f"fp_jet_{n}")
            st.session_state[f"fwd_bunker_{n}"] = sp2.number_input(
                "Bunker ($/gal)",0.2,10.0,
                float(st.session_state[f"fwd_bunker_{n}"]),0.01,"%.3f",key=f"fp_bnk_{n}")
            st.session_state[f"fwd_asphalt_{n}"]= sp3.number_input(
                "Asphalt ($/gal)",0.1,8.0,
                float(st.session_state[f"fwd_asphalt_{n}"]),0.01,"%.3f",key=f"fp_asp_{n}")
            st.session_state[f"fwd_lpg_{n}"]    = sp4.number_input(
                "LPG/Other ($/gal)",0.1,5.0,
                float(st.session_state[f"fwd_lpg_{n}"]),0.01,"%.3f",key=f"fp_lpg_{n}")

            st.markdown("**Location Differentials**")
            d1,d2,d3,d4,d5 = st.columns(5)
            st.session_state[f"fwd_fcd_{n}"] = d1.number_input(
                "Crude diff ($/bbl)",-15.0,15.0,
                float(st.session_state[f"fwd_fcd_{n}"]),0.25,"%.2f",key=f"fp_fcd_{n}")
            st.session_state[f"fwd_fgd_{n}"] = d2.number_input(
                "Gas diff ($/gal)",-1.0,1.0,
                float(st.session_state[f"fwd_fgd_{n}"]),0.01,"%.3f",key=f"fp_fgd_{n}")
            st.session_state[f"fwd_fdd_{n}"] = d3.number_input(
                "Diesel diff ($/gal)",-1.0,1.0,
                float(st.session_state[f"fwd_fdd_{n}"]),0.01,"%.3f",key=f"fp_fdd_{n}")
            st.session_state[f"fwd_tp_{n}"]  = int(d4.number_input(
                "Throughput (bbl/day)",0,200000,
                int(st.session_state[f"fwd_tp_{n}"]),1000,key=f"fp_tp_{n}"))
            loc_cfg = next((l for l in LOCATIONS if l["display"]==n),{})
            d5.markdown(
                f"<div style='padding-top:26px;font-size:10px;color:#8B949E'>"
                f"Config crude diff:<br>"
                f"Light {loc_cfg.get('light_diff',0):+.2f} · "
                f"Heavy {loc_cfg.get('heavy_diff',0):+.2f}</div>",
                unsafe_allow_html=True)

            st.markdown("**Yield Configuration (%)**")
            YLBLS = {
                "gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
                "bunker":"Bunker","asphalt":"Asphalt",
                "lpg_other":"LPG/Other","refinery_use":"Ref. Use",
            }
            ycols = st.columns(7)
            total_y = 0.0
            for i,(k,lbl) in enumerate(YLBLS.items()):
                default = round(YIELD_DEFAULTS.get(k,0)*100,1)
                val = ycols[i].number_input(
                    f"{lbl} (%)",0.0,100.0,
                    float(st.session_state.get(f"fwd_y_{k}_{n}",default)),
                    0.5,"%.1f",key=f"fp_y_{k}_{n}")
                st.session_state[f"fwd_y_{k}_{n}"] = val
                total_y += val
            yc = "#3FB950" if total_y<=100 else "#F85149"
            st.markdown(
                f"<span style='color:{yc};font-size:11px'>Total: {total_y:.1f}%</span>",
                unsafe_allow_html=True)

        # ── Compute forward crack with these inputs ───────────────────────────
        fwd_yields = {k: round(st.session_state.get(f"fwd_y_{k}_{n}",
                       YIELD_DEFAULTS.get(k,0)*100)/100, 6)
                      for k in YIELD_DEFAULTS}
        loc_cfg  = next((l for l in LOCATIONS if l["display"]==n), {})
        crude_diff_total = (st.session_state[f"fwd_fcd_{n}"] +
                            loc_cfg.get("light_diff", 0))

        loc_fwd = compute_forward_crack(
            strip       = strip,
            crude_diff  = crude_diff_total,
            gas_diff    = st.session_state[f"fwd_fgd_{n}"] + loc_cfg.get("gas_diff",0),
            diesel_diff = st.session_state[f"fwd_fdd_{n}"] + loc_cfg.get("diesel_diff",0),
            jet_fwd     = st.session_state[f"fwd_jet_{n}"],
            bunker_fwd  = st.session_state[f"fwd_bunker_{n}"],
            asphalt_fwd = st.session_state[f"fwd_asphalt_{n}"],
            lpg_fwd     = st.session_state[f"fwd_lpg_{n}"],
            yields      = fwd_yields,
        )

        if not loc_fwd:
            st.info("Forward curve data not available. Check CME connection.")
        else:
            fwd_ok   = [row for row in loc_fwd if row.get("crack_321")]
            months   = [row["month"]      for row in fwd_ok]
            wti_fwd  = [row["wti"]        for row in fwd_ok]
            rbob_f   = [row.get("rbob",0) for row in fwd_ok]
            ulsd_f   = [row.get("ulsd",0) for row in fwd_ok]
            crack_vals= [row.get("crack_321") for row in fwd_ok]
            full_vals = [row.get("crack_full") for row in fwd_ok]

            y_g2 = fwd_yields.get("gasoline",  0.445)
            y_d2 = fwd_yields.get("ulsd",      0.290)
            y_j2 = fwd_yields.get("jet",       0.110)
            y_b2 = fwd_yields.get("bunker",    0.035)
            y_a2 = fwd_yields.get("asphalt",   0.025)
            y_l2 = fwd_yields.get("lpg_other", 0.040)

            gas_rev = [round((rb or 0)*y_g2*42,2) for rb in rbob_f]
            die_rev = [round((ul or 0)*y_d2*42,2) for ul in ulsd_f]
            jet_rev = [round(st.session_state[f"fwd_jet_{n}"]*y_j2*42,2)]*len(months)
            bnk_rev = [round(st.session_state[f"fwd_bunker_{n}"]*y_b2*42,2)]*len(months)
            asp_rev = [round(st.session_state[f"fwd_asphalt_{n}"]*y_a2*42,2)]*len(months)
            lpg_rev = [round(st.session_state[f"fwd_lpg_{n}"]*y_l2*42,2)]*len(months)

            # ── Area chart ────────────────────────────────────────────────────
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
            for name,vals in [
                ("Gasoline",  gas_rev),
                ("Diesel",    die_rev),
                ("Jet Fuel",  jet_rev),
                ("Bunker",    bnk_rev),
                ("Asphalt",   asp_rev),
                ("LPG/Other", lpg_rev),
            ]:
                fig_fwd.add_trace(go.Scatter(
                    x=months, y=vals, name=name,
                    mode="none", fill="tonexty",
                    fillcolor=AREA_COLORS[name],
                    stackgroup="one", line=dict(width=0)))
            fig_fwd.add_trace(go.Scatter(
                x=months, y=wti_fwd,
                name="Crude Cost ($/bbl)",
                line=dict(color="#FFFFFF",width=2.5), mode="lines"))
            fig_fwd.add_trace(go.Scatter(
                x=months, y=crack_vals,
                name="3-2-1 Crack ($/bbl)",
                line=dict(color="#F85149",width=2,dash="dot"),
                yaxis="y2"))
            fig_fwd.update_layout(
                paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                xaxis=dict(gridcolor="#21262D",tickangle=-45),
                yaxis=dict(title="Product Revenue ($/bbl)",gridcolor="#21262D"),
                yaxis2=dict(
                    title=dict(text="3-2-1 Crack ($/bbl)",
                               font=dict(color="#F85149")),
                    overlaying="y",side="right",showgrid=False,
                    tickfont=dict(color="#F85149")),
                legend=dict(bgcolor="#161B22",font=dict(size=10),
                            orientation="h",yanchor="bottom",y=1.02),
                margin=dict(l=0,r=60,t=30,b=0),height=380,
                hovermode="x unified")
            if months and wti_fwd:
                fig_fwd.add_annotation(
                    x=months[len(months)//2],
                    y=wti_fwd[len(wti_fwd)//2]+5,
                    text="↑ Gap = Margin",
                    showarrow=False,
                    font=dict(color="#FFFFFF",size=10),
                    bgcolor="rgba(0,0,0,0.5)")
            st.plotly_chart(fig_fwd, use_container_width=True)
            st.caption(
                "Stacked areas = product revenue · White line = crude cost · "
                "Gap above white line = refinery margin · "
                "Red dashed (right axis) = 3-2-1 crack spread")

            # ── Forward stress ±20% ───────────────────────────────────────────
            fov = [v for v in full_vals if v is not None]
            fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
            if fov:
                fwd_dn = compute_forward_crack(
                    strip=strip,
                    crude_diff  = crude_diff_total+(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff    = st.session_state[f"fwd_fgd_{n}"]-0.20,
                    diesel_diff = st.session_state[f"fwd_fdd_{n}"]-0.20,
                    jet_fwd     = st.session_state[f"fwd_jet_{n}"]*0.80,
                    bunker_fwd  = st.session_state[f"fwd_bunker_{n}"]*0.80,
                    asphalt_fwd = st.session_state[f"fwd_asphalt_{n}"]*0.80,
                    lpg_fwd     = st.session_state[f"fwd_lpg_{n}"]*0.80,
                    yields      = fwd_yields)
                fwd_up = compute_forward_crack(
                    strip=strip,
                    crude_diff  = crude_diff_total-(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff    = st.session_state[f"fwd_fgd_{n}"]+0.20,
                    diesel_diff = st.session_state[f"fwd_fdd_{n}"]+0.20,
                    jet_fwd     = st.session_state[f"fwd_jet_{n}"]*1.20,
                    bunker_fwd  = st.session_state[f"fwd_bunker_{n}"]*1.20,
                    asphalt_fwd = st.session_state[f"fwd_asphalt_{n}"]*1.20,
                    lpg_fwd     = st.session_state[f"fwd_lpg_{n}"]*1.20,
                    yields      = fwd_yields)
                sdn  = [row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
                sup  = [row.get("crack_full") for row in fwd_up if row.get("crack_full")]
                mdn  = [row["month"] for row in fwd_dn if row.get("crack_full")]
                mup  = [row["month"] for row in fwd_up if row.get("crack_full")]

                st.markdown("<div class='sec-hdr'>Forward GRM Stress Test ±20%</div>",
                            unsafe_allow_html=True)
                fig_st = go.Figure()
                if sdn and len(sdn)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mdn+mdn[::-1], y=sdn+fov[::-1],
                        fill="toself",fillcolor="rgba(248,81,73,0.12)",
                        line=dict(width=0),name="Downside −20%",hoverinfo="skip"))
                if sup and len(sup)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mup+mup[::-1], y=sup+fov[::-1],
                        fill="toself",fillcolor="rgba(63,185,80,0.10)",
                        line=dict(width=0),name="Upside +20%",hoverinfo="skip"))
                fig_st.add_trace(go.Scatter(
                    x=fmo, y=fov,
                    name="Full Yield GRM — Base",
                    line=dict(color="#E8A020",width=2.5),
                    mode="lines+markers",marker=dict(size=5)))
                if sdn:
                    fig_st.add_trace(go.Scatter(
                        x=mdn, y=sdn, name="Downside",
                        line=dict(color="#F85149",width=1.5,dash="dash")))
                if sup:
                    fig_st.add_trace(go.Scatter(
                        x=mup, y=sup, name="Upside",
                        line=dict(color="#3FB950",width=1.5,dash="dash")))
                fig_st.add_hline(y=15,line_dash="dot",line_color="#8B949E",
                    opacity=0.5,
                    annotation_text="~Breakeven $15/bbl",
                    annotation_font_color="#8B949E",
                    annotation_font_size=9)
                fig_st.update_layout(
                    title=dict(text="Full Yield GRM — Forward Stress ±20%",
                               font=dict(color="#E6EDF3",size=13)),
                    paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
                    font_color="#E6EDF3",
                    xaxis=dict(gridcolor="#21262D",tickangle=-45),
                    yaxis=dict(title="Full Yield GRM ($/bbl)",gridcolor="#21262D"),
                    legend=dict(bgcolor="#161B22",font=dict(size=10),
                                orientation="h",yanchor="bottom",y=1.02),
                    margin=dict(l=0,r=0,t=40,b=0),height=320)
                st.plotly_chart(fig_st, use_container_width=True)
                st.caption(
                    "Base = Full Yield GRM at current inputs · "
                    "Red = downside (crude +20%, products −20%) · "
                    "Green = upside (crude −20%, products +20%)")

            # ── Forward GRM table + download ──────────────────────────────────
            fwd_tp = st.session_state[f"fwd_tp_{n}"]
            grm_fwd_list = [round(v*fwd_tp*30/1e6,2) if v else None
                            for v in crack_vals]
            fwd_df = pd.DataFrame({
                "Month":             months,
                "WTI ($/bbl)":       wti_fwd,
                "3-2-1 GRM ($/bbl)": crack_vals,
                "Full Yield ($/bbl)":full_vals,
                f"GRM ($MM/mo @ {fwd_tp//1000}k bbl/d)": grm_fwd_list,
            })
            with st.expander("📋 Forward GRM Table"):
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
    with st.expander("📋 Methodology & Data Sources — Audit Reference",
                     expanded=False):
        st.markdown("""
<div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

### What this tool calculates

**Gross Refining Margin (GRM)** is the difference between the market value of
refined products produced from one barrel of crude oil and the cost of that crude.
It is a *gross* margin — operating costs ($4–8/bbl) are **not deducted**.

GRM = Σ(Product Price × Yield Fraction × 42) − Crude Cost

---

### Two views — Today vs Forward

**Today tab:** 100% live data. Gas & diesel from AAA daily survey, crude from
CME first-month settle, specialty products from Google Sheet (updated weekly).
No user inputs. Every number is the market as of right now.

**Forward tab:** User-driven model. Starts with today's live prices as defaults.
Adjust any assumption to model future margin scenarios. CME forward strip drives
WTI/RBOB/ULSD for months 2–24. Jet/bunker/asphalt/LPG held flat at user input.

---

### Price sources

| Input | Source | Frequency |
|---|---|---|
| Retail gas & diesel | AAA Fuel Gauge (metro daily) | Daily |
| WTI, RBOB, ULSD spot | CME first-month settle | Daily |
| WTI, RBOB, ULSD forward | CME settle strip (local xlsx) | Daily |
| Jet, Bunker, Asphalt, LPG | Google Sheet (per location) | Weekly |
| Federal excise tax | IRS — unchanged since Oct 1993 | Static |
| State excise taxes | FTA + EIA, Jul 2025 | Semiannual |

---

### Price waterfall
```
Retail pump price (AAA)
  − Federal excise:  $0.184/gal gas · $0.244/gal diesel
  − State excise:    varies by state
  = Pre-tax price
  − Distribution:    $0.35/gal default
  = Wholesale / refinery gate price
```

---

### State excise taxes (Jul 2025)

| State | Gas | Diesel |
|---|---|---|
| AK | $0.0895 | $0.0895 |
| TX | $0.200 | $0.200 |
| OK | $0.190 | $0.190 |
| ND | $0.230 | $0.230 |
| UT | $0.385 | $0.385 |
| LA | $0.200 | $0.200 |
| NM | $0.229 | $0.270 |

---

### Full Yield defaults (EIA 2024)

| Product | % | Notes |
|---|---|---|
| Gasoline | 44.5% | EIA 2024 national avg |
| Diesel | 29.0% | EIA 2024 |
| Jet Fuel | 11.0% | Record high 2024 |
| Bunker | 3.5% | Conservative |
| Asphalt | 2.5% | Road oil |
| LPG/Other | 4.0% | Propane, naphtha |
| Refinery Use | 5.5% | Fuel gas + losses |
| **Total** | **100%** | Fully accounted |

Source: EIA Petroleum Supply Monthly 2024 (eia.gov/todayinenergy/detail.php?id=64786)

---

### What this tool does NOT capture
Operating costs ($3–8/bbl) · RIN obligations · Blendstock costs ·
Pipeline tariffs · Carbon costs · Hedging gains/losses

</div>
""", unsafe_allow_html=True)


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
        if st.button("🔄 Refresh All Data", use_container_width=True):
            get_cme.clear()
            get_spot.clear()
            get_lp.clear()
            get_spec.clear()
            get_specialty_sheet.clear()
            # Clear session state except auth
            auth = st.session_state.get("auth")
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            if auth:
                st.session_state["auth"] = auth
            st.rerun()
        st.markdown("---")
        st.caption(
            "**Today tab:** live prices — read only.\n\n"
            "**Forward tab:** adjust inputs to model future scenarios.\n\n"
            "Specialty prices (jet/bunker/asphalt/LPG) updated weekly "
            "via Google Sheet.")

    # Fetch all data
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
    else:
        show_detail(live_margins, strip, sheet_prices, live_spot)

    st.markdown(
        f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
        f"AAA Fuel Gauge · EIA API · CME local xlsx · "
        f"Specialty via Google Sheet · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()






# # app.py — Rogue Refinery Economics v4 — LPG/Other fully wired
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
#     """Scroll the Streamlit app to the top on page transition."""
#     components.html("""
#         <script>
#         (function() {
#             function scrollUp() {
#                 var sel = [
#                     '[data-testid="stAppViewContainer"]',
#                     '[data-testid="stMain"]',
#                     '.main', 'section.main', 'body'
#                 ];
#                 for (var i=0; i<sel.length; i++) {
#                     var el = window.parent.document.querySelector(sel[i]);
#                     if (el) el.scrollTop = 0;
#                 }
#                 window.parent.scrollTo(0,0);
#             }
#             scrollUp();
#             setTimeout(scrollUp, 150);
#             setTimeout(scrollUp, 400);
#         })();
#         </script>
#     """, height=0)


# st.set_page_config(page_title="Rogue Refinery Economics",
#                    page_icon="🏭", layout="wide")

# # st.markdown("""
# # <style>
# # .stApp{background:#0D1117}
# # .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
# #   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
# # .ticker-item{display:flex;flex-direction:column;align-items:center}
# # .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# # .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# # .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# # .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
# #   text-transform:uppercase;margin:10px 0 6px 0}
# # .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
# #   padding:14px 16px;cursor:pointer}
# # .loc-card:hover{border-color:#E8A020}
# # .loc-card-name{font-size:11px;color:#8B949E;text-transform:uppercase;
# #   letter-spacing:1px;margin-bottom:4px}
# # .loc-card-spread{font-size:26px;font-weight:700;font-family:monospace}
# # .loc-card-badge{display:inline-block;font-size:9px;font-weight:600;
# #   letter-spacing:1px;padding:2px 8px;border-radius:4px;margin-top:4px}
# # .loc-card-pnl{font-size:11px;color:#8B949E;margin-top:4px}
# # .badge-strong{background:#0D2A1A;color:#3FB950}
# # .badge-moderate{background:#2A1F08;color:#E8A020}
# # .badge-thin{background:#2A0D0D;color:#F85149}
# # .metric-card{background:#161B22;border:1px solid #30363D;border-radius:8px;
# #   padding:14px;text-align:center}
# # .mc-label{font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px}
# # .mc-value{font-size:20px;font-weight:700;color:#E6EDF3;font-family:monospace}
# # .mc-sub{font-size:10px;color:#8B949E;margin-top:2px}
# # #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# # .block-container{padding-top:0.3rem !important;padding-bottom:0 !important}
# # [data-testid="stAppViewContainer"]>[data-testid="stVerticalBlock"]{padding-top:0 !important}
# # h2{margin-top:0 !important}
# # [data-testid="stSidebar"]{background:#161B22}
# # p,li,span,div,label,.stMarkdown,.stText{color:#E6EDF3 !important}
# # .stDataFrame{color:#E6EDF3 !important}
# # [data-testid="stMetricValue"]{color:#E6EDF3 !important}
# # [data-testid="stMetricLabel"]{color:#8B949E !important}
# # caption,.stCaption{color:#8B949E !important}
# # div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;border-radius:8px}
# # </style>
# # """, unsafe_allow_html=True)

# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:10px 0 6px 0}
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
# .metric-card{background:#161B22;border:1px solid #30363D;border-radius:8px;
#   padding:14px;text-align:center}
# .mc-label{font-size:9px;color:#8B949E;text-transform:uppercase;letter-spacing:1px}
# .mc-value{font-size:20px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .mc-sub{font-size:10px;color:#8B949E;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# .block-container{padding-top:0.3rem !important;padding-bottom:0 !important}
# [data-testid="stAppViewContainer"]>[data-testid="stVerticalBlock"]{padding-top:0 !important}
# h2{margin-top:0 !important}
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
# @st.cache_data(ttl=3600)
# def get_cme():  return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot(): return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():   return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec(): return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     if st.session_state.get("_init"): return
#     live = get_spot()
#     spec = get_spec()
#     ulsd = live.get("ulsd_gal", 3.50) or 3.50
#     wti  = live.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         "wti":       wti,
#         "rbob":      live.get("rbob_gal", 2.50) or 2.50,
#         "ulsd":      ulsd,
#         "jet":       spec.get("jet_gal")     or ulsd * 1.05,
#         "bunker":    spec.get("bunker_gal")  or ulsd * 0.70,
#         "asphalt":   spec.get("asphalt_gal") or ulsd * 0.60,
#         # LPG default: Mont Belvieu propane proxy ≈ WTI × 0.50 ÷ 42
#         "lpg":       round(wti * 0.50 / 42, 3),
#         "dist":      0.35,
#         "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
#         "view":      "portfolio",
#         "sel_loc":   None,
#         "calc_mode": False,
#     })
#     for k, v in YIELD_DEFAULTS.items():
#         st.session_state[f"y_{k}"] = round(v * 100, 1)
#     for loc in LOCATIONS:
#         n = loc["display"]
#         st.session_state[f"lc_{n}"]  = loc.get("light_diff",   0.0)
#         st.session_state[f"lh_{n}"]  = loc.get("heavy_diff",   0.0)
#         st.session_state[f"lcf_{n}"] = loc.get("catfeed_diff", 0.0)
#         st.session_state[f"lg_{n}"]  = loc.get("gas_diff",     0.0)
#         st.session_state[f"ld_{n}"]  = loc.get("diesel_diff",  0.0)
#         st.session_state[f"lj_{n}"]  = 0.0
#         st.session_state[f"tp_{n}"]  = loc.get("throughput",   30000)
#     st.session_state["_init"] = True


# # ── Build margins ──────────────────────────────────────────────────────────────
# def build_margins(lp, loc_overrides=None):
#     """
#     LIVE MODE  (calc_mode=False):
#       Gas/Diesel wholesale from AAA retail → strip taxes & dist margin.
#       Crude/specialty from CME first-month settle / EIA.
#     SCENARIO MODE  (calc_mode=True):
#       All prices from session state — AAA bypassed.
#       RBOB/ULSD used directly as wholesale proxy.
#     Both modes: yields and location diffs from session state.
#     """
#     calc_mode = st.session_state.get("calc_mode", False)
#     spot = {
#         "wti_bbl":  st.session_state["wti"],
#         "rbob_gal": st.session_state["rbob"],
#         "ulsd_gal": st.session_state["ulsd"],
#     }
#     spec = {
#         "jet_gal":     st.session_state["jet"],
#         "bunker_gal":  st.session_state["bunker"],
#         "asphalt_gal": st.session_state["asphalt"],
#         "lpg_gal":     st.session_state["lpg"],      # ← NEW
#     }
#     yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
#               for k, v in YIELD_DEFAULTS.items()}
#     dist = st.session_state["dist"]

#     locs = loc_overrides or []
#     if not locs:
#         for loc in LOCATIONS:
#             n = loc["display"]
#             o = dict(loc)
#             o["light_diff"]   = st.session_state.get(f"lc_{n}", loc.get("light_diff",0))
#             o["heavy_diff"]   = st.session_state.get(f"lh_{n}", loc.get("heavy_diff",0))
#             o["catfeed_diff"] = st.session_state.get(f"lcf_{n}",loc.get("catfeed_diff",0))
#             o["gas_diff"]     = st.session_state.get(f"lg_{n}", loc.get("gas_diff",0))
#             o["diesel_diff"]  = st.session_state.get(f"ld_{n}", loc.get("diesel_diff",0))
#             o["throughput"]   = st.session_state.get(f"tp_{n}", 30000)
#             locs.append(o)

#     if calc_mode:
#         from engine.location_margins import STATE_TAXES, FEDERAL_TAX_GAS, FEDERAL_TAX_DIESEL
#         synthetic_lp = {}
#         for loc in locs:
#             display = loc["display"]
#             state   = loc.get("aaa_state","")
#             rbob    = st.session_state["rbob"] + loc.get("gas_diff",0)
#             ulsd    = st.session_state["ulsd"] + loc.get("diesel_diff",0)
#             st_gas  = STATE_TAXES.get(state,{}).get("gas",    0.30)
#             st_die  = STATE_TAXES.get(state,{}).get("diesel", 0.30)
#             synthetic_lp[display] = {
#                 "regular": round(rbob + FEDERAL_TAX_GAS    + st_gas  + dist, 3),
#                 "diesel":  round(ulsd + FEDERAL_TAX_DIESEL + st_die  + dist, 3),
#                 "source":  "Scenario — NYMEX-derived",
#             }
#         margins = compute_location_margins(
#             locations=locs, spot_prices=spot,
#             location_prices=synthetic_lp,
#             specialty=spec, yields=yields,
#             dist_margin_gal=dist)
#         for r in margins:
#             r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#             r["pnl"]        = fmt_grm(r.get("spread_321"), r["throughput"])
#             r["price_mode"] = "scenario"
#     else:
#         margins = compute_location_margins(
#             locations=locs, spot_prices=spot, location_prices=lp,
#             specialty=spec, yields=yields, dist_margin_gal=dist)
#         for r in margins:
#             r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#             r["pnl"]        = fmt_grm(r.get("spread_321"), r["throughput"])
#             r["price_mode"] = "live"

#     return margins, spot, yields


# # ── Ticker ─────────────────────────────────────────────────────────────────────
# def render_ticker(spot, margins):
#     wti  = spot.get("wti_bbl")
#     rbob = spot.get("rbob_gal")
#     ulsd = spot.get("ulsd_gal")
#     live = get_spot()
#     wti_l = live.get("wti_bbl")
#     delta = ""
#     if wti and wti_l:
#         d = round(wti - wti_l, 2)
#         delta = (f"<span style='color:#3FB950'>▲${d:.2f} vs live</span>"
#                  if d >= 0 else
#                  f"<span style='color:#F85149'>▼${abs(d):.2f} vs live</span>")
#     spreads   = [r["spread_321"] for r in margins if r.get("spread_321")]
#     pavg      = round(sum(spreads)/len(spreads),2) if spreads else None
#     total_pnl = sum(r["pnl"] for r in margins if r.get("pnl"))
#     pc = spread_color(pavg)
#     st.markdown(f"""
#     <div class="ticker-bar">
#       <div class="ticker-item">
#         <span class="ticker-label">WTI Crude</span>
#         <span class="ticker-value">{fmt_bbl(wti)}</span>
#         <span class="ticker-label">{delta}</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">RBOB</span>
#         <span class="ticker-value">{fmt_gal(rbob)}</span>
#         <span class="ticker-label">per gallon</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">ULSD</span>
#         <span class="ticker-value">{fmt_gal(ulsd)}</span>
#         <span class="ticker-label">per gallon</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">RBOB $/bbl</span>
#         <span class="ticker-value">{fmt_bbl(round(rbob*42,2) if rbob else None)}</span>
#         <span class="ticker-label">×42 gal/bbl</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Portfolio Avg 3-2-1</span>
#         <span class="ticker-value" style="color:{pc}">
#           {"$"+str(pavg)+"/bbl" if pavg else "—"}
#         </span>
#         <span class="ticker-label" style="color:{pc}">{spread_label(pavg)}</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Portfolio GRM/mo</span>
#         <span class="ticker-value" style="color:#3FB950">
#           {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#         </span>
#         <span class="ticker-label">before opex</span>
#       </div>
#     </div>""", unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 1 — COMMAND VIEW
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
#     "Edmonton, Alberta":        (53.55,-113.49),
#     "Puerto Rico":              (18.22, -66.59),
# }

# def show_command(margins):
#     valid = [r for r in margins if r.get("spread_321")]
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
#             <div class='mc-sub'>at current throughput · before opex</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map</div>", unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         c = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         map_rows.append({
#             "name": r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat": c[0], "lon": c[1], "spread": s, "color": spread_color(s),
#             "pnl": r.get("pnl"),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"GRM: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
#                 f"<i>Click card below to drill in</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"], mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.90),
#         text=df_m["short"], textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text"))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]], mode="text",
#                 text=[f"${row['spread']:.0f}"],
#                 textfont=dict(size=10, color=row["color"], family="monospace"),
#                 hoverinfo="skip", showlegend=False))
#     fig_m.update_layout(
#         geo=dict(scope="world", showland=True, landcolor="#1C2128",
#                  showocean=True, oceancolor="#0D1117",
#                  showlakes=True, lakecolor="#0D1117",
#                  showcountries=True, countrycolor="#30363D",
#                  showcoastlines=True, coastlinecolor="#30363D",
#                  showframe=False, bgcolor="#0D1117",
#                  center=dict(lat=45, lon=-100), projection_scale=1.4,
#                  lonaxis_range=[-175,-50], lataxis_range=[10,78]),
#         paper_bgcolor="#0D1117", margin=dict(l=0,r=0,t=0,b=0),
#         height=400, showlegend=False)
#     for lbl,clr,ya in [("● STRONG ≥$25","#3FB950",0.13),
#                         ("● MODERATE $12–25","#E8A020",0.09),
#                         ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     # Location cards
#     IN_CONSTRUCTION  = {"Victoria, TX","Duncan, OK"}
#     DEVELOPMENT_ORDER = [
#         ("Alaska — Port Mackenzie","Port Mackenzie","AK"),
#         ("Greenport — Austin, TX", "Austin",        "TX"),
#         ("Big Spring, TX",         "Big Spring",    "TX"),
#         ("Dewey, OK",              "Dewey",         "OK"),
#         ("North Dakota — Stampede","Stampede",      "ND"),
#         ("Utah",                   "Utah",          "UT"),
#         ("SE New Mexico",          "SE New Mexico", "NM"),
#         ("Louisiana",              "Louisiana",     "LA"),
#         ("Edmonton, Alberta",      "Edmonton",      "CA"),
#         ("Puerto Rico",            "Puerto Rico",   "PR"),
#     ]

#     def _render_card(r, btn_key):
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
#             <div class='loc-card-pnl'>{pnl_s} · {r.get("source","").split("—")[-1][:12]}</div>
#         </div>""", unsafe_allow_html=True)
#         if st.button("Open →", key=btn_key, use_container_width=True):
#             st.session_state["view"]    = "detail"
#             st.session_state["sel_loc"] = r["display"]
#             st.rerun()

#     margin_map = {r["display"]: r for r in margins}

#     st.markdown("<div class='sec-hdr'>In Construction</div>", unsafe_allow_html=True)
#     constr = [r for r in margins if r["display"] in IN_CONSTRUCTION]
#     cc = st.columns(4)
#     for i,r in enumerate(constr):
#         with cc[i%4]: _render_card(r, f"btn_con_{i}")

#     st.markdown("<br>", unsafe_allow_html=True)
#     st.markdown("<div class='sec-hdr'>Development Locations</div>", unsafe_allow_html=True)
#     dev_items = [(dn,sl,st_) for dn,sl,st_ in DEVELOPMENT_ORDER if dn in margin_map]
#     dc = st.columns(4)
#     for i,(dn,sl,st_) in enumerate(dev_items):
#         with dc[i%4]: _render_card(margin_map[dn], f"btn_dev_{i}")

#     # Portfolio download
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
#                 unsafe_allow_html=True)
#     jet_p  = st.session_state.get("jet",     4.07)
#     bnk_p  = st.session_state.get("bunker",  2.52)
#     asp_p  = st.session_state.get("asphalt", 2.16)
#     lpg_p  = st.session_state.get("lpg",     0.95)
#     dl_rows = []
#     for r in margins:
#         n  = r["display"]
#         tp = r.get("throughput",30000)
#         gm = fmt_grm(r.get("spread_321"), tp)
#         dl_rows.append({
#             "Location":                  n,
#             "Price Source":              r.get("source","—"),
#             "Throughput (bbl/day)":      tp,
#             "Light Crude ($/bbl)":       r.get("crude_light"),
#             "Heavy Crude ($/bbl)":       r.get("crude_heavy"),
#             "Cat Feed / HGO ($/bbl)":    r.get("crude_catfeed"),
#             "Gasoline - Retail":         r.get("retail_gas"),
#             "Gasoline - Federal Tax":    r.get("federal_tax_gas"),
#             "Gasoline - State Tax":      r.get("state_tax_gas"),
#             "Gasoline - Pre-tax":        r.get("pretax_gas"),
#             "Gasoline - Dist Margin":    r.get("dist_margin"),
#             "Gasoline - Wholesale":      r.get("wholesale_gas"),
#             "Diesel - Retail":           r.get("retail_diesel"),
#             "Diesel - Pre-tax":          r.get("pretax_diesel"),
#             "Diesel - Wholesale":        r.get("wholesale_diesel"),
#             "Jet Fuel ($/gal)":          jet_p,
#             "Bunker Fuel ($/gal)":       bnk_p,
#             "Asphalt ($/gal)":           asp_p,
#             "LPG / Other ($/gal)":       lpg_p,
#             "3-2-1 Spread ($/bbl)":      r.get("spread_321"),
#             "2-1-1 Spread ($/bbl)":      r.get("spread_211"),
#             "5-3-2 Spread ($/bbl)":      r.get("spread_532"),
#             "Full Yield GRM ($/bbl)":    r.get("spread_full"),
#             "Monthly GRM ($MM)":         gm,
#             "Annual GRM ($MM)":          round(gm*12,2) if gm else None,
#             "As Of":                     datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })
#     df_dl = pd.DataFrame(dl_rows)
#     dc1,dc2 = st.columns([1,2])
#     with dc1:
#         st.download_button("⬇️ Download All Locations CSV",
#             data=df_dl.to_csv(index=False),
#             file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
#             mime="text/csv", use_container_width=True)
#     with dc2:
#         st.dataframe(df_dl[[
#             "Location","Light Crude ($/bbl)","Heavy Crude ($/bbl)",
#             "Gasoline - Retail","Gasoline - Wholesale",
#             "Diesel - Retail","Diesel - Wholesale",
#             "Jet Fuel ($/gal)","Bunker Fuel ($/gal)",
#             "Asphalt ($/gal)","LPG / Other ($/gal)",
#             "3-2-1 Spread ($/bbl)","Full Yield GRM ($/bbl)","Monthly GRM ($MM)",
#         ]], use_container_width=True, hide_index=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(margins, strip, yields, lp):
#     _scroll_top()
#     sel = st.session_state.get("sel_loc")
#     fresh_margins, spot_fresh, yields_fresh = build_margins(lp)
#     margins = fresh_margins
#     yields  = yields_fresh
#     r = next((m for m in margins if m["display"]==sel), None)

#     bc,tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321_hdr = r.get("spread_321") if r else None
#         clr_hdr  = spread_color(s321_hdr)
#         short_hdr= sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short_hdr} &nbsp;"
#             f"<span style='color:{clr_hdr};font-family:monospace'>"
#             f"{'$'+str(s321_hdr)+'/bbl' if s321_hdr else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr_hdr}'>{spread_label(s321_hdr)}</span>"
#             f"</h3>", unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     # Pre-pull n for keying widgets
#     n     = sel
#     short = short_hdr
#     st.markdown("---")

#     # ─── PANEL A ──────────────────────────────────────────────────────────────
#     with st.expander("📊 Current Margin Snapshot", expanded=True):
#         tp   = r.get("throughput", 30000)

#         # Mode toggle
#         mc1,mc2 = st.columns([3,1])
#         with mc2:
#             calc_mode = st.toggle(
#                 "Scenario Mode",
#                 value=st.session_state.get("calc_mode",False),
#                 key="mode_toggle",
#                 help=("OFF = Live Market: AAA daily prices stripped to wholesale. "
#                       "ON = Scenario: all prices from calculator inputs below."))
#             if calc_mode != st.session_state.get("calc_mode",False):
#                 st.session_state["calc_mode"] = calc_mode
#                 st.rerun()
#         with mc1:
#             if st.session_state.get("calc_mode",False):
#                 st.markdown(
#                     "<div style='background:#2A1F08;border:1px solid #E8A020;"
#                     "border-radius:6px;padding:8px 14px;font-size:12px;color:#E8A020'>"
#                     "⚡ <b>SCENARIO MODE</b> — prices from calculator · not live market data"
#                     "</div>", unsafe_allow_html=True)
#             else:
#                 st.markdown(
#                     "<div style='background:#0D2A1A;border:1px solid #3FB950;"
#                     "border-radius:6px;padding:8px 14px;font-size:12px;color:#3FB950'>"
#                     "✅ <b>LIVE MARKET</b> — gas & diesel from AAA daily · crude from CME · specialty from EIA"
#                     "</div>", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#         # Rebuild with current mode
#         fm2,_,yields2 = build_margins(lp)
#         r2     = next((m for m in fm2 if m["display"]==sel), r)
#         s321   = r2.get("spread_321")
#         sfull  = r2.get("spread_full")
#         s211   = r2.get("spread_211")
#         s532   = r2.get("spread_532")
#         yields = yields2

#         # Prices for contribution calc
#         ws_g   = r2.get("wholesale_gas",   0.0) or 0
#         ws_d   = r2.get("wholesale_diesel", 0.0) or 0
#         jet_p  = st.session_state.get("jet",     4.07)
#         bnk_p  = st.session_state.get("bunker",  2.52)
#         asp_p  = st.session_state.get("asphalt", 2.16)
#         lpg_p  = st.session_state.get("lpg",     0.95)
#         cr_    = r2.get("crude_light", 0.0) or 0

#         y_g    = yields.get("gasoline",    0.445)
#         y_d    = yields.get("ulsd",        0.290)
#         y_j    = yields.get("jet",         0.110)
#         y_b    = yields.get("bunker",      0.035)
#         y_a    = yields.get("asphalt",     0.025)
#         y_l    = yields.get("lpg_other",   0.040)  # ← NEW
#         y_ru   = yields.get("refinery_use",0.055)

#         _sal   = y_g + y_d + y_j + y_b + y_a + y_l
#         _total = _sal + y_ru
#         _check = round(1.0 - _total, 3)   # should be ~0 or tiny rounding

#         gc_ = round(ws_g  * y_g * 42, 2)
#         dc_ = round(ws_d  * y_d * 42, 2)
#         jc_ = round(jet_p * y_j * 42, 2)
#         bc_ = round(bnk_p * y_b * 42, 2)
#         ac_ = round(asp_p * y_a * 42, 2)
#         lc_ = round(lpg_p * y_l * 42, 2)  # ← NEW
#         total_rev  = gc_ + dc_ + jc_ + bc_ + ac_ + lc_
#         grm_full   = round(total_rev - cr_, 2)
#         pnl_v      = fmt_grm(s321, tp)

#         # Row 1: Headline cards
#         h1,h2,h3,h4 = st.columns(4)
#         h1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Refinery Crack Spread</div>
#             <div class='mc-value' style='color:{spread_color(grm_full)};font-size:22px'>
#                 {"$"+str(grm_full)+"/bbl" if grm_full else "—"}</div>
#             <div class='mc-sub'>Full Yield GRM · {round(_sal*100,1)}% saleable bbl</div>
#         </div>""", unsafe_allow_html=True)
#         h2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>3-2-1 Reference Spread</div>
#             <div class='mc-value' style='color:{spread_color(s321)};font-size:22px'>
#                 {"$"+str(s321)+"/bbl" if s321 else "—"}</div>
#             <div class='mc-sub'>100% bbl · 2 gas + 1 diesel benchmark</div>
#         </div>""", unsafe_allow_html=True)
#         h3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>GRM / Month</div>
#             <div class='mc-value' style='color:#3FB950;font-size:22px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}</div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day · Full Yield basis"}</div>
#         </div>""", unsafe_allow_html=True)
#         h4.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Annual GRM Run-Rate</div>
#             <div class='mc-value' style='color:#3FB950;font-size:22px'>
#                 {"$"+str(round(pnl_v*12,1))+"MM" if pnl_v else "—"}</div>
#             <div class='mc-sub'>{f"at {tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)

#         # Row 2: Product contribution cards (6 products)
#         st.markdown(
#             "<div class='sec-hdr'>Where Does the Margin Come From? — "
#             "Product Contribution to Full Yield GRM</div>",
#             unsafe_allow_html=True)

#         PRODUCTS = [
#             ("Gasoline", gc_, y_g, "#4A90D9"),
#             ("Diesel",   dc_, y_d, "#E8A020"),
#             ("Jet Fuel", jc_, y_j, "#5A9E3A"),
#             ("Bunker",   bc_, y_b, "#8B4FBF"),
#             ("Asphalt",  ac_, y_a, "#CC7722"),
#             ("LPG/Other",lc_, y_l, "#3AA6B9"),  # ← NEW
#         ]

#         pcols = st.columns(6)
#         for col,(name,rev,yld,clr) in zip(pcols, PRODUCTS):
#             crude_alloc = round(cr_ * (yld/_sal) if _sal>0 else 0, 2)
#             net_contrib = round(rev - crude_alloc, 2)
#             pct_grm     = round(net_contrib/grm_full*100,1) if grm_full else 0
#             pct_bbl     = round(yld*100,1)
#             nc_clr      = clr if net_contrib >= 0 else "#F85149"
#             col.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label' style='color:{clr}'>{name}</div>
#                 <div style='font-size:17px;font-weight:700;font-family:monospace;
#                      color:{nc_clr}'>{"$"+str(net_contrib)+"/bbl"}</div>
#                 <div style='font-size:11px;color:#8B949E;margin-top:2px'>
#                     {pct_grm:+.1f}% of GRM</div>
#                 <div style='font-size:10px;color:#484F58;margin-top:1px'>
#                     {pct_bbl:.1f}% bbl · ${rev:.2f} rev</div>
#             </div>""", unsafe_allow_html=True)

#         # Barrel utilisation summary — now 100%
#         st.markdown(
#             f"<div style='font-size:10px;color:#484F58;margin-top:6px'>"
#             f"Barrel: {round(_sal*100,1)}% saleable · "
#             f"{round(y_ru*100,1)}% refinery fuel use · "
#             f"total = {round(_total*100,1)}% · "
#             f"crude cost ${cr_:.2f}/bbl · product revenue ${total_rev:.2f}/bbl"
#             f"</div>", unsafe_allow_html=True)

#         # Formula reference (collapsed)
#         with st.expander("📐 Formula reference — 3-2-1 · 2-1-1 · 5-3-2", expanded=False):
#             fc1,fc2,fc3 = st.columns(3)
#             for fcol,lbl,val,formula in [
#                 (fc1,"3-2-1",s321,"(2 gas + 1 diesel − 3 WTI) ÷ 3"),
#                 (fc2,"2-1-1",s211,"(1 gas + 1 diesel − 2 WTI) ÷ 2"),
#                 (fc3,"5-3-2",s532,"(3 gas + 2 diesel − 5 WTI) ÷ 5"),
#             ]:
#                 fcol.markdown(f"""<div class='metric-card'>
#                     <div class='mc-label'>{lbl}</div>
#                     <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                         {"$"+str(val)+"/bbl" if val else "—"}</div>
#                     <div class='mc-sub' style='font-size:9px'>{formula}</div>
#                 </div>""", unsafe_allow_html=True)
#             st.caption(
#                 "Simplified formulas assume 100% of barrel becomes gas or diesel "
#                 "at NYMEX prices. Ignore jet, bunker, asphalt, LPG, and refinery losses.")

#         st.markdown("<br>", unsafe_allow_html=True)
#         wa_col,wi_col = st.columns([1,1], gap="large")

#         # Waterfall — full barrel build-up incl LPG
#         with wa_col:
#             st.markdown("<div class='sec-hdr'>GRM Build-Up ($/bbl)</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 fig_wf = go.Figure(go.Waterfall(
#                     orientation="v",
#                     measure=["absolute","relative","relative","relative",
#                              "relative","relative","relative","total"],
#                     x=["− Crude","+ Gas","+ Diesel","+ Jet",
#                        "+ Bunker","+ Asphalt","+ LPG","= GRM"],
#                     y=[-cr_, gc_, dc_, jc_, bc_, ac_, lc_, 0],
#                     text=[f"-${cr_:.2f}",f"+${gc_:.2f}",f"+${dc_:.2f}",
#                           f"+${jc_:.2f}",f"+${bc_:.2f}",f"+${ac_:.2f}",
#                           f"+${lc_:.2f}",f"${grm_full:.2f}"],
#                     textposition="outside",
#                     textfont=dict(size=9,color="#E6EDF3"),
#                     connector=dict(line=dict(color="#30363D",width=1)),
#                     decreasing=dict(marker_color="#F85149"),
#                     increasing=dict(marker_color="#3FB950"),
#                     totals=dict(marker_color="#E8A020"),
#                 ))
#                 fig_wf.update_layout(
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D",tickangle=-20),
#                     margin=dict(l=0,r=0,t=8,b=0), height=300, showlegend=False)
#                 st.plotly_chart(fig_wf, use_container_width=True)
#                 st.caption("Full Yield model · all 6 saleable products · green = adds to GRM · red = crude cost")

#         # What-if 2×2
#         with wi_col:
#             st.markdown("<div class='sec-hdr'>What-If vs Base</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 base    = s321 or 0
#                 crude_b = r2["crude_light"]
#                 gas_b   = r2["wholesale_gas"]
#                 die_b   = r2.get("wholesale_diesel", gas_b)
#                 scenarios = [
#                     ("Crude +25%",    crude_b*1.25, gas_b,      die_b),
#                     ("Products +25%", crude_b,      gas_b*1.25, die_b*1.25),
#                     ("Crude −25%",    crude_b*0.75, gas_b,      die_b),
#                     ("Products −25%", crude_b,      gas_b*0.75, die_b*0.75),
#                 ]
#                 r1c1,r1c2 = st.columns(2)
#                 r2c1,r2c2 = st.columns(2)
#                 for col,(lbl,c,g,d) in zip([r1c1,r1c2,r2c1,r2c2], scenarios):
#                     val   = round(_c321(c,g,d),2)
#                     delta = round(val-base,2)
#                     is_up = delta >= 0
#                     bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                     clr2  = "#3FB950" if is_up else "#F85149"
#                     sign  = "▲" if is_up else "▼"
#                     col.markdown(f"""
#                     <div style='background:{bg};border-radius:8px;padding:14px;
#                          text-align:center;margin-bottom:4px'>
#                       <div style='font-size:9px;color:{clr2};letter-spacing:1px;
#                            text-transform:uppercase;font-weight:600'>{lbl}</div>
#                       <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                           Base: ${base:.2f}</div>
#                       <div style='font-size:20px;font-weight:700;
#                            font-family:monospace;color:{clr2}'>${val:.2f}</div>
#                       <div style='font-size:13px;font-weight:600;color:{clr2}'>
#                           {sign} {sign_str(delta)}/bbl</div>
#                     </div>""", unsafe_allow_html=True)

#                 # Stacked product bar
#                 st.markdown("<br>", unsafe_allow_html=True)
#                 st.markdown("<div class='sec-hdr'>Revenue by Product ($/bbl)</div>",
#                             unsafe_allow_html=True)
#                 AREA_BAR = {
#                     "Gasoline":  ("#4A90D9", gc_),
#                     "Diesel":    ("#E8A020", dc_),
#                     "Jet Fuel":  ("#5A9E3A", jc_),
#                     "Bunker":    ("#8B4FBF", bc_),
#                     "Asphalt":   ("#CC7722", ac_),
#                     "LPG/Other": ("#3AA6B9", lc_),
#                 }
#                 fig_bar = go.Figure()
#                 for prod,(clr2,val) in AREA_BAR.items():
#                     fig_bar.add_trace(go.Bar(
#                         name=prod, x=["Product Revenue"],
#                         y=[val], marker_color=clr2,
#                         text=[f"${val:.1f}"], textposition="inside",
#                         textfont=dict(size=9,color="#E6EDF3")))
#                 fig_bar.add_hline(y=cr_, line_color="#F85149",
#                     line_width=2, line_dash="solid",
#                     annotation_text=f"Crude ${cr_:.2f}/bbl",
#                     annotation_font_color="#F85149",
#                     annotation_font_size=9)
#                 fig_bar.update_layout(
#                     barmode="stack",
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=9),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=30,b=0), height=200)
#                 st.plotly_chart(fig_bar, use_container_width=True)

#     # ─── PANEL B: Forward View ─────────────────────────────────────────────────
#     with st.expander("📈 Forward Crack Spread", expanded=True):
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#         lc_d = st.session_state.get(f"lc_{n}", loc_cfg.get("light_diff",0))
#         lg_d = st.session_state.get(f"lg_{n}", loc_cfg.get("gas_diff",0))
#         ld_d = st.session_state.get(f"ld_{n}", loc_cfg.get("diesel_diff",0))
#         fcd  = st.session_state.get("fcd",0)
#         fgd  = st.session_state.get("fgd",0)
#         fdd  = st.session_state.get("fdd",0)

#         fi1,fi2,fi3,fi4 = st.columns(4)
#         jet_fwd = fi1.number_input("Jet fwd ($/gal)",0.5,15.0,
#             float(st.session_state.get("jet",4.07)),0.01,"%.3f",key="fwd_jet_d")
#         bnk_fwd = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
#             float(st.session_state.get("bunker",2.52)),0.01,"%.3f",key="fwd_bnk_d")
#         asp_fwd = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
#             float(st.session_state.get("asphalt",2.16)),0.01,"%.3f",key="fwd_asp_d")
#         lpg_fwd = fi4.number_input("LPG/Other fwd ($/gal)",0.1,5.0,
#             float(st.session_state.get("lpg",0.95)),0.01,"%.3f",key="fwd_lpg_d")

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = fcd+lc_d,
#             gas_diff    = fgd+lg_d,
#             diesel_diff = fdd+ld_d,
#             jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
#             asphalt_fwd=asp_fwd,
#             lpg_fwd=lpg_fwd,          # ← NEW
#             yields=yields)

#         if loc_fwd:
#             fwd_ok  = [row for row in loc_fwd if row.get("crack_321")]
#             months  = [row["month"]      for row in fwd_ok]
#             wti_fwd = [row["wti"]        for row in fwd_ok]
#             rbob_f  = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]

#             gas_rev = [round((rb or 0)*y_g*42,2) for rb in rbob_f]
#             die_rev = [round((ul or 0)*y_d*42,2) for ul in ulsd_f]
#             jet_rev = [round(jet_fwd*y_j*42,2)] * len(months)
#             bnk_rev = [round(bnk_fwd*y_b*42,2)] * len(months)
#             asp_rev = [round(asp_fwd*y_a*42,2)] * len(months)
#             lpg_rev = [round(lpg_fwd*y_l*42,2)] * len(months)  # ← NEW

#             AREA_COLORS = {
#                 "Gasoline":  "rgba(74,144,217,0.75)",
#                 "Diesel":    "rgba(232,160,32,0.75)",
#                 "Jet Fuel":  "rgba(90,158,58,0.75)",
#                 "Bunker":    "rgba(139,79,191,0.75)",
#                 "Asphalt":   "rgba(204,119,34,0.75)",
#                 "LPG/Other": "rgba(58,166,185,0.75)",  # ← NEW
#             }

#             fig_fwd = go.Figure()
#             for name,vals in [
#                 ("Gasoline",  gas_rev),
#                 ("Diesel",    die_rev),
#                 ("Jet Fuel",  jet_rev),
#                 ("Bunker",    bnk_rev),
#                 ("Asphalt",   asp_rev),
#                 ("LPG/Other", lpg_rev),  # ← NEW
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one", line=dict(width=0)))
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost (WTI+diff)",
#                 line=dict(color="#FFFFFF",width=2.5), mode="lines",
#                 hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>"))
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149",width=2,dash="dot"),
#                 yaxis="y2",
#                 hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>"))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D",tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="Crack Spread ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y", side="right", showgrid=False,
#                     tickfont=dict(color="#F85149")),
#                 legend=dict(bgcolor="#161B22",bordercolor="#30363D",
#                             font=dict(size=10),orientation="h",
#                             yanchor="bottom",y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified")
#             if months and wti_fwd:
#                 fig_fwd.add_annotation(
#                     x=months[len(months)//2],
#                     y=wti_fwd[len(wti_fwd)//2]+5,
#                     text="↑ Gap above line = Margin",
#                     showarrow=False,font=dict(color="#FFFFFF",size=10),
#                     bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = total product revenue by type (6 products incl. LPG/Other). "
#                 "White line = crude cost. Gap above white line = implied refinery margin. "
#                 "Red dashed line (right axis) = 3-2-1 crack spread.")

#             # Full Yield stress ±20%
#             full_vals = [row.get("crack_full") for row in fwd_ok]
#             if any(v for v in full_vals):
#                 fwd_up = compute_forward_crack(
#                     strip=strip,
#                     crude_diff  = fcd+lc_d+(wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff=fgd+lg_d-0.20, diesel_diff=fdd+ld_d-0.20,
#                     jet_fwd=jet_fwd*0.80, bunker_fwd=bnk_fwd*0.80,
#                     asphalt_fwd=asp_fwd*0.80, lpg_fwd=lpg_fwd*0.80, yields=yields)
#                 fwd_dn = compute_forward_crack(
#                     strip=strip,
#                     crude_diff  = fcd+lc_d-(wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff=fgd+lg_d+0.20, diesel_diff=fdd+ld_d+0.20,
#                     jet_fwd=jet_fwd*1.20, bunker_fwd=bnk_fwd*1.20,
#                     asphalt_fwd=asp_fwd*1.20, lpg_fwd=lpg_fwd*1.20, yields=yields)
#                 sup = [row.get("crack_full") for row in fwd_up if row.get("crack_full")]
#                 sdn = [row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
#                 mup = [row["month"] for row in fwd_up if row.get("crack_full")]
#                 mdn = [row["month"] for row in fwd_dn if row.get("crack_full")]
#                 fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
#                 fov = [v for v in full_vals if v is not None]

#                 fig_st = go.Figure()
#                 if sup and len(sup)==len(fov):
#                     fig_st.add_trace(go.Scatter(
#                         x=mup+mup[::-1], y=sup+fov[::-1],
#                         fill="toself", fillcolor="rgba(248,81,73,0.12)",
#                         line=dict(width=0), name="Downside −20%", hoverinfo="skip"))
#                 if sdn and len(sdn)==len(fov):
#                     fig_st.add_trace(go.Scatter(
#                         x=mdn+mdn[::-1], y=sdn+fov[::-1],
#                         fill="toself", fillcolor="rgba(63,185,80,0.10)",
#                         line=dict(width=0), name="Upside +20%", hoverinfo="skip"))
#                 fig_st.add_trace(go.Scatter(
#                     x=fmo, y=fov, name="Full Yield GRM — Base",
#                     line=dict(color="#E8A020",width=2.5),
#                     mode="lines+markers", marker=dict(size=5)))
#                 if sup:
#                     fig_st.add_trace(go.Scatter(
#                         x=mup, y=sup, name="Downside boundary",
#                         line=dict(color="#F85149",width=1.5,dash="dash")))
#                 if sdn:
#                     fig_st.add_trace(go.Scatter(
#                         x=mdn, y=sdn, name="Upside boundary",
#                         line=dict(color="#3FB950",width=1.5,dash="dash")))
#                 fig_st.add_hline(y=15,line_dash="dot",line_color="#8B949E",
#                     opacity=0.5,annotation_text="~Breakeven $15/bbl",
#                     annotation_font_color="#8B949E",annotation_font_size=9)
#                 fig_st.update_layout(
#                     title=dict(text="Full Yield GRM — Forward Stress ±20%",
#                                font=dict(color="#E6EDF3",size=13)),
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     xaxis=dict(gridcolor="#21262D",tickangle=-45),
#                     yaxis=dict(title="Full Yield GRM ($/bbl)",gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=10),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=40,b=0),height=320)
#                 st.plotly_chart(fig_st, use_container_width=True)
#                 st.caption(
#                     "Base = Full Yield GRM at current inputs. "
#                     "Red band = downside (crude +20%, products −20%). "
#                     "Green band = upside (crude −20%, products +20%).")

#             # Forward GRM table
#             if tp and crack_vals:
#                 grm_fwd_list = [round(v*tp*30/1e6,2) if v else None for v in crack_vals]
#                 fwd_df = pd.DataFrame({
#                     "Month":             months,
#                     "WTI ($/bbl)":       wti_fwd,
#                     "3-2-1 GRM ($/bbl)": crack_vals,
#                     "Full Yield ($/bbl)":full_vals,
#                     "GRM ($MM/mo)":      grm_fwd_list,
#                 })
#                 with st.expander("Forward GRM Table"):
#                     st.dataframe(fwd_df, use_container_width=True, hide_index=True)
#         else:
#             st.info("Forward curve data not available. Check CME connection.")

#     # ─── PANEL C: Full Calculator ──────────────────────────────────────────────
#     with st.expander("⚙️ Full Calculator — Scenario Inputs", expanded=False):
#         mode_now = st.session_state.get("calc_mode",False)
#         if mode_now:
#             st.info("**Scenario Mode ON** — cards and forward curve update from these inputs.")
#         else:
#             st.warning(
#                 "**Live Market Mode ON** — inputs affect forward curve only. "
#                 "Toggle Scenario Mode above to use for current month cards.")

#         st.markdown("<div class='sec-hdr'>Market Prices</div>", unsafe_allow_html=True)
#         mp1,mp2,mp3,mp4 = st.columns(4)
#         if st.button("↺ Reset to Live", key="reset_live"):
#             live2 = get_spot(); spec2 = get_spec()
#             ul2   = live2.get("ulsd_gal",3.5) or 3.5
#             wti2  = live2.get("wti_bbl",80)   or 80
#             st.session_state.update({
#                 "wti":    wti2, "rbob": live2.get("rbob_gal",2.5) or 2.5,
#                 "ulsd":   ul2,
#                 "jet":    spec2.get("jet_gal")    or ul2*1.05,
#                 "bunker": spec2.get("bunker_gal") or ul2*0.70,
#                 "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
#                 "lpg":    round(wti2*0.50/42,3),
#             })
#             st.rerun()
#         st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
#             float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
#         st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
#             float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
#         st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
#             float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
#         st.session_state["dist"]   = mp4.number_input("Dist Margin ($/gal)",0.0,1.0,
#             float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

#         sp1,sp2,sp3,sp4 = st.columns(4)
#         st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
#             float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
#         st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
#             float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
#         st.session_state["asphalt"]= sp3.number_input("Asphalt ($/gal)",0.1,8.0,
#             float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")
#         st.session_state["lpg"]    = sp4.number_input("LPG/Other ($/gal)",0.1,5.0,
#             float(st.session_state.get("lpg",0.95)),0.01,"%.3f",key=f"c_lpg_{n}")
#         st.caption("💡 LPG/Other = propane, butane, petrochemical naphtha — Mont Belvieu proxy default. "
#                    "Cat Feed is a crude cost differential (see below), not a product price.")

#         st.markdown("<div class='sec-hdr'>Crude Differentials ($/bbl)</div>",
#                     unsafe_allow_html=True)
#         d1,d2,d3 = st.columns(3)
#         st.session_state[f"lc_{n}"]  = d1.number_input("Light Crude diff",-20.0,20.0,
#             float(st.session_state.get(f"lc_{n}",0)),0.25,"%.2f",key=f"c_lc_{n}")
#         st.session_state[f"lh_{n}"]  = d2.number_input("Heavy Crude diff",-20.0,20.0,
#             float(st.session_state.get(f"lh_{n}",0)),0.25,"%.2f",key=f"c_lh_{n}")
#         st.session_state[f"lcf_{n}"] = d3.number_input("Cat Feed diff",-20.0,20.0,
#             float(st.session_state.get(f"lcf_{n}",0)),0.25,"%.2f",key=f"c_lcf_{n}")

#         st.markdown("<div class='sec-hdr'>Product Differentials ($/gal)</div>",
#                     unsafe_allow_html=True)
#         pd1,pd2,pd3 = st.columns(3)
#         st.session_state[f"lg_{n}"]  = pd1.number_input("Gasoline diff",-1.0,1.0,
#             float(st.session_state.get(f"lg_{n}",0)),0.01,"%.3f",key=f"c_lg_{n}")
#         st.session_state[f"ld_{n}"]  = pd2.number_input("Diesel diff",-1.0,1.0,
#             float(st.session_state.get(f"ld_{n}",0)),0.01,"%.3f",key=f"c_ld_{n}")
#         st.session_state[f"lj_{n}"]  = pd3.number_input("Jet diff",-1.0,1.0,
#             float(st.session_state.get(f"lj_{n}",0)),0.01,"%.3f",key=f"c_lj_{n}")

#         st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
#                     unsafe_allow_html=True)
#         YLBLS = {
#             "gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#             "bunker":"Bunker","asphalt":"Asphalt",
#             "lpg_other":"LPG/Other","refinery_use":"Ref. Use",
#         }
#         ycols = st.columns(7)
#         total_y = 0.0
#         for i,(k,lbl) in enumerate(YLBLS.items()):
#             default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#             val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
#                 float(st.session_state.get(f"y_{k}",default)),
#                 0.5,"%.1f",key=f"c_y_{k}_{n}")
#             st.session_state[f"y_{k}"] = val
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(
#             f"<span style='color:{yc};font-size:12px'>Total: {total_y:.1f}% "
#             f"({'OK' if total_y<=100 else 'EXCEEDS 100%'})</span>",
#             unsafe_allow_html=True)

#         st.markdown("<div class='sec-hdr'>Throughput & Gross Refining Margin</div>",
#                     unsafe_allow_html=True)
#         tp_new = st.number_input("Throughput (bbl/day)",0,200000,
#             int(st.session_state.get(f"tp_{n}",30000)),1000,key=f"c_tp_{n}")
#         st.session_state[f"tp_{n}"] = tp_new
#         if s321 and tp_new:
#             pnl_c  = round(s321 * tp_new * 30 / 1e6, 2)
#             annual = round(pnl_c * 12, 1)
#             st.markdown(
#                 f"<div style='background:#161B22;border:1px solid #30363D;"
#                 f"border-radius:8px;padding:14px;margin-top:8px'>"
#                 f"<span style='color:#8B949E;font-size:10px'>MONTHLY GRM</span><br>"
#                 f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
#                 f"font-family:monospace'>${pnl_c:.2f}MM</span>&nbsp;"
#                 f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
#                 f"<span style='color:#8B949E;font-size:11px'>"
#                 f"${annual}MM annualized · ${s321:.2f}/bbl × {tp_new:,} bbl/day"
#                 f"</span></div>",
#                 unsafe_allow_html=True)

#         st.markdown("---")
#         dl_row = {
#             "Location":           sel,
#             "Price Mode":         "scenario" if mode_now else "live",
#             "Retail Gas ($/gal)": r.get("retail_gas"),
#             "Federal Tax":        r.get("federal_tax_gas"),
#             "State Tax":          r.get("state_tax_gas"),
#             "Pre-tax Gas":        r.get("pretax_gas"),
#             "Distribution":       r.get("dist_margin"),
#             "Wholesale Gas":      r.get("wholesale_gas"),
#             "Wholesale Diesel":   r.get("wholesale_diesel"),
#             "Light Crude ($/bbl)":r.get("crude_light"),
#             "Heavy Crude":        r.get("crude_heavy"),
#             "Cat Feed diff":      r.get("crude_catfeed"),
#             "Jet ($/gal)":        st.session_state.get("jet"),
#             "Bunker ($/gal)":     st.session_state.get("bunker"),
#             "Asphalt ($/gal)":    st.session_state.get("asphalt"),
#             "LPG/Other ($/gal)":  st.session_state.get("lpg"),
#             "3-2-1 ($/bbl)":      r.get("spread_321"),
#             "2-1-1 ($/bbl)":      r.get("spread_211"),
#             "5-3-2 ($/bbl)":      r.get("spread_532"),
#             "Full Yield ($/bbl)": r.get("spread_full"),
#             "Throughput (bbl/d)": tp_new,
#             "GRM ($MM/mo)":       fmt_grm(s321, tp_new),
#             "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
#         }
#         st.download_button(
#             f"⬇️ Download {short} Detail CSV",
#             data=pd.DataFrame([dl_row]).to_csv(index=False),
#             file_name=f"rogue_{short.replace(' ','_').lower()}.csv",
#             mime="text/csv", use_container_width=True)

#     # Forward curve diffs
#     with st.expander("Forward Curve Diffs", expanded=False):
#         fc1,fc2,fc3 = st.columns(3)
#         st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
#             -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",key=f"fcd_{n}")
#         st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",key=f"fgd_{n}")
#         st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",key=f"fdd_{n}")


# # ══════════════════════════════════════════════════════════════════════════════
# # METHODOLOGY
# # ══════════════════════════════════════════════════════════════════════════════
# def show_methodology():
#     with st.expander("📋 Methodology & Data Sources — Audit Reference", expanded=False):
#         st.markdown("""
# <div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

# ### What this tool calculates

# **Gross Refining Margin (GRM)** is the difference between the market value of
# refined products produced from one barrel of crude oil and the cost of that crude.
# It is a *gross* margin — operating costs ($4–8/bbl for a complex US refinery)
# are **not deducted**.

# GRM = Σ(Product Price × Yield Fraction × 42) − Crude Cost

# ---

# ### Price data sources

# | Input | Source | Frequency |
# |---|---|---|
# | Retail gasoline | AAA Fuel Gauge Report (metro daily) | Daily |
# | Retail diesel | AAA Fuel Gauge Report (metro daily) | Daily |
# | WTI crude spot | CME first-month settle (rogueng.duckdns.org) | Daily |
# | RBOB futures | CME settle strip | Daily |
# | ULSD futures | CME settle strip | Daily |
# | Jet fuel spot | EIA Gulf Coast Jet (EPJK/PF4/RGC) | Weekly |
# | Bunker/Residual | EIA Gulf Coast Residual (EPPR/PF4/RGC) | Weekly |
# | Asphalt | EIA US Asphalt (EPPA/PTE/NUS) | Monthly |
# | LPG/Other | Mont Belvieu propane proxy: WTI×0.50÷42 | Calculated |
# | Federal excise tax | IRS/FHWA — unchanged since Oct 1, 1993 | Static |
# | State excise taxes | FTA + EIA, Jul 2025 | Semiannual |

# ---

# ### Price waterfall

# ```
# Retail pump price (AAA)
#   − Federal excise:  $0.184/gal gas · $0.244/gal diesel
#   − State excise:    varies by state
#   = Pre-tax price
#   − Distribution:    default $0.35/gal
#   = Wholesale / refinery gate price
# ```

# ---

# ### State excise taxes (Jul 2025)

# | State | Gas | Diesel | Source |
# |---|---|---|---|
# | AK | $0.0895 | $0.0895 | FTA 2025 |
# | TX | $0.200 | $0.200 | FTA 2025 |
# | OK | $0.190 | $0.190 | FTA 2025 |
# | ND | $0.230 | $0.230 | FTA 2025 |
# | UT | $0.385 | $0.385 | EIA Jul 2025 |
# | LA | $0.200 | $0.200 | FTA 2025 |
# | NM | $0.229 | $0.270 | FTA 2025 + loading fee |

# ---

# ### Full Yield product mix defaults (EIA 2024)

# Source: EIA Petroleum Supply Monthly 2024 / EIA Today in Energy Mar 24 2025
# (eia.gov/todayinenergy/detail.php?id=64786)

# | Product | Default % | EIA 2024 | Notes |
# |---|---|---|---|
# | Gasoline | 44.5% | 44.7% | Lowest share since 2015 |
# | Diesel/Distillate | 29.0% | 28.9% | Approximately flat |
# | Jet Fuel | 11.0% | 11.2% | Record high 2024 |
# | Bunker/Residual | 3.5% | 3.8% | Slightly conservative |
# | Asphalt | 2.5% | 2.8% | Road oil included |
# | LPG/Other | 4.0% | 3.5% | Propane, butane, naphtha |
# | Refinery Use/Loss | 5.5% | ~5.1% | Fuel gas + losses |
# | **Total** | **100%** | **100%** | Fully accounted |

# **LPG/Other** covers propane, butane, ethane, and petrochemical naphtha.
# Priced at Mont Belvieu propane proxy (WTI × 0.50 ÷ 42 ≈ $0.95–$1.10/gal).
# User-adjustable in the Full Calculator.

# **Cat Feed** is a refinery *input* (FCC/hydrocracker feed), not an output.
# Cost is embedded in the crude differential.

# ---

# ### What this tool does NOT capture

# - Refinery operating costs ($3–8/bbl)
# - Blendstock costs (ethanol, MTBE, butane)
# - RIN obligations
# - Pipeline tariffs
# - Carbon costs
# - Hedging gains/losses

# </div>
# """, unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # MAIN
# # ══════════════════════════════════════════════════════════════════════════════
# def main():
#     check_password()
#     init_state()

#     st.markdown(
#         "<h2 style='color:#E6EDF3;margin-bottom:2px;margin-top:-8px'>"
#         "🏭 Rogue Refinery Economics</h2>"
#         "<p style='color:#8B949E;margin-bottom:10px;font-size:12px'>"
#         "Portfolio intelligence · CME forward curves · "
#         "Scenario analysis · Gross Refining Margin</p>",
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
#         if st.button("🔄 Refresh Market Data", use_container_width=True):
#             get_cme.clear(); get_spot.clear()
#             get_lp.clear();  get_spec.clear()
#             for k in list(st.session_state.keys()):
#                 del st.session_state[k]
#             st.rerun()
#         st.markdown("---")
#         st.caption(
#             "**Portfolio:** overview of all locations.\n\n"
#             "**Location detail:** click any card to drill in.\n\n"
#             "**Scenario Mode:** toggle in the Snapshot panel to use "
#             "calculator inputs for current month cards.")

#     with st.spinner("Loading market data..."):
#         strip = get_cme()
#         lp    = get_lp()

#     margins, spot, yields = build_margins(lp)
#     render_ticker(spot, margins)

#     view = st.session_state.get("view","portfolio")
#     if view == "portfolio":
#         show_command(margins)
#         show_methodology()
#     else:
#         show_detail(margins, strip, yields, lp)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
#         f"AAA Fuel Gauge · EIA API · CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()

