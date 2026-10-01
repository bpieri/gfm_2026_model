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
        # Crude basis — auto-populated from config
        f"fwd_crude_basis_{n}": float(loc_cfg.get("light_diff",   0.0)),
        f"fwd_heavy_basis_{n}": float(loc_cfg.get("heavy_diff",   0.0)),
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

    n   = sel
    tp  = r.get("throughput",30000)
    spec= r.get("specialty",{})
    init_fwd_state(n, loc_cfg, sheet_prices, live_spot)
    st.markdown("---")
    tab_today, tab_fwd = st.tabs(["📊 Today", "📈 Forward View"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — TODAY
    # Clean three-panel layout: hero GRM | waterfall | stress test
    # ══════════════════════════════════════════════════════════════════════════
    with tab_today:
        sfull  = r.get("spread_full")
        pnl_v  = fmt_grm(s321, tp)
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

        # ── PANEL 1: Hero headline (left) + supporting cards (right) ─────────
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
                          display:inline-block;width:100%'>
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
            st.markdown("<div class='sec-hdr'>Supporting Metrics</div>",
                        unsafe_allow_html=True)
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
            st.markdown("<div class='sec-hdr'>Today's Prices</div>",
                        unsafe_allow_html=True)
            st.markdown(chips([
                ("WTI+diff", f"${cr_:.2f}/bbl"),
                ("Retail Gas", fmt_gal(ret_g)),
                ("Whsl Gas",   fmt_gal(ws_g)),
                ("Retail Dsl", fmt_gal(ret_d)),
                ("Whsl Dsl",   fmt_gal(ws_d)),
                ("Jet",        fmt_gal(jet_p)),
                ("Bunker",     fmt_gal(bnk_p)),
                ("Asphalt",    fmt_gal(asp_p)),
                ("LPG",        fmt_gal(lpg_p)),
            ]), unsafe_allow_html=True)
            spec_date = r.get("spec_updated","—")
            st.caption(
                f"Gas & diesel: AAA daily · Crude: CME settle · "
                f"Jet/Bunker/Asphalt/LPG: Google Sheet (updated {spec_date})")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── PANEL 2: Waterfall (full width, dominant) ─────────────────────────
        st.markdown("<div class='sec-hdr'>Where Does the Margin Come From?</div>",
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

        # Product contribution mini-row below waterfall
        with st.expander("📊 Product contribution detail", expanded=False):
            pcols = st.columns(6)
            PRODUCTS = [
                ("Gas",   gc_,y_g,"#4A90D9"),("Diesel",dc_,y_d,"#E8A020"),
                ("Jet",   jc_,y_j,"#5A9E3A"),("Bunker",bc_,y_b,"#8B4FBF"),
                ("Asphalt",ac_,y_a,"#CC7722"),("LPG",  lc_,y_l,"#3AA6B9"),
            ]
            for col,(name,rev,yld,clr) in zip(pcols,PRODUCTS):
                crude_alloc = round(cr_*(yld/_sal) if _sal>0 else 0,2)
                net         = round(rev-crude_alloc,2)
                pct         = round(net/grm_full*100,1) if grm_full else 0
                nc_clr      = clr if net>=0 else "#F85149"
                col.markdown(f"""<div class='metric-card' style='padding:10px'>
                    <div class='mc-label' style='color:{clr}'>{name}</div>
                    <div style='font-size:15px;font-weight:700;font-family:monospace;
                         color:{nc_clr}'>{"$"+str(net)+"/bbl"}</div>
                    <div style='font-size:10px;color:#8B949E'>{pct:+.1f}% of GRM</div>
                    <div style='font-size:9px;color:#484F58'>{round(yld*100,1)}% bbl</div>
                </div>""", unsafe_allow_html=True)
            st.caption(
                f"{round(_sal*100,1)}% saleable · "
                f"{round(y_ru*100,1)}% refinery use · "
                f"revenue ${total_rev:.2f}/bbl · crude ${cr_:.2f}/bbl")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── PANEL 3: Stress test (2×2 + stacked bar side by side) ────────────
        st.markdown("<div class='sec-hdr'>What If…</div>",
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
                  <div style='font-size:12px;font-weight:600;color:{clr2}'>
                      {sign} {sign_str(delta)}/bbl</div>
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
                    name=prod,x=["Product Revenue"],y=[val],
                    marker_color=clr2,
                    text=[f"${val:.1f}"],textposition="inside",
                    textfont=dict(size=9,color="#E6EDF3")))
            fig_bar.add_hline(y=cr_,line_color="#F85149",
                line_width=2,line_dash="solid",
                annotation_text=f"Crude ${cr_:.2f}/bbl",
                annotation_font_color="#F85149",annotation_font_size=10)
            fig_bar.update_layout(
                barmode="stack",title=dict(
                    text="Revenue by Product vs Crude Cost",
                    font=dict(color="#E6EDF3",size=12)),
                paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                yaxis=dict(title="$/bbl",gridcolor="#21262D"),
                xaxis=dict(gridcolor="#21262D"),
                legend=dict(bgcolor="#161B22",font=dict(size=9),
                            orientation="h",yanchor="bottom",y=1.05),
                margin=dict(l=0,r=0,t=36,b=0),height=320)
            st.plotly_chart(fig_bar, use_container_width=True)

        # Formula ref (collapsed)
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

        # CSV download
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
            "Specialty Updated":  r.get("spec_updated","—"),
            "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        st.download_button(
            f"⬇️ Download {short} Today CSV",
            data=pd.DataFrame([dl_row]).to_csv(index=False),
            file_name=f"rogue_{short.replace(' ','_').lower()}_today.csv",
            mime="text/csv")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — FORWARD VIEW
    # Basis-driven inputs against the CME forward curve
    # ══════════════════════════════════════════════════════════════════════════
    with tab_fwd:
        # Show CME spot prices as reference
        rbob_spot = live_spot.get("rbob_gal",0) or 0
        ulsd_spot = live_spot.get("ulsd_gal",0) or 0
        wti_spot  = live_spot.get("wti_bbl", 0) or 0

        st.markdown(
            "<div style='background:#161B22;border:1px solid #30363D;"
            "border-radius:8px;padding:12px 16px;margin-bottom:14px'>"
            "<span style='font-size:10px;color:#8B949E;text-transform:uppercase;"
            "letter-spacing:1px'>CME Spot Reference (basis anchor)</span><br>"
            f"<span style='font-family:monospace;color:#E6EDF3'>"
            f"WTI {fmt_bbl(wti_spot)} &nbsp;·&nbsp; "
            f"RBOB {fmt_gal(rbob_spot)} &nbsp;·&nbsp; "
            f"ULSD {fmt_gal(ulsd_spot)}"
            f"</span><br>"
            "<span style='font-size:10px;color:#484F58'>"
            "Forward curve uses CME settle strip for months 1–24. "
            "Adjust basis below to model location-specific differentials.</span>"
            "</div>",
            unsafe_allow_html=True)

        # ── BASIS INPUTS ──────────────────────────────────────────────────────
        with st.expander("⚙️ Basis & Forward Assumptions", expanded=True):
            if st.button("↺ Reset to Config Defaults", key=f"fwd_reset_{n}"):
                spec2 = sheet_prices.get(n, {})
                ulsd2 = live_spot.get("ulsd_gal",3.5) or 3.5
                wti2  = live_spot.get("wti_bbl",80)   or 80
                st.session_state.update({
                    f"fwd_crude_basis_{n}": float(loc_cfg.get("light_diff",0)),
                    f"fwd_heavy_basis_{n}": float(loc_cfg.get("heavy_diff",0)),
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

            # Crude & product basis
            st.markdown("**Location Basis vs NYMEX** *(auto-populated from config)*")
            b1,b2,b3,b4 = st.columns(4)

            crude_basis = b1.number_input(
                f"Light Crude vs WTI ($/bbl)",
                min_value=-20.0, max_value=20.0,
                value=float(st.session_state[f"fwd_crude_basis_{n}"]),
                step=0.25, format="%.2f", key=f"fp_cb_{n}")
            st.session_state[f"fwd_crude_basis_{n}"] = crude_basis
            b1.markdown(
                f"<div class='basis-note'>Config: {loc_cfg.get('light_diff',0):+.2f} · "
                f"Eff. crude: {fmt_bbl(wti_spot+crude_basis)}</div>",
                unsafe_allow_html=True)

            heavy_basis = b2.number_input(
                f"Heavy Crude vs WTI ($/bbl)",
                min_value=-20.0, max_value=20.0,
                value=float(st.session_state[f"fwd_heavy_basis_{n}"]),
                step=0.25, format="%.2f", key=f"fp_hb_{n}")
            st.session_state[f"fwd_heavy_basis_{n}"] = heavy_basis
            b2.markdown(
                f"<div class='basis-note'>Config: {loc_cfg.get('heavy_diff',0):+.2f} · "
                f"Eff. heavy: {fmt_bbl(wti_spot+heavy_basis)}</div>",
                unsafe_allow_html=True)

            gas_basis = b3.number_input(
                "Gas vs RBOB ($/gal)",
                min_value=-1.0, max_value=1.0,
                value=float(st.session_state[f"fwd_gas_basis_{n}"]),
                step=0.01, format="%.3f", key=f"fp_gb_{n}")
            st.session_state[f"fwd_gas_basis_{n}"] = gas_basis
            b3.markdown(
                f"<div class='basis-note'>Config: {loc_cfg.get('gas_diff',0):+.3f} · "
                f"Eff. spot: {fmt_gal(rbob_spot+gas_basis)}</div>",
                unsafe_allow_html=True)

            die_basis = b4.number_input(
                "Diesel vs ULSD ($/gal)",
                min_value=-1.0, max_value=1.0,
                value=float(st.session_state[f"fwd_die_basis_{n}"]),
                step=0.01, format="%.3f", key=f"fp_db_{n}")
            st.session_state[f"fwd_die_basis_{n}"] = die_basis
            b4.markdown(
                f"<div class='basis-note'>Config: {loc_cfg.get('diesel_diff',0):+.3f} · "
                f"Eff. spot: {fmt_gal(ulsd_spot+die_basis)}</div>",
                unsafe_allow_html=True)

            # Specialty — show current price + delta assumption
            st.markdown("<br>**Specialty Products** *(flat forward assumption + delta)*")
            st.caption(
                "Current prices from Google Sheet. Enter a $/gal delta to model "
                "a future price change (e.g. +0.50 = $0.50/gal above today's price).")

            sp1,sp2,sp3,sp4 = st.columns(4)
            jet_base   = float(st.session_state[f"fwd_jet_{n}"])
            jet_delta  = sp1.number_input(
                f"Jet delta vs ${jet_base:.2f} ($/gal)",
                min_value=-3.0,max_value=3.0,
                value=float(st.session_state[f"fwd_jet_delta_{n}"]),
                step=0.05,format="%.2f",key=f"fp_jd_{n}")
            st.session_state[f"fwd_jet_delta_{n}"] = jet_delta
            sp1.markdown(
                f"<div class='basis-note'>Forward: {fmt_gal(jet_base+jet_delta)}</div>",
                unsafe_allow_html=True)

            bnk_base   = float(st.session_state[f"fwd_bunker_{n}"])
            bnk_delta  = sp2.number_input(
                f"Bunker delta vs ${bnk_base:.2f} ($/gal)",
                min_value=-2.0,max_value=2.0,
                value=float(st.session_state[f"fwd_bunker_delta_{n}"]),
                step=0.05,format="%.2f",key=f"fp_bd_{n}")
            st.session_state[f"fwd_bunker_delta_{n}"] = bnk_delta
            sp2.markdown(
                f"<div class='basis-note'>Forward: {fmt_gal(bnk_base+bnk_delta)}</div>",
                unsafe_allow_html=True)

            asp_base   = float(st.session_state[f"fwd_asphalt_{n}"])
            asp_delta  = sp3.number_input(
                f"Asphalt delta vs ${asp_base:.2f} ($/gal)",
                min_value=-2.0,max_value=2.0,
                value=float(st.session_state[f"fwd_asphalt_delta_{n}"]),
                step=0.05,format="%.2f",key=f"fp_ad_{n}")
            st.session_state[f"fwd_asphalt_delta_{n}"] = asp_delta
            sp3.markdown(
                f"<div class='basis-note'>Forward: {fmt_gal(asp_base+asp_delta)}</div>",
                unsafe_allow_html=True)

            lpg_base   = float(st.session_state[f"fwd_lpg_{n}"])
            lpg_delta  = sp4.number_input(
                f"LPG delta vs ${lpg_base:.2f} ($/gal)",
                min_value=-1.0,max_value=1.0,
                value=float(st.session_state[f"fwd_lpg_delta_{n}"]),
                step=0.01,format="%.2f",key=f"fp_ld_{n}")
            st.session_state[f"fwd_lpg_delta_{n}"] = lpg_delta
            sp4.markdown(
                f"<div class='basis-note'>Forward: {fmt_gal(lpg_base+lpg_delta)}</div>",
                unsafe_allow_html=True)

            # Throughput + yield (collapsed)
            with st.expander("Throughput & Yield Configuration", expanded=False):
                tx1,tx2 = st.columns(2)
                st.session_state[f"fwd_dist_{n}"] = tx1.number_input(
                    "Distribution margin ($/gal)",0.0,1.0,
                    float(st.session_state[f"fwd_dist_{n}"]),
                    0.01,"%.2f",key=f"fp_dist_{n}")
                st.session_state[f"fwd_tp_{n}"] = int(tx2.number_input(
                    "Throughput (bbl/day)",0,200000,
                    int(st.session_state[f"fwd_tp_{n}"]),1000,
                    key=f"fp_tp_{n}"))

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
                        f"{lbl}(%)",0.0,100.0,
                        float(st.session_state.get(f"fwd_y_{k}_{n}",default)),
                        0.5,"%.1f",key=f"fp_y_{k}_{n}")
                    st.session_state[f"fwd_y_{k}_{n}"] = val
                    total_y += val
                yc = "#3FB950" if total_y<=100 else "#F85149"
                st.markdown(
                    f"<span style='color:{yc};font-size:11px'>"
                    f"Total: {total_y:.1f}%</span>",
                    unsafe_allow_html=True)

        # ── Compute forward crack with basis ──────────────────────────────────
        fwd_yields = {k: round(st.session_state.get(
                        f"fwd_y_{k}_{n}", YIELD_DEFAULTS.get(k,0)*100)/100,6)
                      for k in YIELD_DEFAULTS}

        # Effective forward specialty prices
        eff_jet    = jet_base + jet_delta
        eff_bunker = bnk_base + bnk_delta
        eff_asphalt= asp_base + asp_delta
        eff_lpg    = lpg_base + lpg_delta

        loc_fwd = compute_forward_crack(
            strip       = strip,
            crude_diff  = crude_basis,
            gas_diff    = gas_basis,
            diesel_diff = die_basis,
            jet_fwd     = eff_jet,
            bunker_fwd  = eff_bunker,
            asphalt_fwd = eff_asphalt,
            lpg_fwd     = eff_lpg,
            yields      = fwd_yields,
        )

        if not loc_fwd:
            st.info("Forward curve data not available. Check CME connection.")
        else:
            fwd_ok    = [row for row in loc_fwd if row.get("crack_321")]
            months    = [row["month"]       for row in fwd_ok]
            wti_fwd   = [row["wti"]         for row in fwd_ok]
            rbob_f    = [row.get("rbob",0)  for row in fwd_ok]
            ulsd_f    = [row.get("ulsd",0)  for row in fwd_ok]
            crack_vals= [row.get("crack_321") for row in fwd_ok]
            full_vals = [row.get("crack_full") for row in fwd_ok]

            # Show effective price strip as reference
            st.markdown("<div class='sec-hdr'>Effective Forward Prices (CME strip + basis)</div>",
                        unsafe_allow_html=True)
            if wti_fwd:
                strip_preview = pd.DataFrame({
                    "Month":       months[:6],
                    "WTI ($/bbl)": [f"${v:.2f}" for v in wti_fwd[:6]],
                    "RBOB ($/gal)":[f"${(v+gas_basis):.3f}" for v in rbob_f[:6]],
                    "ULSD ($/gal)":[f"${(v+die_basis):.3f}" for v in ulsd_f[:6]],
                    "3-2-1 ($/bbl)":[f"${v:.2f}" if v else "—"
                                     for v in crack_vals[:6]],
                })
                st.dataframe(strip_preview, use_container_width=True,
                             hide_index=True)
                st.caption("Showing next 6 months · full table in Forward GRM Table below")

            # Compute product revenues for area chart
            y_g2 = fwd_yields.get("gasoline",  0.445)
            y_d2 = fwd_yields.get("ulsd",      0.290)
            y_j2 = fwd_yields.get("jet",       0.110)
            y_b2 = fwd_yields.get("bunker",    0.035)
            y_a2 = fwd_yields.get("asphalt",   0.025)
            y_l2 = fwd_yields.get("lpg_other", 0.040)

            gas_rev = [round((rb+gas_basis)*y_g2*42,2) for rb in rbob_f]
            die_rev = [round((ul+die_basis)*y_d2*42,2) for ul in ulsd_f]
            jet_rev = [round(eff_jet    *y_j2*42,2)]*len(months)
            bnk_rev = [round(eff_bunker *y_b2*42,2)]*len(months)
            asp_rev = [round(eff_asphalt*y_a2*42,2)]*len(months)
            lpg_rev = [round(eff_lpg    *y_l2*42,2)]*len(months)

            # Area chart
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
                ("Gasoline",  gas_rev),("Diesel",    die_rev),
                ("Jet Fuel",  jet_rev),("Bunker",    bnk_rev),
                ("Asphalt",   asp_rev),("LPG/Other", lpg_rev),
            ]:
                fig_fwd.add_trace(go.Scatter(
                    x=months,y=vals,name=name,
                    mode="none",fill="tonexty",
                    fillcolor=AREA_COLORS[name],
                    stackgroup="one",line=dict(width=0)))
            fig_fwd.add_trace(go.Scatter(
                x=months,y=wti_fwd,name="Crude Cost (WTI+basis)",
                line=dict(color="#FFFFFF",width=2.5),mode="lines"))
            fig_fwd.add_trace(go.Scatter(
                x=months,y=crack_vals,name="3-2-1 Crack ($/bbl)",
                line=dict(color="#F85149",width=2,dash="dot"),yaxis="y2"))
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
            st.plotly_chart(fig_fwd,use_container_width=True)
            st.caption(
                "Stacked areas = product revenue · White line = crude cost (WTI+basis) · "
                "Gap above white = margin · Red dashed (right axis) = 3-2-1 crack")

            # Stress ±20%
            fov = [v for v in full_vals if v is not None]
            fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
            if fov:
                fwd_dn = compute_forward_crack(
                    strip=strip,
                    crude_diff  = crude_basis+(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff=gas_basis-0.20, diesel_diff=die_basis-0.20,
                    jet_fwd=eff_jet*0.80, bunker_fwd=eff_bunker*0.80,
                    asphalt_fwd=eff_asphalt*0.80, lpg_fwd=eff_lpg*0.80,
                    yields=fwd_yields)
                fwd_up = compute_forward_crack(
                    strip=strip,
                    crude_diff  = crude_basis-(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff=gas_basis+0.20, diesel_diff=die_basis+0.20,
                    jet_fwd=eff_jet*1.20, bunker_fwd=eff_bunker*1.20,
                    asphalt_fwd=eff_asphalt*1.20, lpg_fwd=eff_lpg*1.20,
                    yields=fwd_yields)
                sdn = [row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
                sup = [row.get("crack_full") for row in fwd_up if row.get("crack_full")]
                mdn = [row["month"] for row in fwd_dn if row.get("crack_full")]
                mup = [row["month"] for row in fwd_up if row.get("crack_full")]

                st.markdown("<div class='sec-hdr'>Forward GRM Stress Test ±20%</div>",
                            unsafe_allow_html=True)
                fig_st = go.Figure()
                if sdn and len(sdn)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mdn+mdn[::-1],y=sdn+fov[::-1],fill="toself",
                        fillcolor="rgba(248,81,73,0.12)",
                        line=dict(width=0),name="Downside −20%",hoverinfo="skip"))
                if sup and len(sup)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mup+mup[::-1],y=sup+fov[::-1],fill="toself",
                        fillcolor="rgba(63,185,80,0.10)",
                        line=dict(width=0),name="Upside +20%",hoverinfo="skip"))
                fig_st.add_trace(go.Scatter(
                    x=fmo,y=fov,name="Full Yield GRM — Base",
                    line=dict(color="#E8A020",width=2.5),
                    mode="lines+markers",marker=dict(size=5)))
                if sdn:
                    fig_st.add_trace(go.Scatter(
                        x=mdn,y=sdn,name="Downside",
                        line=dict(color="#F85149",width=1.5,dash="dash")))
                if sup:
                    fig_st.add_trace(go.Scatter(
                        x=mup,y=sup,name="Upside",
                        line=dict(color="#3FB950",width=1.5,dash="dash")))
                fig_st.add_hline(y=15,line_dash="dot",line_color="#8B949E",
                    opacity=0.5,annotation_text="~Breakeven $15/bbl",
                    annotation_font_color="#8B949E",annotation_font_size=9)
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
                st.plotly_chart(fig_st,use_container_width=True)
                st.caption(
                    "Base = Full Yield GRM at current basis · "
                    "Red = downside (crude +20%, products −20%) · "
                    "Green = upside (crude −20%, products +20%)")

            # Forward GRM table
            fwd_tp = st.session_state.get(f"fwd_tp_{n}", tp)
            grm_list = [round(v*fwd_tp*30/1e6,2) if v else None
                        for v in crack_vals]
            fwd_df = pd.DataFrame({
                "Month":             months,
                "WTI+Basis ($/bbl)": [round(v+crude_basis,2) for v in wti_fwd],
                "RBOB+Basis ($/gal)":[round(v+gas_basis,3)   for v in rbob_f],
                "ULSD+Basis ($/gal)":[round(v+die_basis,3)   for v in ulsd_f],
                "3-2-1 GRM ($/bbl)": crack_vals,
                "Full Yield ($/bbl)":full_vals,
                f"GRM ($MM/mo @ {fwd_tp//1000}k bbl/d)": grm_list,
            })
            with st.expander("📋 Forward GRM Table"):
                st.dataframe(fwd_df,use_container_width=True,hide_index=True)
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
    else:
        show_detail(live_margins, strip, sheet_prices, live_spot)

    st.markdown(
        f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
        f"AAA Fuel Gauge · EIA API · CME local xlsx · Google Sheet · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()


# # app.py — Rogue Refinery Economics v5
# # Two-tab per-refinery layout: Today | Forward
# # Specialty prices from Google Sheet (jet, bunker, asphalt, lpg per location)
# # Edmonton removed — to be added back later
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


# # ── Scroll to top on page transition ──────────────────────────────────────────
# def _scroll_top():
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
# .price-pill{display:inline-block;background:#21262D;border:1px solid #30363D;
#   border-radius:6px;padding:6px 14px;margin:3px;text-align:center}
# .price-pill-label{font-size:9px;color:#8B949E;text-transform:uppercase;
#   letter-spacing:1px;display:block}
# .price-pill-value{font-size:15px;font-weight:700;color:#E6EDF3;
#   font-family:monospace;display:block}
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
# GSHEET_URL = (
#     "https://docs.google.com/spreadsheets/d/e/"
#     "2PACX-1vTfw6hAiE418gmKF2Ut0qRV2xCTex3fB4wY4IUwoR_5x5bRDpPxPbGwCaJunbjXDhHAeu-h_lQhUKiB"
#     "/pub?gid=0&single=true&output=csv"
# )

# @st.cache_data(ttl=3600)
# def get_specialty_sheet() -> dict:
#     """
#     Fetch per-location specialty prices from Google Sheet.
#     Returns {location_display: {jet_gal, bunker_gal, asphalt_gal, lpg_gal, last_updated}}
#     Falls back to SPECIALTY_DEFAULTS if sheet unavailable.
#     """
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
#                 "lpg_gal":     float(row.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal", 0.95))),
#                 "last_updated":row.get("last_updated","—"),
#             }
#         print(f"  Google Sheet: loaded {len(result)} locations")
#         return result
#     except Exception as e:
#         print(f"  Google Sheet fetch failed: {e} — using defaults")
#         return {}

# @st.cache_data(ttl=3600)
# def get_cme():  return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot(): return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():   return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec(): return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Build live margins (Today tab — no user overrides) ────────────────────────
# def build_live_margins(lp, sheet_prices):
#     """
#     Build margins from 100% live data — no user inputs involved.
#     Gas/diesel: AAA retail → tax strip → distribution strip.
#     Crude: CME first-month settle + location diff from config.
#     Specialty: per-location from Google Sheet, EIA fallback.
#     Yields: EIA 2024 defaults from config (not user-adjustable in Today tab).
#     """
#     live_spot = get_spot()
#     eia_spec  = get_spec()

#     yields = {k: v for k, v in YIELD_DEFAULTS.items()}

#     rows = []
#     for loc in LOCATIONS:
#         n    = loc["display"]
#         spec = sheet_prices.get(n, {})
#         location_specialty = {
#             "jet_gal":     spec.get("jet_gal",     eia_spec.get("jet_gal")     or live_spot.get("ulsd_gal",3.5)*1.05),
#             "bunker_gal":  spec.get("bunker_gal",  eia_spec.get("bunker_gal")  or live_spot.get("ulsd_gal",3.5)*0.70),
#             "asphalt_gal": spec.get("asphalt_gal", eia_spec.get("asphalt_gal") or live_spot.get("ulsd_gal",3.5)*0.60),
#             "lpg_gal":     spec.get("lpg_gal",     SPECIALTY_DEFAULTS.get("lpg_gal", 0.95)),
#         }
#         loc_list = [dict(loc)]
#         margin_list = compute_location_margins(
#             locations       = loc_list,
#             spot_prices     = live_spot,
#             location_prices = lp,
#             specialty       = location_specialty,
#             yields          = yields,
#             dist_margin_gal = 0.35,
#         )
#         if margin_list:
#             r = margin_list[0]
#             r["throughput"]   = loc.get("throughput", 30000)
#             r["pnl"]          = fmt_grm(r.get("spread_321"), r["throughput"])
#             r["specialty"]    = location_specialty
#             r["spec_updated"] = spec.get("last_updated","—")
#             rows.append(r)

#     return rows, live_spot, yields


# # ── Session state for forward tab inputs ──────────────────────────────────────
# def init_fwd_state(loc_display, sheet_prices, live_spot):
#     """Initialise per-location forward inputs from live data if not set."""
#     n = loc_display
#     if st.session_state.get(f"_fwd_init_{n}"): return
#     spec = sheet_prices.get(n, {})
#     ulsd = live_spot.get("ulsd_gal", 3.50) or 3.50
#     wti  = live_spot.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         f"fwd_wti_{n}":    wti,
#         f"fwd_rbob_{n}":   live_spot.get("rbob_gal", 2.50) or 2.50,
#         f"fwd_ulsd_{n}":   ulsd,
#         f"fwd_jet_{n}":    spec.get("jet_gal",     ulsd * 1.05),
#         f"fwd_bunker_{n}": spec.get("bunker_gal",  ulsd * 0.70),
#         f"fwd_asphalt_{n}":spec.get("asphalt_gal", ulsd * 0.60),
#         f"fwd_lpg_{n}":    spec.get("lpg_gal",     round(wti*0.50/42,3)),
#         f"fwd_dist_{n}":   0.35,
#         f"fwd_fcd_{n}":    0.0,
#         f"fwd_fgd_{n}":    0.0,
#         f"fwd_fdd_{n}":    0.0,
#         f"fwd_tp_{n}":     30000,
#     })
#     for k, v in YIELD_DEFAULTS.items():
#         if f"fwd_y_{k}_{n}" not in st.session_state:
#             st.session_state[f"fwd_y_{k}_{n}"] = round(v * 100, 1)
#     st.session_state[f"_fwd_init_{n}"] = True


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
# def render_ticker(live_spot, live_margins):
#     wti  = live_spot.get("wti_bbl")
#     rbob = live_spot.get("rbob_gal")
#     ulsd = live_spot.get("ulsd_gal")
#     spreads   = [r["spread_321"] for r in live_margins if r.get("spread_321")]
#     pavg      = round(sum(spreads)/len(spreads),2) if spreads else None
#     total_grm = sum(r["pnl"] for r in live_margins if r.get("pnl"))
#     pc = spread_color(pavg)
#     st.markdown(f"""
#     <div class="ticker-bar">
#       <div class="ticker-item">
#         <span class="ticker-label">WTI Crude</span>
#         <span class="ticker-value">{fmt_bbl(wti)}</span>
#         <span class="ticker-label">per barrel</span>
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
#         <span class="ticker-label">×42</span>
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
#           {"$"+str(round(total_grm,1))+"MM" if total_grm else "—"}
#         </span>
#         <span class="ticker-label">before opex</span>
#       </div>
#     </div>""", unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 1 — PORTFOLIO COMMAND VIEW
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
#             "name":   r["display"],
#             "short":  r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat":    c[0], "lon": c[1],
#             "spread": s, "color": spread_color(s),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield GRM: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"GRM/mo: {'$'+str(r['pnl'])+'MM' if r.get('pnl') else '—'}<br>"
#                 f"Jet: ${spec.get('jet_gal','—')}/gal  Bunker: ${spec.get('bunker_gal','—')}/gal<br>"
#                 f"<i>Click card below to open</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"], mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2,color="#0D1117"), opacity=0.90),
#         text=df_m["short"], textposition="top center",
#         textfont=dict(size=10,color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text"))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]], mode="text",
#                 text=[f"${row['spread']:.0f}"],
#                 textfont=dict(size=10,color=row["color"],family="monospace"),
#                 hoverinfo="skip", showlegend=False))
#     fig_m.update_layout(
#         geo=dict(scope="world", showland=True, landcolor="#1C2128",
#                  showocean=True, oceancolor="#0D1117",
#                  showlakes=True, lakecolor="#0D1117",
#                  showcountries=True, countrycolor="#30363D",
#                  showcoastlines=True, coastlinecolor="#30363D",
#                  showframe=False, bgcolor="#0D1117",
#                  center=dict(lat=45,lon=-100), projection_scale=1.4,
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
#         ("Puerto Rico",            "Puerto Rico",   "PR"),
#     ]

#     margin_map = {r["display"]: r for r in live_margins}

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
#             <div class='loc-card-pnl'>{pnl_s}</div>
#         </div>""", unsafe_allow_html=True)
#         if st.button("Open →", key=btn_key, use_container_width=True):
#             st.session_state["view"]    = "detail"
#             st.session_state["sel_loc"] = r["display"]
#             st.rerun()

#     st.markdown("<div class='sec-hdr'>In Construction</div>", unsafe_allow_html=True)
#     constr = [r for r in live_margins if r["display"] in IN_CONSTRUCTION]
#     cc = st.columns(4)
#     for i,r in enumerate(constr):
#         with cc[i%4]: _render_card(r, f"btn_con_{i}")

#     st.markdown("<br>", unsafe_allow_html=True)
#     st.markdown("<div class='sec-hdr'>Development Locations</div>", unsafe_allow_html=True)
#     dev_items = [(dn,sl,st_) for dn,sl,st_ in DEVELOPMENT_ORDER if dn in margin_map]
#     dc = st.columns(4)
#     for i,(dn,sl,_) in enumerate(dev_items):
#         with dc[i%4]: _render_card(margin_map[dn], f"btn_dev_{i}")

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
#             mime="text/csv", use_container_width=True)
#     with dc2:
#         st.dataframe(df_dl[[
#             "Location","Light Crude ($/bbl)",
#             "Gasoline - Retail","Gasoline - Wholesale",
#             "Diesel - Retail","Diesel - Wholesale",
#             "Jet Fuel ($/gal)","Bunker ($/gal)","Asphalt ($/gal)",
#             "3-2-1 ($/bbl)","Full Yield GRM ($/bbl)","Monthly GRM ($MM)",
#         ]], use_container_width=True, hide_index=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL  (two tabs: Today | Forward)
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(live_margins, strip, sheet_prices, live_spot):
#     _scroll_top()
#     sel = st.session_state.get("sel_loc","")
#     r   = next((m for m in live_margins if m["display"]==sel), None)

#     # Back nav + header
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
#             f"</h3>", unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     n    = sel
#     spec = r.get("specialty", {})
#     tp   = r.get("throughput", 30000)

#     # Initialise forward tab state
#     init_fwd_state(n, sheet_prices, live_spot)

#     st.markdown("---")
#     tab_today, tab_fwd = st.tabs(["📊 Today", "📈 Forward View"])

#     # ══════════════════════════════════════════════════════════════════════════
#     # TAB 1 — TODAY  (read-only, live data only)
#     # ══════════════════════════════════════════════════════════════════════════
#     with tab_today:

#         # ── Headline crack spread cards ───────────────────────────────────────
#         sfull = r.get("spread_full")
#         pnl_v = fmt_grm(s321, tp)

#         h1,h2,h3,h4 = st.columns(4)
#         h1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>3-2-1 Reference Spread</div>
#             <div class='mc-value' style='color:{spread_color(s321)};font-size:22px'>
#                 {"$"+str(s321)+"/bbl" if s321 else "—"}</div>
#             <div class='mc-sub'>2 gas + 1 diesel benchmark</div>
#         </div>""", unsafe_allow_html=True)
#         h2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Refinery Crack Spread</div>
#             <div class='mc-value' style='color:{spread_color(sfull)};font-size:22px'>
#                 {"$"+str(sfull)+"/bbl" if sfull else "—"}</div>
#             <div class='mc-sub'>Full Yield GRM · all products</div>
#         </div>""", unsafe_allow_html=True)
#         h3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>GRM / Month</div>
#             <div class='mc-value' style='color:#3FB950;font-size:22px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}</div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)
#         h4.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Annual GRM Run-Rate</div>
#             <div class='mc-value' style='color:#3FB950;font-size:22px'>
#                 {"$"+str(round(pnl_v*12,1))+"MM" if pnl_v else "—"}</div>
#             <div class='mc-sub'>{f"at {tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)

#         # ── Today's prices pill row ───────────────────────────────────────────
#         st.markdown("<div class='sec-hdr'>Today's Prices ($/gal)</div>",
#                     unsafe_allow_html=True)

#         ws_g  = r.get("wholesale_gas",  0) or 0
#         ws_d  = r.get("wholesale_diesel",0) or 0
#         ret_g = r.get("retail_gas",     0) or 0
#         ret_d = r.get("retail_diesel",  0) or 0
#         cr_   = r.get("crude_light",    0) or 0
#         jet_p = spec.get("jet_gal",    SPECIALTY_DEFAULTS["jet_gal"])
#         bnk_p = spec.get("bunker_gal", SPECIALTY_DEFAULTS["bunker_gal"])
#         asp_p = spec.get("asphalt_gal",SPECIALTY_DEFAULTS["asphalt_gal"])
#         lpg_p = spec.get("lpg_gal",    SPECIALTY_DEFAULTS.get("lpg_gal",0.95))

#         # Build price pills as HTML
#         pills = [
#             ("WTI Crude",   f"${cr_:.2f}/bbl"),
#             ("Light Crude", f"${cr_:.2f}/bbl"),
#             ("RBOB",        f"${live_spot.get('rbob_gal',0):.3f}/gal"),
#             ("ULSD",        f"${live_spot.get('ulsd_gal',0):.3f}/gal"),
#             ("Retail Gas",  f"${ret_g:.3f}/gal"),
#             ("Whsl Gas",    f"${ws_g:.3f}/gal"),
#             ("Retail Diesel",f"${ret_d:.3f}/gal"),
#             ("Whsl Diesel", f"${ws_d:.3f}/gal"),
#             ("Jet Fuel",    f"${jet_p:.3f}/gal"),
#             ("Bunker",      f"${bnk_p:.3f}/gal"),
#             ("Asphalt",     f"${asp_p:.3f}/gal"),
#             ("LPG/Other",   f"${lpg_p:.3f}/gal"),
#         ]
#         pill_html = "<div style='display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px'>"
#         for label, val in pills:
#             pill_html += (
#                 f"<div class='price-pill'>"
#                 f"<span class='price-pill-label'>{label}</span>"
#                 f"<span class='price-pill-value'>{val}</span>"
#                 f"</div>"
#             )
#         pill_html += "</div>"
#         st.markdown(pill_html, unsafe_allow_html=True)

#         spec_date = r.get("spec_updated","—")
#         st.caption(
#             f"Gas & diesel: AAA daily · Crude: CME settle · "
#             f"Jet/Bunker/Asphalt/LPG: Google Sheet (updated {spec_date})"
#         )

#         st.markdown("<br>", unsafe_allow_html=True)
#         left_col, right_col = st.columns([1,1], gap="large")

#         # ── GRM build-up waterfall ────────────────────────────────────────────
#         with left_col:
#             st.markdown("<div class='sec-hdr'>Where Does the Margin Come From?</div>",
#                         unsafe_allow_html=True)
#             yields = {k: v for k, v in YIELD_DEFAULTS.items()}
#             y_g  = yields.get("gasoline",  0.445)
#             y_d  = yields.get("ulsd",      0.290)
#             y_j  = yields.get("jet",       0.110)
#             y_b  = yields.get("bunker",    0.035)
#             y_a  = yields.get("asphalt",   0.025)
#             y_l  = yields.get("lpg_other", 0.040)
#             y_ru = yields.get("refinery_use",0.055)
#             _sal = y_g + y_d + y_j + y_b + y_a + y_l

#             gc_ = round(ws_g  * y_g * 42, 2)
#             dc_ = round(ws_d  * y_d * 42, 2)
#             jc_ = round(jet_p * y_j * 42, 2)
#             bc_ = round(bnk_p * y_b * 42, 2)
#             ac_ = round(asp_p * y_a * 42, 2)
#             lc_ = round(lpg_p * y_l * 42, 2)
#             total_rev  = gc_+dc_+jc_+bc_+ac_+lc_
#             grm_full   = round(total_rev - cr_, 2)

#             fig_wf = go.Figure(go.Waterfall(
#                 orientation="v",
#                 measure=["absolute","relative","relative","relative",
#                          "relative","relative","relative","total"],
#                 x=["− Crude","+ Gas","+ Diesel","+ Jet",
#                    "+ Bunker","+ Asphalt","+ LPG","= GRM"],
#                 y=[-cr_, gc_, dc_, jc_, bc_, ac_, lc_, 0],
#                 text=[f"-${cr_:.2f}",f"+${gc_:.2f}",f"+${dc_:.2f}",
#                       f"+${jc_:.2f}",f"+${bc_:.2f}",f"+${ac_:.2f}",
#                       f"+${lc_:.2f}",f"${grm_full:.2f}"],
#                 textposition="outside",
#                 textfont=dict(size=9,color="#E6EDF3"),
#                 connector=dict(line=dict(color="#30363D",width=1)),
#                 decreasing=dict(marker_color="#F85149"),
#                 increasing=dict(marker_color="#3FB950"),
#                 totals=dict(marker_color="#E8A020"),
#             ))
#             fig_wf.update_layout(
#                 paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                 xaxis=dict(gridcolor="#21262D",tickangle=-20),
#                 margin=dict(l=0,r=0,t=8,b=0),height=320,showlegend=False)
#             st.plotly_chart(fig_wf, use_container_width=True)

#             # Product contribution cards
#             st.markdown("<div class='sec-hdr'>Contribution to GRM</div>",
#                         unsafe_allow_html=True)
#             PRODUCTS = [
#                 ("Gas",    gc_, y_g, "#4A90D9"),
#                 ("Diesel", dc_, y_d, "#E8A020"),
#                 ("Jet",    jc_, y_j, "#5A9E3A"),
#                 ("Bunker", bc_, y_b, "#8B4FBF"),
#                 ("Asphalt",ac_, y_a, "#CC7722"),
#                 ("LPG",    lc_, y_l, "#3AA6B9"),
#             ]
#             pcols = st.columns(6)
#             for col,(name,rev,yld,clr) in zip(pcols,PRODUCTS):
#                 crude_alloc = round(cr_*(yld/_sal) if _sal>0 else 0,2)
#                 net         = round(rev-crude_alloc,2)
#                 pct         = round(net/grm_full*100,1) if grm_full else 0
#                 nc_clr      = clr if net>=0 else "#F85149"
#                 col.markdown(f"""<div class='metric-card' style='padding:10px'>
#                     <div class='mc-label' style='color:{clr}'>{name}</div>
#                     <div style='font-size:16px;font-weight:700;font-family:monospace;
#                          color:{nc_clr}'>{"$"+str(net)+"/bbl"}</div>
#                     <div style='font-size:10px;color:#8B949E'>{pct:+.1f}% of GRM</div>
#                     <div style='font-size:9px;color:#484F58'>{round(yld*100,1)}% bbl</div>
#                 </div>""", unsafe_allow_html=True)

#             st.markdown(
#                 f"<div style='font-size:10px;color:#484F58;margin-top:4px'>"
#                 f"{round(_sal*100,1)}% saleable · {round(y_ru*100,1)}% refinery use · "
#                 f"total revenue ${total_rev:.2f}/bbl · crude ${cr_:.2f}/bbl</div>",
#                 unsafe_allow_html=True)

#         # ── Stress test 2×2 ───────────────────────────────────────────────────
#         with right_col:
#             st.markdown("<div class='sec-hdr'>Today's Stress Test</div>",
#                         unsafe_allow_html=True)
#             base = s321 or 0
#             crude_b = r.get("crude_light", cr_)
#             gas_b   = r.get("wholesale_gas",  ws_g)
#             die_b   = r.get("wholesale_diesel",ws_d)

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
#                 is_up = delta >= 0
#                 bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                 clr2  = "#3FB950" if is_up else "#F85149"
#                 sign  = "▲" if is_up else "▼"
#                 col.markdown(f"""
#                 <div style='background:{bg};border-radius:8px;padding:14px;
#                      text-align:center;margin-bottom:6px'>
#                   <div style='font-size:9px;color:{clr2};letter-spacing:1px;
#                        text-transform:uppercase;font-weight:600'>{lbl}</div>
#                   <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                       Base 3-2-1: ${base:.2f}</div>
#                   <div style='font-size:22px;font-weight:700;
#                        font-family:monospace;color:{clr2}'>${val:.2f}</div>
#                   <div style='font-size:13px;font-weight:600;color:{clr2}'>
#                       {sign} {sign_str(delta)}/bbl</div>
#                 </div>""", unsafe_allow_html=True)

#             # Stacked revenue bar
#             st.markdown("<br>", unsafe_allow_html=True)
#             st.markdown("<div class='sec-hdr'>Revenue by Product ($/bbl)</div>",
#                         unsafe_allow_html=True)
#             AREA_BAR = {
#                 "Gasoline": ("#4A90D9", gc_),
#                 "Diesel":   ("#E8A020", dc_),
#                 "Jet":      ("#5A9E3A", jc_),
#                 "Bunker":   ("#8B4FBF", bc_),
#                 "Asphalt":  ("#CC7722", ac_),
#                 "LPG":      ("#3AA6B9", lc_),
#             }
#             fig_bar = go.Figure()
#             for prod,(clr2,val) in AREA_BAR.items():
#                 fig_bar.add_trace(go.Bar(
#                     name=prod, x=["Revenue"], y=[val],
#                     marker_color=clr2,
#                     text=[f"${val:.1f}"], textposition="inside",
#                     textfont=dict(size=9,color="#E6EDF3")))
#             fig_bar.add_hline(y=cr_, line_color="#F85149",
#                 line_width=2, line_dash="solid",
#                 annotation_text=f"Crude ${cr_:.2f}/bbl",
#                 annotation_font_color="#F85149",
#                 annotation_font_size=9)
#             fig_bar.update_layout(
#                 barmode="stack",
#                 paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                 xaxis=dict(gridcolor="#21262D"),
#                 legend=dict(bgcolor="#161B22",font=dict(size=9),
#                             orientation="h",yanchor="bottom",y=1.02),
#                 margin=dict(l=0,r=0,t=30,b=0),height=220)
#             st.plotly_chart(fig_bar, use_container_width=True)

#             # Formula reference
#             with st.expander("📐 Simplified formula reference", expanded=False):
#                 fc1,fc2,fc3 = st.columns(3)
#                 for fcol,lbl,val,formula in [
#                     (fc1,"3-2-1",s321,"(2 gas + 1 diesel − 3 WTI) ÷ 3"),
#                     (fc2,"2-1-1",r.get("spread_211"),"(1 gas + 1 diesel − 2 WTI) ÷ 2"),
#                     (fc3,"5-3-2",r.get("spread_532"),"(3 gas + 2 diesel − 5 WTI) ÷ 5"),
#                 ]:
#                     fcol.markdown(f"""<div class='metric-card'>
#                         <div class='mc-label'>{lbl}</div>
#                         <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                             {"$"+str(val)+"/bbl" if val else "—"}</div>
#                         <div class='mc-sub' style='font-size:9px'>{formula}</div>
#                     </div>""", unsafe_allow_html=True)

#         # Per-location CSV download
#         st.markdown("---")
#         dl_row = {
#             "Location":           sel,
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
#             "Throughput (bbl/d)": tp,
#             "GRM ($MM/mo)":       pnl_v,
#             "Specialty Updated":  spec_date,
#             "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
#         }
#         st.download_button(
#             f"⬇️ Download {short} Today CSV",
#             data=pd.DataFrame([dl_row]).to_csv(index=False),
#             file_name=f"rogue_{short.replace(' ','_').lower()}_today.csv",
#             mime="text/csv")

#     # ══════════════════════════════════════════════════════════════════════════
#     # TAB 2 — FORWARD VIEW  (user inputs, forward curve)
#     # ══════════════════════════════════════════════════════════════════════════
#     with tab_fwd:
#         st.markdown(
#             "<div style='background:#2A1F08;border:1px solid #E8A020;"
#             "border-radius:6px;padding:8px 14px;font-size:12px;color:#E8A020;"
#             "margin-bottom:12px'>📐 <b>FORWARD MODEL</b> — adjust inputs below "
#             "to model future margin scenarios. Today's live prices are the default "
#             "starting point.</div>",
#             unsafe_allow_html=True)

#         # ── Input panels ──────────────────────────────────────────────────────
#         with st.expander("⚙️ Price & Yield Assumptions", expanded=True):
#             if st.button("↺ Reset to Today's Live Prices", key=f"fwd_reset_{n}"):
#                 spec2 = sheet_prices.get(n, {})
#                 ulsd2 = live_spot.get("ulsd_gal",3.5) or 3.5
#                 wti2  = live_spot.get("wti_bbl",80) or 80
#                 st.session_state.update({
#                     f"fwd_wti_{n}":     wti2,
#                     f"fwd_rbob_{n}":    live_spot.get("rbob_gal",2.5) or 2.5,
#                     f"fwd_ulsd_{n}":    ulsd2,
#                     f"fwd_jet_{n}":     spec2.get("jet_gal",   ulsd2*1.05),
#                     f"fwd_bunker_{n}":  spec2.get("bunker_gal",ulsd2*0.70),
#                     f"fwd_asphalt_{n}": spec2.get("asphalt_gal",ulsd2*0.60),
#                     f"fwd_lpg_{n}":     spec2.get("lpg_gal",   round(wti2*0.50/42,3)),
#                     f"fwd_dist_{n}":    0.35,
#                     f"fwd_fcd_{n}":     0.0,
#                     f"fwd_fgd_{n}":     0.0,
#                     f"fwd_fdd_{n}":     0.0,
#                 })
#                 st.rerun()

#             st.markdown("**Market Price Assumptions**")
#             p1,p2,p3,p4 = st.columns(4)
#             st.session_state[f"fwd_wti_{n}"]    = p1.number_input(
#                 "WTI ($/bbl)",20.0,200.0,
#                 float(st.session_state[f"fwd_wti_{n}"]),0.25,"%.2f",key=f"fp_wti_{n}")
#             st.session_state[f"fwd_rbob_{n}"]   = p2.number_input(
#                 "RBOB ($/gal)",0.5,10.0,
#                 float(st.session_state[f"fwd_rbob_{n}"]),0.01,"%.3f",key=f"fp_rbob_{n}")
#             st.session_state[f"fwd_ulsd_{n}"]   = p3.number_input(
#                 "ULSD ($/gal)",0.5,10.0,
#                 float(st.session_state[f"fwd_ulsd_{n}"]),0.01,"%.3f",key=f"fp_ulsd_{n}")
#             st.session_state[f"fwd_dist_{n}"]   = p4.number_input(
#                 "Dist Margin ($/gal)",0.0,1.0,
#                 float(st.session_state[f"fwd_dist_{n}"]),0.01,"%.2f",key=f"fp_dist_{n}")

#             st.markdown("**Specialty Product Prices** (used as flat forward assumption)")
#             sp1,sp2,sp3,sp4 = st.columns(4)
#             st.session_state[f"fwd_jet_{n}"]    = sp1.number_input(
#                 "Jet Fuel ($/gal)",0.5,15.0,
#                 float(st.session_state[f"fwd_jet_{n}"]),0.01,"%.3f",key=f"fp_jet_{n}")
#             st.session_state[f"fwd_bunker_{n}"] = sp2.number_input(
#                 "Bunker ($/gal)",0.2,10.0,
#                 float(st.session_state[f"fwd_bunker_{n}"]),0.01,"%.3f",key=f"fp_bnk_{n}")
#             st.session_state[f"fwd_asphalt_{n}"]= sp3.number_input(
#                 "Asphalt ($/gal)",0.1,8.0,
#                 float(st.session_state[f"fwd_asphalt_{n}"]),0.01,"%.3f",key=f"fp_asp_{n}")
#             st.session_state[f"fwd_lpg_{n}"]    = sp4.number_input(
#                 "LPG/Other ($/gal)",0.1,5.0,
#                 float(st.session_state[f"fwd_lpg_{n}"]),0.01,"%.3f",key=f"fp_lpg_{n}")

#             st.markdown("**Location Differentials**")
#             d1,d2,d3,d4,d5 = st.columns(5)
#             st.session_state[f"fwd_fcd_{n}"] = d1.number_input(
#                 "Crude diff ($/bbl)",-15.0,15.0,
#                 float(st.session_state[f"fwd_fcd_{n}"]),0.25,"%.2f",key=f"fp_fcd_{n}")
#             st.session_state[f"fwd_fgd_{n}"] = d2.number_input(
#                 "Gas diff ($/gal)",-1.0,1.0,
#                 float(st.session_state[f"fwd_fgd_{n}"]),0.01,"%.3f",key=f"fp_fgd_{n}")
#             st.session_state[f"fwd_fdd_{n}"] = d3.number_input(
#                 "Diesel diff ($/gal)",-1.0,1.0,
#                 float(st.session_state[f"fwd_fdd_{n}"]),0.01,"%.3f",key=f"fp_fdd_{n}")
#             st.session_state[f"fwd_tp_{n}"]  = int(d4.number_input(
#                 "Throughput (bbl/day)",0,200000,
#                 int(st.session_state[f"fwd_tp_{n}"]),1000,key=f"fp_tp_{n}"))
#             loc_cfg = next((l for l in LOCATIONS if l["display"]==n),{})
#             d5.markdown(
#                 f"<div style='padding-top:26px;font-size:10px;color:#8B949E'>"
#                 f"Config crude diff:<br>"
#                 f"Light {loc_cfg.get('light_diff',0):+.2f} · "
#                 f"Heavy {loc_cfg.get('heavy_diff',0):+.2f}</div>",
#                 unsafe_allow_html=True)

#             st.markdown("**Yield Configuration (%)**")
#             YLBLS = {
#                 "gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#                 "bunker":"Bunker","asphalt":"Asphalt",
#                 "lpg_other":"LPG/Other","refinery_use":"Ref. Use",
#             }
#             ycols = st.columns(7)
#             total_y = 0.0
#             for i,(k,lbl) in enumerate(YLBLS.items()):
#                 default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#                 val = ycols[i].number_input(
#                     f"{lbl} (%)",0.0,100.0,
#                     float(st.session_state.get(f"fwd_y_{k}_{n}",default)),
#                     0.5,"%.1f",key=f"fp_y_{k}_{n}")
#                 st.session_state[f"fwd_y_{k}_{n}"] = val
#                 total_y += val
#             yc = "#3FB950" if total_y<=100 else "#F85149"
#             st.markdown(
#                 f"<span style='color:{yc};font-size:11px'>Total: {total_y:.1f}%</span>",
#                 unsafe_allow_html=True)

#         # ── Compute forward crack with these inputs ───────────────────────────
#         fwd_yields = {k: round(st.session_state.get(f"fwd_y_{k}_{n}",
#                        YIELD_DEFAULTS.get(k,0)*100)/100, 6)
#                       for k in YIELD_DEFAULTS}
#         loc_cfg  = next((l for l in LOCATIONS if l["display"]==n), {})
#         crude_diff_total = (st.session_state[f"fwd_fcd_{n}"] +
#                             loc_cfg.get("light_diff", 0))

#         loc_fwd = compute_forward_crack(
#             strip       = strip,
#             crude_diff  = crude_diff_total,
#             gas_diff    = st.session_state[f"fwd_fgd_{n}"] + loc_cfg.get("gas_diff",0),
#             diesel_diff = st.session_state[f"fwd_fdd_{n}"] + loc_cfg.get("diesel_diff",0),
#             jet_fwd     = st.session_state[f"fwd_jet_{n}"],
#             bunker_fwd  = st.session_state[f"fwd_bunker_{n}"],
#             asphalt_fwd = st.session_state[f"fwd_asphalt_{n}"],
#             lpg_fwd     = st.session_state[f"fwd_lpg_{n}"],
#             yields      = fwd_yields,
#         )

#         if not loc_fwd:
#             st.info("Forward curve data not available. Check CME connection.")
#         else:
#             fwd_ok   = [row for row in loc_fwd if row.get("crack_321")]
#             months   = [row["month"]      for row in fwd_ok]
#             wti_fwd  = [row["wti"]        for row in fwd_ok]
#             rbob_f   = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f   = [row.get("ulsd",0) for row in fwd_ok]
#             crack_vals= [row.get("crack_321") for row in fwd_ok]
#             full_vals = [row.get("crack_full") for row in fwd_ok]

#             y_g2 = fwd_yields.get("gasoline",  0.445)
#             y_d2 = fwd_yields.get("ulsd",      0.290)
#             y_j2 = fwd_yields.get("jet",       0.110)
#             y_b2 = fwd_yields.get("bunker",    0.035)
#             y_a2 = fwd_yields.get("asphalt",   0.025)
#             y_l2 = fwd_yields.get("lpg_other", 0.040)

#             gas_rev = [round((rb or 0)*y_g2*42,2) for rb in rbob_f]
#             die_rev = [round((ul or 0)*y_d2*42,2) for ul in ulsd_f]
#             jet_rev = [round(st.session_state[f"fwd_jet_{n}"]*y_j2*42,2)]*len(months)
#             bnk_rev = [round(st.session_state[f"fwd_bunker_{n}"]*y_b2*42,2)]*len(months)
#             asp_rev = [round(st.session_state[f"fwd_asphalt_{n}"]*y_a2*42,2)]*len(months)
#             lpg_rev = [round(st.session_state[f"fwd_lpg_{n}"]*y_l2*42,2)]*len(months)

#             # ── Area chart ────────────────────────────────────────────────────
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
#             for name,vals in [
#                 ("Gasoline",  gas_rev),
#                 ("Diesel",    die_rev),
#                 ("Jet Fuel",  jet_rev),
#                 ("Bunker",    bnk_rev),
#                 ("Asphalt",   asp_rev),
#                 ("LPG/Other", lpg_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one", line=dict(width=0)))
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost ($/bbl)",
#                 line=dict(color="#FFFFFF",width=2.5), mode="lines"))
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149",width=2,dash="dot"),
#                 yaxis="y2"))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D",tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="3-2-1 Crack ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y",side="right",showgrid=False,
#                     tickfont=dict(color="#F85149")),
#                 legend=dict(bgcolor="#161B22",font=dict(size=10),
#                             orientation="h",yanchor="bottom",y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0),height=380,
#                 hovermode="x unified")
#             if months and wti_fwd:
#                 fig_fwd.add_annotation(
#                     x=months[len(months)//2],
#                     y=wti_fwd[len(wti_fwd)//2]+5,
#                     text="↑ Gap = Margin",
#                     showarrow=False,
#                     font=dict(color="#FFFFFF",size=10),
#                     bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = product revenue · White line = crude cost · "
#                 "Gap above white line = refinery margin · "
#                 "Red dashed (right axis) = 3-2-1 crack spread")

#             # ── Forward stress ±20% ───────────────────────────────────────────
#             fov = [v for v in full_vals if v is not None]
#             fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
#             if fov:
#                 fwd_dn = compute_forward_crack(
#                     strip=strip,
#                     crude_diff  = crude_diff_total+(wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff    = st.session_state[f"fwd_fgd_{n}"]-0.20,
#                     diesel_diff = st.session_state[f"fwd_fdd_{n}"]-0.20,
#                     jet_fwd     = st.session_state[f"fwd_jet_{n}"]*0.80,
#                     bunker_fwd  = st.session_state[f"fwd_bunker_{n}"]*0.80,
#                     asphalt_fwd = st.session_state[f"fwd_asphalt_{n}"]*0.80,
#                     lpg_fwd     = st.session_state[f"fwd_lpg_{n}"]*0.80,
#                     yields      = fwd_yields)
#                 fwd_up = compute_forward_crack(
#                     strip=strip,
#                     crude_diff  = crude_diff_total-(wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff    = st.session_state[f"fwd_fgd_{n}"]+0.20,
#                     diesel_diff = st.session_state[f"fwd_fdd_{n}"]+0.20,
#                     jet_fwd     = st.session_state[f"fwd_jet_{n}"]*1.20,
#                     bunker_fwd  = st.session_state[f"fwd_bunker_{n}"]*1.20,
#                     asphalt_fwd = st.session_state[f"fwd_asphalt_{n}"]*1.20,
#                     lpg_fwd     = st.session_state[f"fwd_lpg_{n}"]*1.20,
#                     yields      = fwd_yields)
#                 sdn  = [row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
#                 sup  = [row.get("crack_full") for row in fwd_up if row.get("crack_full")]
#                 mdn  = [row["month"] for row in fwd_dn if row.get("crack_full")]
#                 mup  = [row["month"] for row in fwd_up if row.get("crack_full")]

#                 st.markdown("<div class='sec-hdr'>Forward GRM Stress Test ±20%</div>",
#                             unsafe_allow_html=True)
#                 fig_st = go.Figure()
#                 if sdn and len(sdn)==len(fov):
#                     fig_st.add_trace(go.Scatter(
#                         x=mdn+mdn[::-1], y=sdn+fov[::-1],
#                         fill="toself",fillcolor="rgba(248,81,73,0.12)",
#                         line=dict(width=0),name="Downside −20%",hoverinfo="skip"))
#                 if sup and len(sup)==len(fov):
#                     fig_st.add_trace(go.Scatter(
#                         x=mup+mup[::-1], y=sup+fov[::-1],
#                         fill="toself",fillcolor="rgba(63,185,80,0.10)",
#                         line=dict(width=0),name="Upside +20%",hoverinfo="skip"))
#                 fig_st.add_trace(go.Scatter(
#                     x=fmo, y=fov,
#                     name="Full Yield GRM — Base",
#                     line=dict(color="#E8A020",width=2.5),
#                     mode="lines+markers",marker=dict(size=5)))
#                 if sdn:
#                     fig_st.add_trace(go.Scatter(
#                         x=mdn, y=sdn, name="Downside",
#                         line=dict(color="#F85149",width=1.5,dash="dash")))
#                 if sup:
#                     fig_st.add_trace(go.Scatter(
#                         x=mup, y=sup, name="Upside",
#                         line=dict(color="#3FB950",width=1.5,dash="dash")))
#                 fig_st.add_hline(y=15,line_dash="dot",line_color="#8B949E",
#                     opacity=0.5,
#                     annotation_text="~Breakeven $15/bbl",
#                     annotation_font_color="#8B949E",
#                     annotation_font_size=9)
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
#                     "Base = Full Yield GRM at current inputs · "
#                     "Red = downside (crude +20%, products −20%) · "
#                     "Green = upside (crude −20%, products +20%)")

#             # ── Forward GRM table + download ──────────────────────────────────
#             fwd_tp = st.session_state[f"fwd_tp_{n}"]
#             grm_fwd_list = [round(v*fwd_tp*30/1e6,2) if v else None
#                             for v in crack_vals]
#             fwd_df = pd.DataFrame({
#                 "Month":             months,
#                 "WTI ($/bbl)":       wti_fwd,
#                 "3-2-1 GRM ($/bbl)": crack_vals,
#                 "Full Yield ($/bbl)":full_vals,
#                 f"GRM ($MM/mo @ {fwd_tp//1000}k bbl/d)": grm_fwd_list,
#             })
#             with st.expander("📋 Forward GRM Table"):
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
#     with st.expander("📋 Methodology & Data Sources — Audit Reference",
#                      expanded=False):
#         st.markdown("""
# <div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

# ### What this tool calculates

# **Gross Refining Margin (GRM)** is the difference between the market value of
# refined products produced from one barrel of crude oil and the cost of that crude.
# It is a *gross* margin — operating costs ($4–8/bbl) are **not deducted**.

# GRM = Σ(Product Price × Yield Fraction × 42) − Crude Cost

# ---

# ### Two views — Today vs Forward

# **Today tab:** 100% live data. Gas & diesel from AAA daily survey, crude from
# CME first-month settle, specialty products from Google Sheet (updated weekly).
# No user inputs. Every number is the market as of right now.

# **Forward tab:** User-driven model. Starts with today's live prices as defaults.
# Adjust any assumption to model future margin scenarios. CME forward strip drives
# WTI/RBOB/ULSD for months 2–24. Jet/bunker/asphalt/LPG held flat at user input.

# ---

# ### Price sources

# | Input | Source | Frequency |
# |---|---|---|
# | Retail gas & diesel | AAA Fuel Gauge (metro daily) | Daily |
# | WTI, RBOB, ULSD spot | CME first-month settle | Daily |
# | WTI, RBOB, ULSD forward | CME settle strip (local xlsx) | Daily |
# | Jet, Bunker, Asphalt, LPG | Google Sheet (per location) | Weekly |
# | Federal excise tax | IRS — unchanged since Oct 1993 | Static |
# | State excise taxes | FTA + EIA, Jul 2025 | Semiannual |

# ---

# ### Price waterfall
# ```
# Retail pump price (AAA)
#   − Federal excise:  $0.184/gal gas · $0.244/gal diesel
#   − State excise:    varies by state
#   = Pre-tax price
#   − Distribution:    $0.35/gal default
#   = Wholesale / refinery gate price
# ```

# ---

# ### State excise taxes (Jul 2025)

# | State | Gas | Diesel |
# |---|---|---|
# | AK | $0.0895 | $0.0895 |
# | TX | $0.200 | $0.200 |
# | OK | $0.190 | $0.190 |
# | ND | $0.230 | $0.230 |
# | UT | $0.385 | $0.385 |
# | LA | $0.200 | $0.200 |
# | NM | $0.229 | $0.270 |

# ---

# ### Full Yield defaults (EIA 2024)

# | Product | % | Notes |
# |---|---|---|
# | Gasoline | 44.5% | EIA 2024 national avg |
# | Diesel | 29.0% | EIA 2024 |
# | Jet Fuel | 11.0% | Record high 2024 |
# | Bunker | 3.5% | Conservative |
# | Asphalt | 2.5% | Road oil |
# | LPG/Other | 4.0% | Propane, naphtha |
# | Refinery Use | 5.5% | Fuel gas + losses |
# | **Total** | **100%** | Fully accounted |

# Source: EIA Petroleum Supply Monthly 2024 (eia.gov/todayinenergy/detail.php?id=64786)

# ---

# ### What this tool does NOT capture
# Operating costs ($3–8/bbl) · RIN obligations · Blendstock costs ·
# Pipeline tariffs · Carbon costs · Hedging gains/losses

# </div>
# """, unsafe_allow_html=True)


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
#             get_cme.clear()
#             get_spot.clear()
#             get_lp.clear()
#             get_spec.clear()
#             get_specialty_sheet.clear()
#             # Clear session state except auth
#             auth = st.session_state.get("auth")
#             for k in list(st.session_state.keys()):
#                 del st.session_state[k]
#             if auth:
#                 st.session_state["auth"] = auth
#             st.rerun()
#         st.markdown("---")
#         st.caption(
#             "**Today tab:** live prices — read only.\n\n"
#             "**Forward tab:** adjust inputs to model future scenarios.\n\n"
#             "Specialty prices (jet/bunker/asphalt/LPG) updated weekly "
#             "via Google Sheet.")

#     # Fetch all data
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
#         f"AAA Fuel Gauge · EIA API · CME local xlsx · "
#         f"Specialty via Google Sheet · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()



