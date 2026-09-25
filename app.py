# app.py — Rogue Refinery Economics v4 — LPG/Other fully wired
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
    """Scroll the Streamlit app to the top on page transition."""
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
#MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
.block-container{padding-top:0.3rem !important;padding-bottom:0 !important}
[data-testid="stAppViewContainer"]>[data-testid="stVerticalBlock"]{padding-top:0 !important}
h2{margin-top:0 !important}
[data-testid="stSidebar"]{background:#161B22}
div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;border-radius:8px}
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
@st.cache_data(ttl=3600)
def get_cme():  return fetch_cme_forward_curve()

@st.cache_data(ttl=3600)
def get_spot(): return fetch_spot_prices(EIA_API_KEY)

@st.cache_data(ttl=3600)
def get_lp():   return fetch_location_prices(LOCATIONS)

@st.cache_data(ttl=86400)
def get_spec(): return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# ── Session state init ─────────────────────────────────────────────────────────
def init_state():
    if st.session_state.get("_init"): return
    live = get_spot()
    spec = get_spec()
    ulsd = live.get("ulsd_gal", 3.50) or 3.50
    wti  = live.get("wti_bbl",  80.0) or 80.0
    st.session_state.update({
        "wti":       wti,
        "rbob":      live.get("rbob_gal", 2.50) or 2.50,
        "ulsd":      ulsd,
        "jet":       spec.get("jet_gal")     or ulsd * 1.05,
        "bunker":    spec.get("bunker_gal")  or ulsd * 0.70,
        "asphalt":   spec.get("asphalt_gal") or ulsd * 0.60,
        # LPG default: Mont Belvieu propane proxy ≈ WTI × 0.50 ÷ 42
        "lpg":       round(wti * 0.50 / 42, 3),
        "dist":      0.35,
        "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
        "view":      "portfolio",
        "sel_loc":   None,
        "calc_mode": False,
    })
    for k, v in YIELD_DEFAULTS.items():
        st.session_state[f"y_{k}"] = round(v * 100, 1)
    for loc in LOCATIONS:
        n = loc["display"]
        st.session_state[f"lc_{n}"]  = loc.get("light_diff",   0.0)
        st.session_state[f"lh_{n}"]  = loc.get("heavy_diff",   0.0)
        st.session_state[f"lcf_{n}"] = loc.get("catfeed_diff", 0.0)
        st.session_state[f"lg_{n}"]  = loc.get("gas_diff",     0.0)
        st.session_state[f"ld_{n}"]  = loc.get("diesel_diff",  0.0)
        st.session_state[f"lj_{n}"]  = 0.0
        st.session_state[f"tp_{n}"]  = loc.get("throughput",   30000)
    st.session_state["_init"] = True


# ── Build margins ──────────────────────────────────────────────────────────────
def build_margins(lp, loc_overrides=None):
    """
    LIVE MODE  (calc_mode=False):
      Gas/Diesel wholesale from AAA retail → strip taxes & dist margin.
      Crude/specialty from CME first-month settle / EIA.
    SCENARIO MODE  (calc_mode=True):
      All prices from session state — AAA bypassed.
      RBOB/ULSD used directly as wholesale proxy.
    Both modes: yields and location diffs from session state.
    """
    calc_mode = st.session_state.get("calc_mode", False)
    spot = {
        "wti_bbl":  st.session_state["wti"],
        "rbob_gal": st.session_state["rbob"],
        "ulsd_gal": st.session_state["ulsd"],
    }
    spec = {
        "jet_gal":     st.session_state["jet"],
        "bunker_gal":  st.session_state["bunker"],
        "asphalt_gal": st.session_state["asphalt"],
        "lpg_gal":     st.session_state["lpg"],      # ← NEW
    }
    yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
              for k, v in YIELD_DEFAULTS.items()}
    dist = st.session_state["dist"]

    locs = loc_overrides or []
    if not locs:
        for loc in LOCATIONS:
            n = loc["display"]
            o = dict(loc)
            o["light_diff"]   = st.session_state.get(f"lc_{n}", loc.get("light_diff",0))
            o["heavy_diff"]   = st.session_state.get(f"lh_{n}", loc.get("heavy_diff",0))
            o["catfeed_diff"] = st.session_state.get(f"lcf_{n}",loc.get("catfeed_diff",0))
            o["gas_diff"]     = st.session_state.get(f"lg_{n}", loc.get("gas_diff",0))
            o["diesel_diff"]  = st.session_state.get(f"ld_{n}", loc.get("diesel_diff",0))
            o["throughput"]   = st.session_state.get(f"tp_{n}", 30000)
            locs.append(o)

    if calc_mode:
        from engine.location_margins import STATE_TAXES, FEDERAL_TAX_GAS, FEDERAL_TAX_DIESEL
        synthetic_lp = {}
        for loc in locs:
            display = loc["display"]
            state   = loc.get("aaa_state","")
            rbob    = st.session_state["rbob"] + loc.get("gas_diff",0)
            ulsd    = st.session_state["ulsd"] + loc.get("diesel_diff",0)
            st_gas  = STATE_TAXES.get(state,{}).get("gas",    0.30)
            st_die  = STATE_TAXES.get(state,{}).get("diesel", 0.30)
            synthetic_lp[display] = {
                "regular": round(rbob + FEDERAL_TAX_GAS    + st_gas  + dist, 3),
                "diesel":  round(ulsd + FEDERAL_TAX_DIESEL + st_die  + dist, 3),
                "source":  "Scenario — NYMEX-derived",
            }
        margins = compute_location_margins(
            locations=locs, spot_prices=spot,
            location_prices=synthetic_lp,
            specialty=spec, yields=yields,
            dist_margin_gal=dist)
        for r in margins:
            r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
            r["pnl"]        = fmt_grm(r.get("spread_321"), r["throughput"])
            r["price_mode"] = "scenario"
    else:
        margins = compute_location_margins(
            locations=locs, spot_prices=spot, location_prices=lp,
            specialty=spec, yields=yields, dist_margin_gal=dist)
        for r in margins:
            r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
            r["pnl"]        = fmt_grm(r.get("spread_321"), r["throughput"])
            r["price_mode"] = "live"

    return margins, spot, yields


# ── Ticker ─────────────────────────────────────────────────────────────────────
def render_ticker(spot, margins):
    wti  = spot.get("wti_bbl")
    rbob = spot.get("rbob_gal")
    ulsd = spot.get("ulsd_gal")
    live = get_spot()
    wti_l = live.get("wti_bbl")
    delta = ""
    if wti and wti_l:
        d = round(wti - wti_l, 2)
        delta = (f"<span style='color:#3FB950'>▲${d:.2f} vs live</span>"
                 if d >= 0 else
                 f"<span style='color:#F85149'>▼${abs(d):.2f} vs live</span>")
    spreads   = [r["spread_321"] for r in margins if r.get("spread_321")]
    pavg      = round(sum(spreads)/len(spreads),2) if spreads else None
    total_pnl = sum(r["pnl"] for r in margins if r.get("pnl"))
    pc = spread_color(pavg)
    st.markdown(f"""
    <div class="ticker-bar">
      <div class="ticker-item">
        <span class="ticker-label">WTI Crude</span>
        <span class="ticker-value">{fmt_bbl(wti)}</span>
        <span class="ticker-label">{delta}</span>
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
        <span class="ticker-label">×42 gal/bbl</span>
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
          {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
        </span>
        <span class="ticker-label">before opex</span>
      </div>
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — COMMAND VIEW
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
    "Edmonton, Alberta":        (53.55,-113.49),
    "Puerto Rico":              (18.22, -66.59),
}

def show_command(margins):
    valid = [r for r in margins if r.get("spread_321")]
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
            <div class='mc-sub'>at current throughput · before opex</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # Map
    st.markdown("<div class='sec-hdr'>Portfolio Map</div>", unsafe_allow_html=True)
    map_rows = []
    for r in margins:
        c = LOC_COORDS.get(r["display"], (39.5,-98.35))
        s = r.get("spread_321")
        map_rows.append({
            "name": r["display"],
            "short": r["display"].split("—")[-1].split(",")[0].strip(),
            "lat": c[0], "lon": c[1], "spread": s, "color": spread_color(s),
            "pnl": r.get("pnl"),
            "hover": (
                f"<b>{r['display']}</b><br>"
                f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
                f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
                f"GRM: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
                f"<i>Click card below to drill in</i>"
            ),
        })
    df_m = pd.DataFrame(map_rows)
    fig_m = go.Figure()
    fig_m.add_trace(go.Scattergeo(
        lat=df_m["lat"], lon=df_m["lon"], mode="markers+text",
        marker=dict(size=20, color=df_m["color"].tolist(),
                    line=dict(width=2, color="#0D1117"), opacity=0.90),
        text=df_m["short"], textposition="top center",
        textfont=dict(size=10, color="#E6EDF3"),
        hovertext=df_m["hover"], hoverinfo="text"))
    for _, row in df_m.iterrows():
        if row["spread"]:
            fig_m.add_trace(go.Scattergeo(
                lat=[row["lat"]-1.9], lon=[row["lon"]], mode="text",
                text=[f"${row['spread']:.0f}"],
                textfont=dict(size=10, color=row["color"], family="monospace"),
                hoverinfo="skip", showlegend=False))
    fig_m.update_layout(
        geo=dict(scope="world", showland=True, landcolor="#1C2128",
                 showocean=True, oceancolor="#0D1117",
                 showlakes=True, lakecolor="#0D1117",
                 showcountries=True, countrycolor="#30363D",
                 showcoastlines=True, coastlinecolor="#30363D",
                 showframe=False, bgcolor="#0D1117",
                 center=dict(lat=45, lon=-100), projection_scale=1.4,
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
        ("Edmonton, Alberta",      "Edmonton",      "CA"),
        ("Puerto Rico",            "Puerto Rico",   "PR"),
    ]

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
            <div class='loc-card-pnl'>{pnl_s} · {r.get("source","").split("—")[-1][:12]}</div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open →", key=btn_key, use_container_width=True):
            st.session_state["view"]    = "detail"
            st.session_state["sel_loc"] = r["display"]
            st.rerun()

    margin_map = {r["display"]: r for r in margins}

    st.markdown("<div class='sec-hdr'>In Construction</div>", unsafe_allow_html=True)
    constr = [r for r in margins if r["display"] in IN_CONSTRUCTION]
    cc = st.columns(4)
    for i,r in enumerate(constr):
        with cc[i%4]: _render_card(r, f"btn_con_{i}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<div class='sec-hdr'>Development Locations</div>", unsafe_allow_html=True)
    dev_items = [(dn,sl,st_) for dn,sl,st_ in DEVELOPMENT_ORDER if dn in margin_map]
    dc = st.columns(4)
    for i,(dn,sl,st_) in enumerate(dev_items):
        with dc[i%4]: _render_card(margin_map[dn], f"btn_dev_{i}")

    # Portfolio download
    st.markdown("---")
    st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
                unsafe_allow_html=True)
    jet_p  = st.session_state.get("jet",     4.07)
    bnk_p  = st.session_state.get("bunker",  2.52)
    asp_p  = st.session_state.get("asphalt", 2.16)
    lpg_p  = st.session_state.get("lpg",     0.95)
    dl_rows = []
    for r in margins:
        n  = r["display"]
        tp = r.get("throughput",30000)
        gm = fmt_grm(r.get("spread_321"), tp)
        dl_rows.append({
            "Location":                  n,
            "Price Source":              r.get("source","—"),
            "Throughput (bbl/day)":      tp,
            "Light Crude ($/bbl)":       r.get("crude_light"),
            "Heavy Crude ($/bbl)":       r.get("crude_heavy"),
            "Cat Feed / HGO ($/bbl)":    r.get("crude_catfeed"),
            "Gasoline - Retail":         r.get("retail_gas"),
            "Gasoline - Federal Tax":    r.get("federal_tax_gas"),
            "Gasoline - State Tax":      r.get("state_tax_gas"),
            "Gasoline - Pre-tax":        r.get("pretax_gas"),
            "Gasoline - Dist Margin":    r.get("dist_margin"),
            "Gasoline - Wholesale":      r.get("wholesale_gas"),
            "Diesel - Retail":           r.get("retail_diesel"),
            "Diesel - Pre-tax":          r.get("pretax_diesel"),
            "Diesel - Wholesale":        r.get("wholesale_diesel"),
            "Jet Fuel ($/gal)":          jet_p,
            "Bunker Fuel ($/gal)":       bnk_p,
            "Asphalt ($/gal)":           asp_p,
            "LPG / Other ($/gal)":       lpg_p,
            "3-2-1 Spread ($/bbl)":      r.get("spread_321"),
            "2-1-1 Spread ($/bbl)":      r.get("spread_211"),
            "5-3-2 Spread ($/bbl)":      r.get("spread_532"),
            "Full Yield GRM ($/bbl)":    r.get("spread_full"),
            "Monthly GRM ($MM)":         gm,
            "Annual GRM ($MM)":          round(gm*12,2) if gm else None,
            "As Of":                     datetime.now().strftime("%Y-%m-%d %H:%M"),
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
            "Location","Light Crude ($/bbl)","Heavy Crude ($/bbl)",
            "Gasoline - Retail","Gasoline - Wholesale",
            "Diesel - Retail","Diesel - Wholesale",
            "Jet Fuel ($/gal)","Bunker Fuel ($/gal)",
            "Asphalt ($/gal)","LPG / Other ($/gal)",
            "3-2-1 Spread ($/bbl)","Full Yield GRM ($/bbl)","Monthly GRM ($MM)",
        ]], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — LOCATION DETAIL
# ══════════════════════════════════════════════════════════════════════════════
def show_detail(margins, strip, yields, lp):
    _scroll_top()
    sel = st.session_state.get("sel_loc")
    fresh_margins, spot_fresh, yields_fresh = build_margins(lp)
    margins = fresh_margins
    yields  = yields_fresh
    r = next((m for m in margins if m["display"]==sel), None)

    bc,tc = st.columns([1,8])
    with bc:
        if st.button("← Portfolio"):
            st.session_state["view"] = "portfolio"
            st.rerun()
    with tc:
        s321_hdr = r.get("spread_321") if r else None
        clr_hdr  = spread_color(s321_hdr)
        short_hdr= sel.split("—")[-1].split(",")[0].strip() if sel else "—"
        st.markdown(
            f"<h3 style='color:#E6EDF3;margin:0'>{short_hdr} &nbsp;"
            f"<span style='color:{clr_hdr};font-family:monospace'>"
            f"{'$'+str(s321_hdr)+'/bbl' if s321_hdr else '—'}</span>&nbsp;"
            f"<span style='font-size:14px;color:{clr_hdr}'>{spread_label(s321_hdr)}</span>"
            f"</h3>", unsafe_allow_html=True)

    if not r:
        st.warning("No data for this location.")
        return

    # Pre-pull n for keying widgets
    n     = sel
    short = short_hdr
    st.markdown("---")

    # ─── PANEL A ──────────────────────────────────────────────────────────────
    with st.expander("📊 Current Margin Snapshot", expanded=True):
        tp   = r.get("throughput", 30000)

        # Mode toggle
        mc1,mc2 = st.columns([3,1])
        with mc2:
            calc_mode = st.toggle(
                "Scenario Mode",
                value=st.session_state.get("calc_mode",False),
                key="mode_toggle",
                help=("OFF = Live Market: AAA daily prices stripped to wholesale. "
                      "ON = Scenario: all prices from calculator inputs below."))
            if calc_mode != st.session_state.get("calc_mode",False):
                st.session_state["calc_mode"] = calc_mode
                st.rerun()
        with mc1:
            if st.session_state.get("calc_mode",False):
                st.markdown(
                    "<div style='background:#2A1F08;border:1px solid #E8A020;"
                    "border-radius:6px;padding:8px 14px;font-size:12px;color:#E8A020'>"
                    "⚡ <b>SCENARIO MODE</b> — prices from calculator · not live market data"
                    "</div>", unsafe_allow_html=True)
            else:
                st.markdown(
                    "<div style='background:#0D2A1A;border:1px solid #3FB950;"
                    "border-radius:6px;padding:8px 14px;font-size:12px;color:#3FB950'>"
                    "✅ <b>LIVE MARKET</b> — gas & diesel from AAA daily · crude from CME · specialty from EIA"
                    "</div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # Rebuild with current mode
        fm2,_,yields2 = build_margins(lp)
        r2     = next((m for m in fm2 if m["display"]==sel), r)
        s321   = r2.get("spread_321")
        sfull  = r2.get("spread_full")
        s211   = r2.get("spread_211")
        s532   = r2.get("spread_532")
        yields = yields2

        # Prices for contribution calc
        ws_g   = r2.get("wholesale_gas",   0.0) or 0
        ws_d   = r2.get("wholesale_diesel", 0.0) or 0
        jet_p  = st.session_state.get("jet",     4.07)
        bnk_p  = st.session_state.get("bunker",  2.52)
        asp_p  = st.session_state.get("asphalt", 2.16)
        lpg_p  = st.session_state.get("lpg",     0.95)
        cr_    = r2.get("crude_light", 0.0) or 0

        y_g    = yields.get("gasoline",    0.445)
        y_d    = yields.get("ulsd",        0.290)
        y_j    = yields.get("jet",         0.110)
        y_b    = yields.get("bunker",      0.035)
        y_a    = yields.get("asphalt",     0.025)
        y_l    = yields.get("lpg_other",   0.040)  # ← NEW
        y_ru   = yields.get("refinery_use",0.055)

        _sal   = y_g + y_d + y_j + y_b + y_a + y_l
        _total = _sal + y_ru
        _check = round(1.0 - _total, 3)   # should be ~0 or tiny rounding

        gc_ = round(ws_g  * y_g * 42, 2)
        dc_ = round(ws_d  * y_d * 42, 2)
        jc_ = round(jet_p * y_j * 42, 2)
        bc_ = round(bnk_p * y_b * 42, 2)
        ac_ = round(asp_p * y_a * 42, 2)
        lc_ = round(lpg_p * y_l * 42, 2)  # ← NEW
        total_rev  = gc_ + dc_ + jc_ + bc_ + ac_ + lc_
        grm_full   = round(total_rev - cr_, 2)
        pnl_v      = fmt_grm(s321, tp)

        # Row 1: Headline cards
        h1,h2,h3,h4 = st.columns(4)
        h1.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Refinery Crack Spread</div>
            <div class='mc-value' style='color:{spread_color(grm_full)};font-size:22px'>
                {"$"+str(grm_full)+"/bbl" if grm_full else "—"}</div>
            <div class='mc-sub'>Full Yield GRM · {round(_sal*100,1)}% saleable bbl</div>
        </div>""", unsafe_allow_html=True)
        h2.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>3-2-1 Reference Spread</div>
            <div class='mc-value' style='color:{spread_color(s321)};font-size:22px'>
                {"$"+str(s321)+"/bbl" if s321 else "—"}</div>
            <div class='mc-sub'>100% bbl · 2 gas + 1 diesel benchmark</div>
        </div>""", unsafe_allow_html=True)
        h3.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>GRM / Month</div>
            <div class='mc-value' style='color:#3FB950;font-size:22px'>
                {"$"+str(pnl_v)+"MM" if pnl_v else "—"}</div>
            <div class='mc-sub'>{f"{tp:,} bbl/day · Full Yield basis"}</div>
        </div>""", unsafe_allow_html=True)
        h4.markdown(f"""<div class='metric-card'>
            <div class='mc-label'>Annual GRM Run-Rate</div>
            <div class='mc-value' style='color:#3FB950;font-size:22px'>
                {"$"+str(round(pnl_v*12,1))+"MM" if pnl_v else "—"}</div>
            <div class='mc-sub'>{f"at {tp:,} bbl/day"}</div>
        </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Row 2: Product contribution cards (6 products)
        st.markdown(
            "<div class='sec-hdr'>Where Does the Margin Come From? — "
            "Product Contribution to Full Yield GRM</div>",
            unsafe_allow_html=True)

        PRODUCTS = [
            ("Gasoline", gc_, y_g, "#4A90D9"),
            ("Diesel",   dc_, y_d, "#E8A020"),
            ("Jet Fuel", jc_, y_j, "#5A9E3A"),
            ("Bunker",   bc_, y_b, "#8B4FBF"),
            ("Asphalt",  ac_, y_a, "#CC7722"),
            ("LPG/Other",lc_, y_l, "#3AA6B9"),  # ← NEW
        ]

        pcols = st.columns(6)
        for col,(name,rev,yld,clr) in zip(pcols, PRODUCTS):
            crude_alloc = round(cr_ * (yld/_sal) if _sal>0 else 0, 2)
            net_contrib = round(rev - crude_alloc, 2)
            pct_grm     = round(net_contrib/grm_full*100,1) if grm_full else 0
            pct_bbl     = round(yld*100,1)
            nc_clr      = clr if net_contrib >= 0 else "#F85149"
            col.markdown(f"""<div class='metric-card'>
                <div class='mc-label' style='color:{clr}'>{name}</div>
                <div style='font-size:17px;font-weight:700;font-family:monospace;
                     color:{nc_clr}'>{"$"+str(net_contrib)+"/bbl"}</div>
                <div style='font-size:11px;color:#8B949E;margin-top:2px'>
                    {pct_grm:+.1f}% of GRM</div>
                <div style='font-size:10px;color:#484F58;margin-top:1px'>
                    {pct_bbl:.1f}% bbl · ${rev:.2f} rev</div>
            </div>""", unsafe_allow_html=True)

        # Barrel utilisation summary — now 100%
        st.markdown(
            f"<div style='font-size:10px;color:#484F58;margin-top:6px'>"
            f"Barrel: {round(_sal*100,1)}% saleable · "
            f"{round(y_ru*100,1)}% refinery fuel use · "
            f"total = {round(_total*100,1)}% · "
            f"crude cost ${cr_:.2f}/bbl · product revenue ${total_rev:.2f}/bbl"
            f"</div>", unsafe_allow_html=True)

        # Formula reference (collapsed)
        with st.expander("📐 Formula reference — 3-2-1 · 2-1-1 · 5-3-2", expanded=False):
            fc1,fc2,fc3 = st.columns(3)
            for fcol,lbl,val,formula in [
                (fc1,"3-2-1",s321,"(2 gas + 1 diesel − 3 WTI) ÷ 3"),
                (fc2,"2-1-1",s211,"(1 gas + 1 diesel − 2 WTI) ÷ 2"),
                (fc3,"5-3-2",s532,"(3 gas + 2 diesel − 5 WTI) ÷ 5"),
            ]:
                fcol.markdown(f"""<div class='metric-card'>
                    <div class='mc-label'>{lbl}</div>
                    <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
                        {"$"+str(val)+"/bbl" if val else "—"}</div>
                    <div class='mc-sub' style='font-size:9px'>{formula}</div>
                </div>""", unsafe_allow_html=True)
            st.caption(
                "Simplified formulas assume 100% of barrel becomes gas or diesel "
                "at NYMEX prices. Ignore jet, bunker, asphalt, LPG, and refinery losses.")

        st.markdown("<br>", unsafe_allow_html=True)
        wa_col,wi_col = st.columns([1,1], gap="large")

        # Waterfall — full barrel build-up incl LPG
        with wa_col:
            st.markdown("<div class='sec-hdr'>GRM Build-Up ($/bbl)</div>",
                        unsafe_allow_html=True)
            if r.get("crude_light") and r.get("wholesale_gas"):
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
                    paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
                    font_color="#E6EDF3",
                    yaxis=dict(title="$/bbl",gridcolor="#21262D"),
                    xaxis=dict(gridcolor="#21262D",tickangle=-20),
                    margin=dict(l=0,r=0,t=8,b=0), height=300, showlegend=False)
                st.plotly_chart(fig_wf, use_container_width=True)
                st.caption("Full Yield model · all 6 saleable products · green = adds to GRM · red = crude cost")

        # What-if 2×2
        with wi_col:
            st.markdown("<div class='sec-hdr'>What-If vs Base</div>",
                        unsafe_allow_html=True)
            if r.get("crude_light") and r.get("wholesale_gas"):
                base    = s321 or 0
                crude_b = r2["crude_light"]
                gas_b   = r2["wholesale_gas"]
                die_b   = r2.get("wholesale_diesel", gas_b)
                scenarios = [
                    ("Crude +25%",    crude_b*1.25, gas_b,      die_b),
                    ("Products +25%", crude_b,      gas_b*1.25, die_b*1.25),
                    ("Crude −25%",    crude_b*0.75, gas_b,      die_b),
                    ("Products −25%", crude_b,      gas_b*0.75, die_b*0.75),
                ]
                r1c1,r1c2 = st.columns(2)
                r2c1,r2c2 = st.columns(2)
                for col,(lbl,c,g,d) in zip([r1c1,r1c2,r2c1,r2c2], scenarios):
                    val   = round(_c321(c,g,d),2)
                    delta = round(val-base,2)
                    is_up = delta >= 0
                    bg    = "#0D2A1A" if is_up else "#2A0D0D"
                    clr2  = "#3FB950" if is_up else "#F85149"
                    sign  = "▲" if is_up else "▼"
                    col.markdown(f"""
                    <div style='background:{bg};border-radius:8px;padding:14px;
                         text-align:center;margin-bottom:4px'>
                      <div style='font-size:9px;color:{clr2};letter-spacing:1px;
                           text-transform:uppercase;font-weight:600'>{lbl}</div>
                      <div style='font-size:10px;color:#8B949E;margin:2px 0'>
                          Base: ${base:.2f}</div>
                      <div style='font-size:20px;font-weight:700;
                           font-family:monospace;color:{clr2}'>${val:.2f}</div>
                      <div style='font-size:13px;font-weight:600;color:{clr2}'>
                          {sign} {sign_str(delta)}/bbl</div>
                    </div>""", unsafe_allow_html=True)

                # Stacked product bar
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("<div class='sec-hdr'>Revenue by Product ($/bbl)</div>",
                            unsafe_allow_html=True)
                AREA_BAR = {
                    "Gasoline":  ("#4A90D9", gc_),
                    "Diesel":    ("#E8A020", dc_),
                    "Jet Fuel":  ("#5A9E3A", jc_),
                    "Bunker":    ("#8B4FBF", bc_),
                    "Asphalt":   ("#CC7722", ac_),
                    "LPG/Other": ("#3AA6B9", lc_),
                }
                fig_bar = go.Figure()
                for prod,(clr2,val) in AREA_BAR.items():
                    fig_bar.add_trace(go.Bar(
                        name=prod, x=["Product Revenue"],
                        y=[val], marker_color=clr2,
                        text=[f"${val:.1f}"], textposition="inside",
                        textfont=dict(size=9,color="#E6EDF3")))
                fig_bar.add_hline(y=cr_, line_color="#F85149",
                    line_width=2, line_dash="solid",
                    annotation_text=f"Crude ${cr_:.2f}/bbl",
                    annotation_font_color="#F85149",
                    annotation_font_size=9)
                fig_bar.update_layout(
                    barmode="stack",
                    paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
                    font_color="#E6EDF3",
                    yaxis=dict(title="$/bbl",gridcolor="#21262D"),
                    xaxis=dict(gridcolor="#21262D"),
                    legend=dict(bgcolor="#161B22",font=dict(size=9),
                                orientation="h",yanchor="bottom",y=1.02),
                    margin=dict(l=0,r=0,t=30,b=0), height=200)
                st.plotly_chart(fig_bar, use_container_width=True)

    # ─── PANEL B: Forward View ─────────────────────────────────────────────────
    with st.expander("📈 Forward Crack Spread", expanded=True):
        loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
        lc_d = st.session_state.get(f"lc_{n}", loc_cfg.get("light_diff",0))
        lg_d = st.session_state.get(f"lg_{n}", loc_cfg.get("gas_diff",0))
        ld_d = st.session_state.get(f"ld_{n}", loc_cfg.get("diesel_diff",0))
        fcd  = st.session_state.get("fcd",0)
        fgd  = st.session_state.get("fgd",0)
        fdd  = st.session_state.get("fdd",0)

        fi1,fi2,fi3,fi4 = st.columns(4)
        jet_fwd = fi1.number_input("Jet fwd ($/gal)",0.5,15.0,
            float(st.session_state.get("jet",4.07)),0.01,"%.3f",key="fwd_jet_d")
        bnk_fwd = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
            float(st.session_state.get("bunker",2.52)),0.01,"%.3f",key="fwd_bnk_d")
        asp_fwd = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
            float(st.session_state.get("asphalt",2.16)),0.01,"%.3f",key="fwd_asp_d")
        lpg_fwd = fi4.number_input("LPG/Other fwd ($/gal)",0.1,5.0,
            float(st.session_state.get("lpg",0.95)),0.01,"%.3f",key="fwd_lpg_d")

        loc_fwd = compute_forward_crack(
            strip=strip,
            crude_diff  = fcd+lc_d,
            gas_diff    = fgd+lg_d,
            diesel_diff = fdd+ld_d,
            jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
            asphalt_fwd=asp_fwd,
            lpg_fwd=lpg_fwd,          # ← NEW
            yields=yields)

        if loc_fwd:
            fwd_ok  = [row for row in loc_fwd if row.get("crack_321")]
            months  = [row["month"]      for row in fwd_ok]
            wti_fwd = [row["wti"]        for row in fwd_ok]
            rbob_f  = [row.get("rbob",0) for row in fwd_ok]
            ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]

            gas_rev = [round((rb or 0)*y_g*42,2) for rb in rbob_f]
            die_rev = [round((ul or 0)*y_d*42,2) for ul in ulsd_f]
            jet_rev = [round(jet_fwd*y_j*42,2)] * len(months)
            bnk_rev = [round(bnk_fwd*y_b*42,2)] * len(months)
            asp_rev = [round(asp_fwd*y_a*42,2)] * len(months)
            lpg_rev = [round(lpg_fwd*y_l*42,2)] * len(months)  # ← NEW

            AREA_COLORS = {
                "Gasoline":  "rgba(74,144,217,0.75)",
                "Diesel":    "rgba(232,160,32,0.75)",
                "Jet Fuel":  "rgba(90,158,58,0.75)",
                "Bunker":    "rgba(139,79,191,0.75)",
                "Asphalt":   "rgba(204,119,34,0.75)",
                "LPG/Other": "rgba(58,166,185,0.75)",  # ← NEW
            }

            fig_fwd = go.Figure()
            for name,vals in [
                ("Gasoline",  gas_rev),
                ("Diesel",    die_rev),
                ("Jet Fuel",  jet_rev),
                ("Bunker",    bnk_rev),
                ("Asphalt",   asp_rev),
                ("LPG/Other", lpg_rev),  # ← NEW
            ]:
                fig_fwd.add_trace(go.Scatter(
                    x=months, y=vals, name=name,
                    mode="none", fill="tonexty",
                    fillcolor=AREA_COLORS[name],
                    stackgroup="one", line=dict(width=0)))
            fig_fwd.add_trace(go.Scatter(
                x=months, y=wti_fwd,
                name="Crude Cost (WTI+diff)",
                line=dict(color="#FFFFFF",width=2.5), mode="lines",
                hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>"))
            crack_vals = [row.get("crack_321") for row in fwd_ok]
            fig_fwd.add_trace(go.Scatter(
                x=months, y=crack_vals,
                name="3-2-1 Crack ($/bbl)",
                line=dict(color="#F85149",width=2,dash="dot"),
                yaxis="y2",
                hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>"))
            fig_fwd.update_layout(
                paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
                font_color="#E6EDF3",
                xaxis=dict(gridcolor="#21262D",tickangle=-45),
                yaxis=dict(title="Product Revenue ($/bbl)",gridcolor="#21262D"),
                yaxis2=dict(
                    title=dict(text="Crack Spread ($/bbl)",
                               font=dict(color="#F85149")),
                    overlaying="y", side="right", showgrid=False,
                    tickfont=dict(color="#F85149")),
                legend=dict(bgcolor="#161B22",bordercolor="#30363D",
                            font=dict(size=10),orientation="h",
                            yanchor="bottom",y=1.02),
                margin=dict(l=0,r=60,t=30,b=0), height=380,
                hovermode="x unified")
            if months and wti_fwd:
                fig_fwd.add_annotation(
                    x=months[len(months)//2],
                    y=wti_fwd[len(wti_fwd)//2]+5,
                    text="↑ Gap above line = Margin",
                    showarrow=False,font=dict(color="#FFFFFF",size=10),
                    bgcolor="rgba(0,0,0,0.5)")
            st.plotly_chart(fig_fwd, use_container_width=True)
            st.caption(
                "Stacked areas = total product revenue by type (6 products incl. LPG/Other). "
                "White line = crude cost. Gap above white line = implied refinery margin. "
                "Red dashed line (right axis) = 3-2-1 crack spread.")

            # Full Yield stress ±20%
            full_vals = [row.get("crack_full") for row in fwd_ok]
            if any(v for v in full_vals):
                fwd_up = compute_forward_crack(
                    strip=strip,
                    crude_diff  = fcd+lc_d+(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff=fgd+lg_d-0.20, diesel_diff=fdd+ld_d-0.20,
                    jet_fwd=jet_fwd*0.80, bunker_fwd=bnk_fwd*0.80,
                    asphalt_fwd=asp_fwd*0.80, lpg_fwd=lpg_fwd*0.80, yields=yields)
                fwd_dn = compute_forward_crack(
                    strip=strip,
                    crude_diff  = fcd+lc_d-(wti_fwd[0]*0.20 if wti_fwd else 0),
                    gas_diff=fgd+lg_d+0.20, diesel_diff=fdd+ld_d+0.20,
                    jet_fwd=jet_fwd*1.20, bunker_fwd=bnk_fwd*1.20,
                    asphalt_fwd=asp_fwd*1.20, lpg_fwd=lpg_fwd*1.20, yields=yields)
                sup = [row.get("crack_full") for row in fwd_up if row.get("crack_full")]
                sdn = [row.get("crack_full") for row in fwd_dn if row.get("crack_full")]
                mup = [row["month"] for row in fwd_up if row.get("crack_full")]
                mdn = [row["month"] for row in fwd_dn if row.get("crack_full")]
                fmo = [row["month"] for row in fwd_ok if row.get("crack_full")]
                fov = [v for v in full_vals if v is not None]

                fig_st = go.Figure()
                if sup and len(sup)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mup+mup[::-1], y=sup+fov[::-1],
                        fill="toself", fillcolor="rgba(248,81,73,0.12)",
                        line=dict(width=0), name="Downside −20%", hoverinfo="skip"))
                if sdn and len(sdn)==len(fov):
                    fig_st.add_trace(go.Scatter(
                        x=mdn+mdn[::-1], y=sdn+fov[::-1],
                        fill="toself", fillcolor="rgba(63,185,80,0.10)",
                        line=dict(width=0), name="Upside +20%", hoverinfo="skip"))
                fig_st.add_trace(go.Scatter(
                    x=fmo, y=fov, name="Full Yield GRM — Base",
                    line=dict(color="#E8A020",width=2.5),
                    mode="lines+markers", marker=dict(size=5)))
                if sup:
                    fig_st.add_trace(go.Scatter(
                        x=mup, y=sup, name="Downside boundary",
                        line=dict(color="#F85149",width=1.5,dash="dash")))
                if sdn:
                    fig_st.add_trace(go.Scatter(
                        x=mdn, y=sdn, name="Upside boundary",
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
                st.plotly_chart(fig_st, use_container_width=True)
                st.caption(
                    "Base = Full Yield GRM at current inputs. "
                    "Red band = downside (crude +20%, products −20%). "
                    "Green band = upside (crude −20%, products +20%).")

            # Forward GRM table
            if tp and crack_vals:
                grm_fwd_list = [round(v*tp*30/1e6,2) if v else None for v in crack_vals]
                fwd_df = pd.DataFrame({
                    "Month":             months,
                    "WTI ($/bbl)":       wti_fwd,
                    "3-2-1 GRM ($/bbl)": crack_vals,
                    "Full Yield ($/bbl)":full_vals,
                    "GRM ($MM/mo)":      grm_fwd_list,
                })
                with st.expander("Forward GRM Table"):
                    st.dataframe(fwd_df, use_container_width=True, hide_index=True)
        else:
            st.info("Forward curve data not available. Check CME connection.")

    # ─── PANEL C: Full Calculator ──────────────────────────────────────────────
    with st.expander("⚙️ Full Calculator — Scenario Inputs", expanded=False):
        mode_now = st.session_state.get("calc_mode",False)
        if mode_now:
            st.info("**Scenario Mode ON** — cards and forward curve update from these inputs.")
        else:
            st.warning(
                "**Live Market Mode ON** — inputs affect forward curve only. "
                "Toggle Scenario Mode above to use for current month cards.")

        st.markdown("<div class='sec-hdr'>Market Prices</div>", unsafe_allow_html=True)
        mp1,mp2,mp3,mp4 = st.columns(4)
        if st.button("↺ Reset to Live", key="reset_live"):
            live2 = get_spot(); spec2 = get_spec()
            ul2   = live2.get("ulsd_gal",3.5) or 3.5
            wti2  = live2.get("wti_bbl",80)   or 80
            st.session_state.update({
                "wti":    wti2, "rbob": live2.get("rbob_gal",2.5) or 2.5,
                "ulsd":   ul2,
                "jet":    spec2.get("jet_gal")    or ul2*1.05,
                "bunker": spec2.get("bunker_gal") or ul2*0.70,
                "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
                "lpg":    round(wti2*0.50/42,3),
            })
            st.rerun()
        st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
            float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
        st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
            float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
        st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
            float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
        st.session_state["dist"]   = mp4.number_input("Dist Margin ($/gal)",0.0,1.0,
            float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

        sp1,sp2,sp3,sp4 = st.columns(4)
        st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
            float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
        st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
            float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
        st.session_state["asphalt"]= sp3.number_input("Asphalt ($/gal)",0.1,8.0,
            float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")
        st.session_state["lpg"]    = sp4.number_input("LPG/Other ($/gal)",0.1,5.0,
            float(st.session_state.get("lpg",0.95)),0.01,"%.3f",key=f"c_lpg_{n}")
        st.caption("💡 LPG/Other = propane, butane, petrochemical naphtha — Mont Belvieu proxy default. "
                   "Cat Feed is a crude cost differential (see below), not a product price.")

        st.markdown("<div class='sec-hdr'>Crude Differentials ($/bbl)</div>",
                    unsafe_allow_html=True)
        d1,d2,d3 = st.columns(3)
        st.session_state[f"lc_{n}"]  = d1.number_input("Light Crude diff",-20.0,20.0,
            float(st.session_state.get(f"lc_{n}",0)),0.25,"%.2f",key=f"c_lc_{n}")
        st.session_state[f"lh_{n}"]  = d2.number_input("Heavy Crude diff",-20.0,20.0,
            float(st.session_state.get(f"lh_{n}",0)),0.25,"%.2f",key=f"c_lh_{n}")
        st.session_state[f"lcf_{n}"] = d3.number_input("Cat Feed diff",-20.0,20.0,
            float(st.session_state.get(f"lcf_{n}",0)),0.25,"%.2f",key=f"c_lcf_{n}")

        st.markdown("<div class='sec-hdr'>Product Differentials ($/gal)</div>",
                    unsafe_allow_html=True)
        pd1,pd2,pd3 = st.columns(3)
        st.session_state[f"lg_{n}"]  = pd1.number_input("Gasoline diff",-1.0,1.0,
            float(st.session_state.get(f"lg_{n}",0)),0.01,"%.3f",key=f"c_lg_{n}")
        st.session_state[f"ld_{n}"]  = pd2.number_input("Diesel diff",-1.0,1.0,
            float(st.session_state.get(f"ld_{n}",0)),0.01,"%.3f",key=f"c_ld_{n}")
        st.session_state[f"lj_{n}"]  = pd3.number_input("Jet diff",-1.0,1.0,
            float(st.session_state.get(f"lj_{n}",0)),0.01,"%.3f",key=f"c_lj_{n}")

        st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
                    unsafe_allow_html=True)
        YLBLS = {
            "gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
            "bunker":"Bunker","asphalt":"Asphalt",
            "lpg_other":"LPG/Other","refinery_use":"Ref. Use",
        }
        ycols = st.columns(7)
        total_y = 0.0
        for i,(k,lbl) in enumerate(YLBLS.items()):
            default = round(YIELD_DEFAULTS.get(k,0)*100,1)
            val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
                float(st.session_state.get(f"y_{k}",default)),
                0.5,"%.1f",key=f"c_y_{k}_{n}")
            st.session_state[f"y_{k}"] = val
            total_y += val
        yc = "#3FB950" if total_y <= 100 else "#F85149"
        st.markdown(
            f"<span style='color:{yc};font-size:12px'>Total: {total_y:.1f}% "
            f"({'OK' if total_y<=100 else 'EXCEEDS 100%'})</span>",
            unsafe_allow_html=True)

        st.markdown("<div class='sec-hdr'>Throughput & Gross Refining Margin</div>",
                    unsafe_allow_html=True)
        tp_new = st.number_input("Throughput (bbl/day)",0,200000,
            int(st.session_state.get(f"tp_{n}",30000)),1000,key=f"c_tp_{n}")
        st.session_state[f"tp_{n}"] = tp_new
        if s321 and tp_new:
            pnl_c  = round(s321 * tp_new * 30 / 1e6, 2)
            annual = round(pnl_c * 12, 1)
            st.markdown(
                f"<div style='background:#161B22;border:1px solid #30363D;"
                f"border-radius:8px;padding:14px;margin-top:8px'>"
                f"<span style='color:#8B949E;font-size:10px'>MONTHLY GRM</span><br>"
                f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
                f"font-family:monospace'>${pnl_c:.2f}MM</span>&nbsp;"
                f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
                f"<span style='color:#8B949E;font-size:11px'>"
                f"${annual}MM annualized · ${s321:.2f}/bbl × {tp_new:,} bbl/day"
                f"</span></div>",
                unsafe_allow_html=True)

        st.markdown("---")
        dl_row = {
            "Location":           sel,
            "Price Mode":         "scenario" if mode_now else "live",
            "Retail Gas ($/gal)": r.get("retail_gas"),
            "Federal Tax":        r.get("federal_tax_gas"),
            "State Tax":          r.get("state_tax_gas"),
            "Pre-tax Gas":        r.get("pretax_gas"),
            "Distribution":       r.get("dist_margin"),
            "Wholesale Gas":      r.get("wholesale_gas"),
            "Wholesale Diesel":   r.get("wholesale_diesel"),
            "Light Crude ($/bbl)":r.get("crude_light"),
            "Heavy Crude":        r.get("crude_heavy"),
            "Cat Feed diff":      r.get("crude_catfeed"),
            "Jet ($/gal)":        st.session_state.get("jet"),
            "Bunker ($/gal)":     st.session_state.get("bunker"),
            "Asphalt ($/gal)":    st.session_state.get("asphalt"),
            "LPG/Other ($/gal)":  st.session_state.get("lpg"),
            "3-2-1 ($/bbl)":      r.get("spread_321"),
            "2-1-1 ($/bbl)":      r.get("spread_211"),
            "5-3-2 ($/bbl)":      r.get("spread_532"),
            "Full Yield ($/bbl)": r.get("spread_full"),
            "Throughput (bbl/d)": tp_new,
            "GRM ($MM/mo)":       fmt_grm(s321, tp_new),
            "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        st.download_button(
            f"⬇️ Download {short} Detail CSV",
            data=pd.DataFrame([dl_row]).to_csv(index=False),
            file_name=f"rogue_{short.replace(' ','_').lower()}.csv",
            mime="text/csv", use_container_width=True)

    # Forward curve diffs
    with st.expander("Forward Curve Diffs", expanded=False):
        fc1,fc2,fc3 = st.columns(3)
        st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
            -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",key=f"fcd_{n}")
        st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
            -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",key=f"fgd_{n}")
        st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
            -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",key=f"fdd_{n}")


# ══════════════════════════════════════════════════════════════════════════════
# METHODOLOGY
# ══════════════════════════════════════════════════════════════════════════════
def show_methodology():
    with st.expander("📋 Methodology & Data Sources — Audit Reference", expanded=False):
        st.markdown("""
<div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

### What this tool calculates

**Gross Refining Margin (GRM)** is the difference between the market value of
refined products produced from one barrel of crude oil and the cost of that crude.
It is a *gross* margin — operating costs ($4–8/bbl for a complex US refinery)
are **not deducted**.

GRM = Σ(Product Price × Yield Fraction × 42) − Crude Cost

---

### Price data sources

| Input | Source | Frequency |
|---|---|---|
| Retail gasoline | AAA Fuel Gauge Report (metro daily) | Daily |
| Retail diesel | AAA Fuel Gauge Report (metro daily) | Daily |
| WTI crude spot | CME first-month settle (rogueng.duckdns.org) | Daily |
| RBOB futures | CME settle strip | Daily |
| ULSD futures | CME settle strip | Daily |
| Jet fuel spot | EIA Gulf Coast Jet (EPJK/PF4/RGC) | Weekly |
| Bunker/Residual | EIA Gulf Coast Residual (EPPR/PF4/RGC) | Weekly |
| Asphalt | EIA US Asphalt (EPPA/PTE/NUS) | Monthly |
| LPG/Other | Mont Belvieu propane proxy: WTI×0.50÷42 | Calculated |
| Federal excise tax | IRS/FHWA — unchanged since Oct 1, 1993 | Static |
| State excise taxes | FTA + EIA, Jul 2025 | Semiannual |

---

### Price waterfall

```
Retail pump price (AAA)
  − Federal excise:  $0.184/gal gas · $0.244/gal diesel
  − State excise:    varies by state
  = Pre-tax price
  − Distribution:    default $0.35/gal
  = Wholesale / refinery gate price
```

---

### State excise taxes (Jul 2025)

| State | Gas | Diesel | Source |
|---|---|---|---|
| AK | $0.0895 | $0.0895 | FTA 2025 |
| TX | $0.200 | $0.200 | FTA 2025 |
| OK | $0.190 | $0.190 | FTA 2025 |
| ND | $0.230 | $0.230 | FTA 2025 |
| UT | $0.385 | $0.385 | EIA Jul 2025 |
| LA | $0.200 | $0.200 | FTA 2025 |
| NM | $0.229 | $0.270 | FTA 2025 + loading fee |

---

### Full Yield product mix defaults (EIA 2024)

Source: EIA Petroleum Supply Monthly 2024 / EIA Today in Energy Mar 24 2025
(eia.gov/todayinenergy/detail.php?id=64786)

| Product | Default % | EIA 2024 | Notes |
|---|---|---|---|
| Gasoline | 44.5% | 44.7% | Lowest share since 2015 |
| Diesel/Distillate | 29.0% | 28.9% | Approximately flat |
| Jet Fuel | 11.0% | 11.2% | Record high 2024 |
| Bunker/Residual | 3.5% | 3.8% | Slightly conservative |
| Asphalt | 2.5% | 2.8% | Road oil included |
| LPG/Other | 4.0% | 3.5% | Propane, butane, naphtha |
| Refinery Use/Loss | 5.5% | ~5.1% | Fuel gas + losses |
| **Total** | **100%** | **100%** | Fully accounted |

**LPG/Other** covers propane, butane, ethane, and petrochemical naphtha.
Priced at Mont Belvieu propane proxy (WTI × 0.50 ÷ 42 ≈ $0.95–$1.10/gal).
User-adjustable in the Full Calculator.

**Cat Feed** is a refinery *input* (FCC/hydrocracker feed), not an output.
Cost is embedded in the crude differential.

---

### What this tool does NOT capture

- Refinery operating costs ($3–8/bbl)
- Blendstock costs (ethanol, MTBE, butane)
- RIN obligations
- Pipeline tariffs
- Carbon costs
- Hedging gains/losses

</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    check_password()
    init_state()

    st.markdown(
        "<h2 style='color:#E6EDF3;margin-bottom:2px;margin-top:-8px'>"
        "🏭 Rogue Refinery Economics</h2>"
        "<p style='color:#8B949E;margin-bottom:10px;font-size:12px'>"
        "Portfolio intelligence · CME forward curves · "
        "Scenario analysis · Gross Refining Margin</p>",
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
        if st.button("🔄 Refresh Market Data", use_container_width=True):
            get_cme.clear(); get_spot.clear()
            get_lp.clear();  get_spec.clear()
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
        st.markdown("---")
        st.caption(
            "**Portfolio:** overview of all locations.\n\n"
            "**Location detail:** click any card to drill in.\n\n"
            "**Scenario Mode:** toggle in the Snapshot panel to use "
            "calculator inputs for current month cards.")

    with st.spinner("Loading market data..."):
        strip = get_cme()
        lp    = get_lp()

    margins, spot, yields = build_margins(lp)
    render_ticker(spot, margins)

    view = st.session_state.get("view","portfolio")
    if view == "portfolio":
        show_command(margins)
        show_methodology()
    else:
        show_detail(margins, strip, yields, lp)

    st.markdown(
        f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
        f"AAA Fuel Gauge · EIA API · CME via rogueng.duckdns.org · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()


    
# # app.py — Rogue Refinery Economics v3 — Command + Detail Flow
# import streamlit as st
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

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── CSS ────────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;
#   flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:10px 0 6px 0}
# .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
#   padding:14px 16px;cursor:pointer;transition:border-color 0.15s}
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
# .whatif-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
# .wi-box{border-radius:8px;padding:12px;text-align:center}
# .wi-label{font-size:9px;letter-spacing:1px;text-transform:uppercase;
#   font-weight:600;margin-bottom:4px}
# .wi-base{font-size:11px;opacity:0.7;margin-bottom:2px}
# .wi-spread{font-size:20px;font-weight:700;font-family:monospace}
# .wi-delta{font-size:13px;font-weight:600;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# [data-testid="stSidebar"]{background:#161B22}
# .stTabs [data-baseweb="tab-list"]{background:#161B22;border-radius:8px;padding:4px}
# .stTabs [data-baseweb="tab"]{color:#8B949E}
# .stTabs [aria-selected="true"]{background:#21262D;color:#E6EDF3;border-radius:6px}
# div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;
#   border-radius:8px}
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
# def get_cme():    return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot():   return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec():   return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     if st.session_state.get("_init"): return
#     live  = get_spot()
#     spec  = get_spec()
#     ulsd  = live.get("ulsd_gal", 3.50) or 3.50
#     wti   = live.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         "wti":      wti,
#         "rbob":     live.get("rbob_gal", 2.50) or 2.50,
#         "ulsd":     ulsd,
#         "jet":      spec.get("jet_gal")     or ulsd * 1.05,
#         "bunker":   spec.get("bunker_gal")  or ulsd * 0.70,
#         "asphalt":  spec.get("asphalt_gal") or ulsd * 0.60,
#         "dist":     0.35,
#         "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
#         "view": "portfolio",
#         "sel_loc": None,
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
#     spot = {"wti_bbl": st.session_state["wti"],
#             "rbob_gal": st.session_state["rbob"],
#             "ulsd_gal": st.session_state["ulsd"]}
#     spec = {"jet_gal":     st.session_state["jet"],
#             "bunker_gal":  st.session_state["bunker"],
#             "asphalt_gal": st.session_state["asphalt"]}
#     yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
#               for k, v in YIELD_DEFAULTS.items()}
#     locs = loc_overrides or []
#     if not locs:
#         for loc in LOCATIONS:
#             n = loc["display"]
#             o = dict(loc)
#             o["light_diff"]   = st.session_state.get(f"lc_{n}",  loc.get("light_diff",0))
#             o["heavy_diff"]   = st.session_state.get(f"lh_{n}",  loc.get("heavy_diff",0))
#             o["catfeed_diff"] = st.session_state.get(f"lcf_{n}", loc.get("catfeed_diff",0))
#             o["gas_diff"]     = st.session_state.get(f"lg_{n}",  loc.get("gas_diff",0))
#             o["diesel_diff"]  = st.session_state.get(f"ld_{n}",  loc.get("diesel_diff",0))
#             o["throughput"]   = st.session_state.get(f"tp_{n}",  30000)
#             locs.append(o)
#     margins = compute_location_margins(
#         locations=locs, spot_prices=spot, location_prices=lp,
#         specialty=spec, yields=yields,
#         dist_margin_gal=st.session_state["dist"])
#     for r in margins:
#         r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#         r["pnl"] = fmt_grm(r.get("spread_321"), r["throughput"])
#     return margins, spot, yields


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
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
#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     pavg = round(sum(spreads)/len(spreads),2) if spreads else None
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
#     # Summary cards
#     valid = [r for r in margins if r.get("spread_321")]
#     if valid:
#         best  = max(valid, key=lambda x: x["spread_321"])
#         worst = min(valid, key=lambda x: x["spread_321"])
#         total_pnl = sum(r["pnl"] for r in valid if r.get("pnl"))
#         sc1, sc2, sc3 = st.columns(3)
#         sc1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Best Margin Today</div>
#             <div class='mc-value' style='color:#3FB950'>
#               ${best["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Thinnest Margin Today</div>
#             <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
#               ${worst["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Total Portfolio Gross Refining Margin / Mo</div>
#             <div class='mc-value' style='color:#3FB950'>
#               {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#             </div>
#             <div class='mc-sub'>at current throughput · before opex</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map — Tap a location for detail</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         c = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         map_rows.append({
#             "name": r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat": c[0], "lon": c[1],
#             "spread": s, "color": spread_color(s),
#             "pnl": r.get("pnl"),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"GRM: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
#                 f"<i>Click location card below to drill in</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"],
#         mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.90),
#         text=df_m["short"],
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text",
#     ))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]],
#                 mode="text",
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
#         paper_bgcolor="#0D1117",
#         margin=dict(l=0,r=0,t=0,b=0), height=400, showlegend=False)
#     for lbl, clr, ya in [("● STRONG ≥$25","#3FB950",0.13),
#                           ("● MODERATE $12–25","#E8A020",0.09),
#                           ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     # Location cards — grouped by status then state
#     # Map display names to groups
#     IN_CONSTRUCTION = {"Victoria, TX", "Duncan, OK"}

#     # Ordered development locations: (display_name, short_label, state_prefix)
#     DEVELOPMENT_ORDER = [
#         ("Alaska — Port Mackenzie",    "Port Mackenzie",   "AK"),
#         ("Greenport — Austin, TX",     "Austin",           "TX"),
#         ("Big Spring, TX",             "Big Spring",       "TX"),
#         ("Dewey, OK",                  "Dewey",            "OK"),
#         ("North Dakota — Stampede",    "Stampede",         "ND"),
#         ("Utah",                       "Utah",             "UT"),
#         ("SE New Mexico",              "SE New Mexico",    "NM"),
#         ("Louisiana",                  "Louisiana",        "LA"),
#         ("Edmonton, Alberta",          "Edmonton",         "CA"),
#         ("Puerto Rico",                "Puerto Rico",      "PR"),
#     ]

#     def _render_card(r, btn_key):
#         s      = r.get("spread_321")
#         clr    = spread_color(s)
#         badge  = spread_badge_class(s)
#         pnl_str= (f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—")
#         short  = r["display"].split("—")[-1].split(",")[0].strip()
#         st.markdown(f"""<div class='loc-card'>
#             <div class='loc-card-name'>{short}</div>
#             <div class='loc-card-spread' style='color:{clr}'>
#                 {"$"+str(s)+"/bbl" if s else "—"}
#             </div>
#             <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
#             <div class='loc-card-pnl'>{pnl_str} · {r.get("source","").split("—")[-1][:12]}</div>
#         </div>""", unsafe_allow_html=True)
#         if st.button("Open →", key=btn_key, use_container_width=True):
#             st.session_state["view"]    = "detail"
#             st.session_state["sel_loc"] = r["display"]
#             st.rerun()

#     margin_map = {r["display"]: r for r in margins}

#     # ── Group 1: Development locations ────────────────────────────────────────
#     st.markdown("<div class='sec-hdr'>Development Locations</div>",
#                 unsafe_allow_html=True)
#     dev_items = [(dn, sl, st_) for dn, sl, st_ in DEVELOPMENT_ORDER
#                  if dn in margin_map]
#     dcols = st.columns(4)
#     for i, (dn, sl, st_) in enumerate(dev_items):
#         r = margin_map[dn]
#         with dcols[i % 4]:
#             _render_card(r, f"btn_dev_{i}")

#     # ── Group 2: In Construction ──────────────────────────────────────────────
#     st.markdown("<br>", unsafe_allow_html=True)
#     st.markdown(
#         "<div class='sec-hdr'>In Construction</div>",
#         unsafe_allow_html=True)
#     constr_items = [r for r in margins if r["display"] in IN_CONSTRUCTION]
#     ccols = st.columns(4)
#     for i, r in enumerate(constr_items):
#         with ccols[i % 4]:
#             _render_card(r, f"btn_con_{i}")

#     # ── Portfolio download ─────────────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
#                 unsafe_allow_html=True)
#     st.caption("Full price detail for every location — retail, pre-tax, "
#                "wholesale, crude prices, specialty products, and crack spreads.")

#     jet_p     = st.session_state.get("jet",     4.07)
#     bunker_p  = st.session_state.get("bunker",  2.52)
#     asphalt_p = st.session_state.get("asphalt", 2.16)

#     dl_rows = []
#     for r in margins:
#         n  = r["display"]
#         tp = r.get("throughput", 30000)
#         grm_mo = fmt_grm(r.get("spread_321"), tp)
#         dl_rows.append({
#             "Location":                      n,
#             "Price Source":                  r.get("source", "—"),
#             "Throughput (bbl/day)":          tp,
#             "Light Crude ($/bbl)":           r.get("crude_light"),
#             "Heavy Crude ($/bbl)":           r.get("crude_heavy"),
#             "Cat Feed / HGO ($/bbl)":        r.get("crude_catfeed"),
#             "Gasoline - Retail ($/gal)":     r.get("retail_gas"),
#             "Gasoline - Federal Tax":        r.get("federal_tax_gas"),
#             "Gasoline - State Tax":          r.get("state_tax_gas"),
#             "Gasoline - Pre-tax ($/gal)":    r.get("pretax_gas"),
#             "Gasoline - Dist Margin":        r.get("dist_margin"),
#             "Gasoline - Wholesale ($/gal)":  r.get("wholesale_gas"),
#             "Diesel - Retail ($/gal)":       r.get("retail_diesel"),
#             "Diesel - Pre-tax ($/gal)":      r.get("pretax_diesel"),
#             "Diesel - Wholesale ($/gal)":    r.get("wholesale_diesel"),
#             "Jet Fuel ($/gal)":              jet_p,
#             "Bunker Fuel ($/gal)":           bunker_p,
#             "Asphalt ($/gal)":               asphalt_p,
#             "3-2-1 Spread ($/bbl)":          r.get("spread_321"),
#             "2-1-1 Spread ($/bbl)":          r.get("spread_211"),
#             "5-3-2 Spread ($/bbl)":          r.get("spread_532"),
#             "Full Yield Spread ($/bbl)":     r.get("spread_full"),
#             "Monthly GRM ($MM)":             grm_mo,
#             "Annual GRM ($MM)":              round(grm_mo * 12, 2) if grm_mo else None,
#             "As Of":                         datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })

#     df_dl = pd.DataFrame(dl_rows)

#     dl_col, tbl_col = st.columns([1, 2])
#     with dl_col:
#         st.download_button(
#             "⬇️ Download All Locations CSV",
#             data=df_dl.to_csv(index=False),
#             file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
#             mime="text/csv",
#             use_container_width=True,
#         )
#     with tbl_col:
#         st.dataframe(
#             df_dl[[
#                 "Location",
#                 "Light Crude ($/bbl)", "Heavy Crude ($/bbl)",
#                 "Gasoline - Retail ($/gal)", "Gasoline - Wholesale ($/gal)",
#                 "Diesel - Retail ($/gal)",   "Diesel - Wholesale ($/gal)",
#                 "Jet Fuel ($/gal)", "Bunker Fuel ($/gal)", "Asphalt ($/gal)",
#                 "3-2-1 Spread ($/bbl)", "Full Yield Spread ($/bbl)",
#                 "Monthly GRM ($MM)",
#             ]],
#             use_container_width=True,
#             hide_index=True,
#         )


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(margins, strip, yields, lp):
#     sel = st.session_state.get("sel_loc")
#     r   = next((m for m in margins if m["display"]==sel), None)

#     # Back nav
#     bc, tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321 = r.get("spread_321") if r else None
#         clr  = spread_color(s321)
#         short = sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
#             f"<span style='color:{clr};font-family:monospace'>"
#             f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
#             f"</h3>",
#             unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     st.markdown("---")

#     # ─── PANEL A: Current Snapshot ────────────────────────────────────────────
#     with st.expander("📊 Current Margin Snapshot", expanded=True):
#         tp   = r.get("throughput", 30000)
#         pnl  = r.get("pnl")
#         sfull= r.get("spread_full")
#         s211 = r.get("spread_211")
#         s532 = r.get("spread_532")

#         # 4 spread formula cards
#         f1,f2,f3,f4,f5 = st.columns(5)
#         for col, lbl, val in [
#             (f1,"3-2-1",s321),(f2,"2-1-1",s211),
#             (f3,"5-3-2",s532),(f4,"Full Yield",sfull),
#         ]:
#             col.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>{lbl}</div>
#                 <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                     {"$"+str(val)+"/bbl" if val else "—"}
#                 </div>
#                 <div class='mc-sub'>{spread_label(val)}</div>
#             </div>""", unsafe_allow_html=True)
#         pnl_v = fmt_grm(s321, tp)
#         f5.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Gross Refining Margin / Mo</div>
#             <div class='mc-value' style='color:#3FB950;font-size:18px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
#             </div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)
#         wa_col, wi_col = st.columns([1,1], gap="large")

#         # Waterfall — full barrel crack spread build-up
#         with wa_col:
#             st.markdown("<div class='sec-hdr'>Gross Refining Margin Build-Up ($/bbl)</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 crude_cost = r["crude_light"]
#                 ws_gas     = r.get("wholesale_gas",  0.0)
#                 ws_die     = r.get("wholesale_diesel",0.0)
#                 jet_p2     = st.session_state.get("jet",     4.07)
#                 bnk_p2     = st.session_state.get("bunker",  2.52)
#                 asp_p2     = st.session_state.get("asphalt", 2.16)

#                 y_g2 = yields.get("gasoline", 0.465)
#                 y_d2 = yields.get("ulsd",     0.286)
#                 y_j2 = yields.get("jet",      0.095)
#                 y_b2 = yields.get("bunker",   0.048)
#                 y_a2 = yields.get("asphalt",  0.036)

#                 gas_contrib  = round(ws_gas  * y_g2 * 42, 2)
#                 die_contrib  = round(ws_die  * y_d2 * 42, 2)
#                 jet_contrib  = round(jet_p2  * y_j2 * 42, 2)
#                 bnk_contrib  = round(bnk_p2  * y_b2 * 42, 2)
#                 asp_contrib  = round(asp_p2  * y_a2 * 42, 2)
#                 sfull_val    = r.get("spread_full", 0) or 0

#                 fig_wf = go.Figure(go.Waterfall(
#                     orientation="v",
#                     measure=["absolute","relative","relative","relative",
#                              "relative","relative","total"],
#                     x=["− Crude Cost","+ Gasoline","+ Diesel",
#                        "+ Jet Fuel","+ Bunker","+ Asphalt",
#                        "= GRM"],
#                     y=[-crude_cost, gas_contrib, die_contrib,
#                        jet_contrib, bnk_contrib, asp_contrib, 0],
#                     text=[
#                         f"-${crude_cost:.2f}",
#                         f"+${gas_contrib:.2f}",
#                         f"+${die_contrib:.2f}",
#                         f"+${jet_contrib:.2f}",
#                         f"+${bnk_contrib:.2f}",
#                         f"+${asp_contrib:.2f}",
#                         f"${sfull_val:.2f}",
#                     ],
#                     textposition="outside",
#                     textfont=dict(size=10, color="#E6EDF3"),
#                     connector=dict(line=dict(color="#30363D", width=1)),
#                     decreasing=dict(marker_color="#F85149"),
#                     increasing=dict(marker_color="#3FB950"),
#                     totals=dict(marker_color="#E8A020"),
#                 ))
#                 fig_wf.update_layout(
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl", gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D", tickangle=-20),
#                     margin=dict(l=0, r=0, t=8, b=0),
#                     height=300, showlegend=False)
#                 st.plotly_chart(fig_wf, use_container_width=True)
#                 st.caption(
#                     "Full Yield model · bars show each product's revenue "
#                     "contribution per barrel of crude processed · "
#                     "green = adds to margin · red = crude cost"
#                 )

#         # What-if 2×2 grid
#         with wi_col:
#             st.markdown("<div class='sec-hdr'>What-If — 4 Scenarios vs Base</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 base    = s321 or 0
#                 crude_b = r["crude_light"]
#                 gas_b   = r["wholesale_gas"]
#                 die_b   = r.get("wholesale_diesel", gas_b)

#                 scenarios = [
#                     ("Crude +25%",   crude_b*1.25, gas_b,     die_b),
#                     ("Products +25%",crude_b,      gas_b*1.25,die_b*1.25),
#                     ("Crude −25%",   crude_b*0.75, gas_b,     die_b),
#                     ("Products −25%",crude_b,      gas_b*0.75,die_b*0.75),
#                 ]
#                 boxes = []
#                 for lbl, c, g, d in scenarios:
#                     val   = round(_c321(c, g, d), 2)
#                     delta = round(val - base, 2)
#                     is_up = delta >= 0
#                     bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                     clr   = "#3FB950" if is_up else "#F85149"
#                     boxes.append((lbl, val, delta, bg, clr, is_up))

#                 # Render as 2×2 using columns
#                 r1c1, r1c2 = st.columns(2)
#                 r2c1, r2c2 = st.columns(2)
#                 for col, (lbl, val, delta, bg, clr, is_up) in zip(
#                     [r1c1,r1c2,r2c1,r2c2], boxes
#                 ):
#                     sign = "▲" if is_up else "▼"
#                     col.markdown(f"""
#                     <div style='background:{bg};border-radius:8px;padding:14px;
#                          text-align:center;margin-bottom:4px'>
#                       <div style='font-size:9px;color:{clr};letter-spacing:1px;
#                            text-transform:uppercase;font-weight:600'>{lbl}</div>
#                       <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                           Base: ${base:.2f}</div>
#                       <div style='font-size:20px;font-weight:700;
#                            font-family:monospace;color:{clr}'>${val:.2f}</div>
#                       <div style='font-size:13px;font-weight:600;color:{clr}'>
#                           {sign} {sign_str(delta)}/bbl</div>
#                     </div>""", unsafe_allow_html=True)

#                 # Product contribution bar
#                 st.markdown("<br>", unsafe_allow_html=True)
#                 st.markdown("<div class='sec-hdr'>Margin by Product Contribution</div>",
#                             unsafe_allow_html=True)
#                 ws_gas  = r.get("wholesale_gas",  0)
#                 ws_die  = r.get("wholesale_diesel",0)
#                 jet_p   = st.session_state.get("jet",    4.07)
#                 bnk_p   = st.session_state.get("bunker", 2.52)
#                 asp_p   = st.session_state.get("asphalt",2.16)
#                 crude_b2= r.get("crude_light",0)

#                 y_gas = yields.get("gasoline",0.465)
#                 y_die = yields.get("ulsd",    0.286)
#                 y_jet = yields.get("jet",     0.095)
#                 y_bnk = yields.get("bunker",  0.048)
#                 y_asp = yields.get("asphalt", 0.036)

#                 contrib = {
#                     "Gasoline": round(ws_gas*y_gas*42, 2),
#                     "Diesel":   round(ws_die*y_die*42, 2),
#                     "Jet Fuel": round(jet_p *y_jet*42, 2),
#                     "Bunker":   round(bnk_p *y_bnk*42, 2),
#                     "Asphalt":  round(asp_p *y_asp*42, 2),
#                 }
#                 colors_c = ["#4A90D9","#E8A020","#5A9E3A","#8B4FBF","#CC7722"]
#                 fig_c = go.Figure()
#                 for (prod, val_c), clr_c in zip(contrib.items(), colors_c):
#                     fig_c.add_trace(go.Bar(
#                         name=prod, x=["Product Revenue"],
#                         y=[val_c], marker_color=clr_c,
#                         text=[f"${val_c:.1f}"],
#                         textposition="inside",
#                         textfont=dict(size=10,color="#E6EDF3")))
#                 fig_c.add_hline(y=crude_b2,
#                     line_color="#F85149",line_width=2,line_dash="solid",
#                     annotation_text=f"Crude cost ${crude_b2:.2f}/bbl",
#                     annotation_font_color="#F85149",annotation_font_size=10)
#                 fig_c.update_layout(
#                     barmode="stack",
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=10),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=30,b=0),height=220)
#                 st.plotly_chart(fig_c, use_container_width=True)

#     # ─── PANEL B: Forward View ────────────────────────────────────────────────
#     with st.expander("📈 Forward Crack Spread", expanded=True):
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#         n       = sel
#         lc_d    = st.session_state.get(f"lc_{n}",  loc_cfg.get("light_diff",0))
#         lg_d    = st.session_state.get(f"lg_{n}",  loc_cfg.get("gas_diff",0))
#         ld_d    = st.session_state.get(f"ld_{n}",  loc_cfg.get("diesel_diff",0))
#         fcd     = st.session_state.get("fcd",0)
#         fgd     = st.session_state.get("fgd",0)
#         fdd     = st.session_state.get("fdd",0)
#         jet_fwd = st.session_state.get("jet",   4.07)
#         bnk_fwd = st.session_state.get("bunker",2.52)
#         asp_fwd = st.session_state.get("asphalt",2.16)

#         # Inline forward price inputs
#         fi1,fi2,fi3 = st.columns(3)
#         jet_fwd  = fi1.number_input("Jet Fuel fwd ($/gal)",0.5,15.0,
#             float(jet_fwd), 0.01,"%.3f",key="fwd_jet_d")
#         bnk_fwd  = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
#             float(bnk_fwd), 0.01,"%.3f",key="fwd_bnk_d")
#         asp_fwd  = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
#             float(asp_fwd), 0.01,"%.3f",key="fwd_asp_d")

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = fcd+lc_d,
#             gas_diff    = fgd+lg_d,
#             diesel_diff = fdd+ld_d,
#             jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
#             asphalt_fwd=asp_fwd, yields=yields)

#         if loc_fwd:
#             # Area chart: products stacked, crude as contrasting line
#             fwd_ok = [row for row in loc_fwd if row.get("crack_321")]
#             months  = [row["month"] for row in fwd_ok]
#             wti_fwd = [row["wti"]   for row in fwd_ok]
#             rbob_f  = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]
#             y_g = yields.get("gasoline",0.465)
#             y_d = yields.get("ulsd",    0.286)
#             y_j = yields.get("jet",     0.095)
#             y_b = yields.get("bunker",  0.048)
#             y_a = yields.get("asphalt", 0.036)

#             gas_rev  = [round((rb or 0)*y_g*42, 2) for rb in rbob_f]
#             die_rev  = [round((ul or 0)*y_d*42, 2) for ul in ulsd_f]
#             jet_rev  = [round(jet_fwd*y_j*42, 2)]  * len(months)
#             bnk_rev  = [round(bnk_fwd*y_b*42, 2)]  * len(months)
#             asp_rev  = [round(asp_fwd*y_a*42, 2)]   * len(months)

#             # Proper rgba color map — no string manipulation
#             AREA_COLORS = {
#                 "Gasoline": "rgba(74,144,217,0.75)",
#                 "Diesel":   "rgba(232,160,32,0.75)",
#                 "Jet Fuel": "rgba(90,158,58,0.75)",
#                 "Bunker":   "rgba(139,79,191,0.75)",
#                 "Asphalt":  "rgba(204,119,34,0.75)",
#             }

#             fig_fwd = go.Figure()
#             # Stacked area — products
#             for name, vals in [
#                 ("Gasoline", gas_rev),
#                 ("Diesel",   die_rev),
#                 ("Jet Fuel", jet_rev),
#                 ("Bunker",   bnk_rev),
#                 ("Asphalt",  asp_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one",
#                     line=dict(width=0),
#                 ))
#             # Crude cost line — white/contrast
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost (WTI+diff)",
#                 line=dict(color="#FFFFFF", width=2.5),
#                 mode="lines",
#                 hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             # 3-2-1 crack line overlay
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149", width=2, dash="dot"),
#                 yaxis="y2",
#                 hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",
#                            gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="Crack Spread ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y", side="right",
#                     showgrid=False,
#                     tickfont=dict(color="#F85149"),
#                 ),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10),
#                             orientation="h", yanchor="bottom", y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified",
#             )
#             # Annotation explaining the gap
#             fig_fwd.add_annotation(
#                 x=months[len(months)//2] if months else 0,
#                 y=wti_fwd[len(wti_fwd)//2]+5 if wti_fwd else 50,
#                 text="↑ Gap above line = Margin",
#                 showarrow=False, font=dict(color="#FFFFFF", size=10),
#                 bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = total product revenue by type. "
#                 "White line = crude cost (WTI + location diff). "
#                 "The gap above the white line is the implied refinery margin. "
#                 "Red dashed line (right axis) = 3-2-1 crack spread."
#             )

#             # Full Yield forward stress chart ±20%
#             full_vals = [row.get("crack_full") for row in fwd_ok]
#             if any(v for v in full_vals):
#                 # Stress: crude +20%, products -20% (worst case compression)
#                 fwd_stress_up = compute_forward_crack(
#                     strip=strip,
#                     crude_diff   = fcd + lc_d + (wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff     = fgd + lg_d - 0.20,
#                     diesel_diff  = fdd + ld_d - 0.20,
#                     jet_fwd      = jet_fwd * 0.80,
#                     bunker_fwd   = bnk_fwd  * 0.80,
#                     asphalt_fwd  = asp_fwd  * 0.80,
#                     yields       = yields,
#                 )
#                 fwd_stress_dn = compute_forward_crack(
#                     strip=strip,
#                     crude_diff   = fcd + lc_d - (wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff     = fgd + lg_d + 0.20,
#                     diesel_diff  = fdd + ld_d + 0.20,
#                     jet_fwd      = jet_fwd * 1.20,
#                     bunker_fwd   = bnk_fwd  * 1.20,
#                     asphalt_fwd  = asp_fwd  * 1.20,
#                     yields       = yields,
#                 )
#                 stress_up_vals = [row.get("crack_full")
#                                   for row in fwd_stress_up if row.get("crack_full")]
#                 stress_dn_vals = [row.get("crack_full")
#                                   for row in fwd_stress_dn if row.get("crack_full")]
#                 stress_mo_up   = [row["month"]
#                                   for row in fwd_stress_up if row.get("crack_full")]
#                 stress_mo_dn   = [row["month"]
#                                   for row in fwd_stress_dn if row.get("crack_full")]
#                 full_mo        = [row["month"] for row in fwd_ok if row.get("crack_full")]
#                 full_ok_vals   = [v for v in full_vals if v is not None]

#                 fig_stress = go.Figure()

#                 # Stress band fill (worst case up, best case down)
#                 if stress_up_vals and stress_dn_vals and len(stress_up_vals)==len(full_ok_vals):
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_up + stress_mo_up[::-1],
#                         y=stress_up_vals + full_ok_vals[::-1],
#                         fill="toself",
#                         fillcolor="rgba(248,81,73,0.12)",
#                         line=dict(width=0),
#                         name="Downside: crude +20%, products −20%",
#                         hoverinfo="skip",
#                     ))
#                 if stress_dn_vals and len(stress_dn_vals)==len(full_ok_vals):
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_dn + stress_mo_dn[::-1],
#                         y=stress_dn_vals + full_ok_vals[::-1],
#                         fill="toself",
#                         fillcolor="rgba(63,185,80,0.10)",
#                         line=dict(width=0),
#                         name="Upside: crude −20%, products +20%",
#                         hoverinfo="skip",
#                     ))

#                 # Base case Full Yield line
#                 fig_stress.add_trace(go.Scatter(
#                     x=full_mo, y=full_ok_vals,
#                     name="Full Yield GRM — Base",
#                     line=dict(color="#E8A020", width=2.5),
#                     mode="lines+markers", marker=dict(size=5),
#                 ))
#                 # Stress boundary lines
#                 if stress_up_vals:
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_up, y=stress_up_vals,
#                         name="Downside boundary",
#                         line=dict(color="#F85149", width=1.5, dash="dash"),
#                     ))
#                 if stress_dn_vals:
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_dn, y=stress_dn_vals,
#                         name="Upside boundary",
#                         line=dict(color="#3FB950", width=1.5, dash="dash"),
#                     ))
#                 # Breakeven reference
#                 fig_stress.add_hline(
#                     y=15, line_dash="dot", line_color="#8B949E",
#                     opacity=0.5,
#                     annotation_text="~Breakeven $15/bbl",
#                     annotation_font_color="#8B949E",
#                     annotation_font_size=9,
#                 )
#                 fig_stress.update_layout(
#                     title=dict(
#                         text="Full Yield GRM — Forward Stress Test ±20%",
#                         font=dict(color="#E6EDF3", size=13),
#                     ),
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                     yaxis=dict(title="Full Yield GRM ($/bbl)",
#                                gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                                 font=dict(size=10),
#                                 orientation="h", yanchor="bottom", y=1.02),
#                     margin=dict(l=0, r=0, t=40, b=0), height=320,
#                 )
#                 st.plotly_chart(fig_stress, use_container_width=True)
#                 st.caption(
#                     "Base case = Full Yield GRM at current inputs. "
#                     "Red band = downside scenario (crude +20%, products −20%). "
#                     "Green band = upside scenario (crude −20%, products +20%). "
#                     "The width of the band shows your margin sensitivity."
#                 )

#             # GRM forward table
#             tp = r.get("throughput", 30000)
#             if tp and crack_vals:
#                 grm_fwd = [round(v*tp*30/1e6,2) if v else None
#                            for v in crack_vals]
#                 fwd_df = pd.DataFrame({
#                     "Month":              months,
#                     "WTI ($/bbl)":        wti_fwd,
#                     "3-2-1 GRM ($/bbl)":  crack_vals,
#                     "Full Yield ($/bbl)": full_vals,
#                     "GRM ($MM/mo)":       grm_fwd,
#                 })
#                 with st.expander("Forward GRM Table"):
#                     st.dataframe(fwd_df, use_container_width=True,
#                                  hide_index=True)
#         else:
#             st.info("Forward curve data not available. Check CME connection.")

#     # ─── PANEL C: Full Calculator ─────────────────────────────────────────────
#     with st.expander("⚙️ Full Calculator — Change Any Input", expanded=False):
#         st.caption(
#             "All changes here update the snapshot and forward curve above. "
#             "Use this to answer any 'what if' question."
#         )
#         # Market prices
#         st.markdown("<div class='sec-hdr'>Market Prices</div>",
#                     unsafe_allow_html=True)
#         mp1,mp2,mp3,mp4 = st.columns(4)
#         if st.button("↺ Reset to Live", key="reset_live"):
#             live2 = get_spot(); spec2 = get_spec()
#             ul2   = live2.get("ulsd_gal",3.5) or 3.5
#             st.session_state.update({
#                 "wti":    live2.get("wti_bbl",80) or 80,
#                 "rbob":   live2.get("rbob_gal",2.5) or 2.5,
#                 "ulsd":   ul2,
#                 "jet":    spec2.get("jet_gal")    or ul2*1.05,
#                 "bunker": spec2.get("bunker_gal") or ul2*0.70,
#                 "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
#             })
#             st.rerun()
#         st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
#             float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
#         st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
#             float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
#         st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
#             float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
#         st.session_state["dist"]   = mp4.number_input("Dist. Margin ($/gal)",0.0,1.0,
#             float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

#         sp1,sp2,sp3 = st.columns(3)
#         st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
#             float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
#         st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
#             float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
#         st.session_state["asphalt"]= sp3.number_input("Asphalt ($/gal)",0.1,8.0,
#             float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")
#         st.caption("💡 Cat Feed is a refinery intermediate stream (FCC/hydrocracker feed), "
#                    "not a saleable product. It is represented as a crude cost differential — "
#                    "see Crude Differentials below.")

#         # Location diffs
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

#         # Yield %
#         st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
#                     unsafe_allow_html=True)
#         YLBLS = {"gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#                  "bunker":"Bunker","asphalt":"Asphalt","refinery_use":"Ref. Use"}
#         ycols = st.columns(6)
#         total_y = 0.0
#         for i,(k,lbl) in enumerate(YLBLS.items()):
#             default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#             val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
#                 float(st.session_state.get(f"y_{k}",default)),
#                 0.5,"%.1f",key=f"c_y_{k}_{n}")
#             st.session_state[f"y_{k}"] = val
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(f"<span style='color:{yc};font-size:12px'>"
#                     f"Total: {total_y:.1f}%</span>", unsafe_allow_html=True)

#         # Throughput
#         st.markdown("<div class='sec-hdr'>Throughput & Gross Refining Margin</div>",
#                     unsafe_allow_html=True)
#         tp_new = st.number_input("Throughput (bbl/day)",0,200000,
#             int(st.session_state.get(f"tp_{n}",30000)),1000,
#             key=f"c_tp_{n}")
#         st.session_state[f"tp_{n}"] = tp_new
#         if s321 and tp_new:
#             pnl_calc = round(s321 * tp_new * 30 / 1e6, 2)
#             annual   = round(pnl_calc * 12, 1)
#             st.markdown(
#                 f"<div style='background:#161B22;border:1px solid #30363D;"
#                 f"border-radius:8px;padding:14px;margin-top:8px'>"
#                 f"<span style='color:#8B949E;font-size:10px'>MONTHLY GRM</span><br>"
#                 f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
#                 f"font-family:monospace'>${pnl_calc:.2f}MM</span>&nbsp;"
#                 f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
#                 f"<span style='color:#8B949E;font-size:11px'>"
#                 f"${annual}MM annualized at ${s321:.2f}/bbl × "
#                 f"{tp_new:,} bbl/day</span></div>",
#                 unsafe_allow_html=True)

#         st.markdown("---")
#         # CSV download
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
#             "Cat Feed":           r.get("crude_catfeed"),
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

#     # Forward diffs (sidebar-style, at bottom of detail page)
#     with st.expander("Forward Curve Diffs", expanded=False):
#         fc1,fc2,fc3 = st.columns(3)
#         st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
#             -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",
#             key=f"fcd_{n}")
#         st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",
#             key=f"fgd_{n}")
#         st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",
#             key=f"fdd_{n}")




# # ══════════════════════════════════════════════════════════════════════════════
# # METHODOLOGY & DATA SOURCES
# # ══════════════════════════════════════════════════════════════════════════════
# def show_methodology():
#     """
#     Comprehensive audit of data sources, formulas, and assumptions.
#     Shown as a collapsed expander at the bottom of the portfolio page.
#     """
#     with st.expander("📋  Methodology & Data Sources — Audit Reference", expanded=False):
#         st.markdown("""
# <div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

# ### What this tool calculates

# **Gross Refining Margin (GRM)** is the difference between the market value of
# refined products produced from one barrel of crude oil and the cost of that crude.
# It is a *gross* margin — operating costs (fuel, catalysts, labour, maintenance,
# depreciation) are **not deducted**. Typical refinery opex runs $4–8/bbl for a
# complex US refinery; simpler refineries run $3–5/bbl.

# GRM = Σ(Product Price × Yield Fraction × 42) − Crude Cost

# ---

# ### Price data sources

# | Input | Source | Frequency | Notes |
# |---|---|---|---|
# | Retail gasoline | AAA Fuel Gauge Report (metro) | Daily | ~60,000 station survey |
# | Retail diesel | AAA Fuel Gauge Report (metro) | Daily | Same survey |
# | WTI crude spot | CME first-month settle (output.xlsx) | Daily | EIA fallback if unavailable |
# | RBOB gasoline futures | CME settle strip (output.xlsx) | Daily | Front through 24 months |
# | ULSD diesel futures | CME settle strip (output.xlsx) | Daily | Front through 24 months |
# | Jet fuel spot | EIA Gulf Coast Kerosene-Type Jet Fuel | Weekly | Series EPJK/PF4/RGC |
# | Bunker/Residual | EIA Gulf Coast Residual Fuel | Weekly | Series EPPR/PF4/RGC |
# | Asphalt | EIA US Asphalt and Road Oil | Monthly | Series EPPA/PTE/NUS |
# | Federal excise tax | IRS/FHWA | Static | Unchanged since Oct 1, 1993 |
# | State excise taxes | Federation of Tax Administrators + EIA | Semiannual | Rates as of Jul 2025 |

# **CME forward curve:** Sourced from `rogueng.duckdns.org/cme_excel/output.xlsx`,
# updated daily. Contains WTI ($/bbl), ULSD ($/gal), and RBOB ($/gal) settle prices
# for all listed contract months. Specialty product forward prices (Jet, Bunker,
# Asphalt) are user inputs held flat across the curve — no exchange-traded forward
# exists for these products at the location level.

# ---

# ### Price waterfall — how retail becomes wholesale

# ```
# Retail pump price (AAA daily metro survey)
#   − Federal excise tax  ($0.184/gal gas · $0.244/gal diesel — fixed since 1993)
#   − State excise tax    (varies by state, see table below)
#   = Pre-tax price
#   − Distribution & retail margin  (default $0.35/gal — adjustable)
#   = Implied wholesale / refinery gate price
# ```

# The wholesale price is then anchored to the NYMEX benchmark
# (RBOB for gasoline, ULSD for diesel) with a local basis adjustment:
# `adj_price = NYMEX_price + (wholesale − NYMEX_price) + location_product_diff`

# ---

# ### State excise tax rates used (as of July 2025)

# | State | Gas ($/gal) | Diesel ($/gal) | Source |
# |---|---|---|---|
# | Alaska (AK) | $0.0895 | $0.0895 | FTA 2025 |
# | Texas (TX) | $0.200 | $0.200 | FTA 2025 |
# | Oklahoma (OK) | $0.190 | $0.190 | FTA 2025 |
# | North Dakota (ND) | $0.230 | $0.230 | FTA 2025 |
# | Utah (UT) | $0.385 | $0.385 | EIA Jul 2025 (updated) |
# | Louisiana (LA) | $0.200 | $0.200 | FTA 2025 |
# | New Mexico (NM) | $0.229 | $0.270 | FTA 2025 + petroleum loading fee |

# *FTA = Federation of Tax Administrators. Federal tax ($0.184/$0.244) is added separately.*

# ---

# ### Crack spread formulas

# | Formula | Equation | Use case |
# |---|---|---|
# | **3-2-1** | (2 × Gas + 1 × Diesel − 3 × WTI) ÷ 3 | Industry benchmark — most widely quoted |
# | **2-1-1** | (1 × Gas + 1 × Diesel − 2 × WTI) ÷ 2 | Balanced distillate refinery |
# | **5-3-2** | (3 × Gas + 2 × Diesel − 5 × WTI) ÷ 5 | Gasoline-heavy refinery |
# | **Full Yield GRM** | Σ(product revenue) − WTI | Complete barrel model using yield fractions |

# Product prices are in $/gal × 42 gal/bbl to convert to $/bbl equivalent.

# ---

# ### Full Yield GRM — product mix defaults

# Default yield fractions are sourced from:
# **EIA Petroleum Supply Monthly, 2024 annual average** (published March 2025).
# Reference: EIA Today in Energy, "Jet fuel made up a record share of U.S. refinery
# output in 2024," March 24, 2025. URL: eia.gov/todayinenergy/detail.php?id=64786

# | Product | Default % | EIA 2024 US Avg | Notes |
# |---|---|---|---|
# | Gasoline | 44.5% | 44.7% | Lowest since 2015 as jet share grew |
# | Diesel/Distillate | 29.0% | 28.9% | Approximately flat vs prior year |
# | Jet Fuel | 11.0% | 11.2% | Record high in 2024; expected to grow |
# | Bunker/Residual | 3.5% | 3.8% | Slightly conservative |
# | Asphalt | 2.5% | 2.8% | Road oil included |
# | Refinery Use/Loss | 5.5% | ~5.1% | Fuel gas + processing losses |
# | **Saleable total** | **90.5%** | **91.4%** | |
# | Unmodeled (LPG, other) | 4.0% | 3.5% | No price source available |

# **Note on Cat Feed / HGO:** Catalytic cracker feed (vacuum gas oil) is an
# intermediate refinery stream — a *feed* to conversion units, not a saleable product.
# It is not included in the GRM calculation. Its cost is represented through the
# heavy crude differential, which reflects the discount applied to heavy sour crude
# relative to WTI light sweet.

# ---

# ### Crude differentials

# Each location's crude input cost is derived from WTI plus a location-specific
# differential reflecting crude quality and transportation basis:

# | Differential | Meaning |
# |---|---|
# | Light crude diff | Light sweet crude vs WTI Cushing ($/bbl) |
# | Heavy crude diff | Heavy sour crude vs WTI — reflects quality discount |

# These are user-configurable defaults set from market knowledge of each location.
# They do **not** auto-update from a live feed — adjust as market conditions change.

# ---

# ### Distribution & retail margin

# Default $0.35/gal ($14.70/bbl). This covers:
# - Truck delivery from terminal to retail station
# - Terminal storage and throughput fees
# - Retail station overhead and retailer margin

# Industry range: $0.18–$0.55/gal depending on market and ownership structure.
# Source: Lundberg Survey / EIA retail margin estimates.

# ---

# ### What this tool does NOT capture

# - Refinery operating costs ($3–8/bbl — subtract from GRM for net margin)
# - Blendstock costs (ethanol, MTBE, butane)
# - RIN (Renewable Identification Number) obligations
# - Refinery maintenance / turnaround costs
# - Pipeline tariffs to/from the refinery
# - Carbon costs (where applicable)
# - Hedging gains or losses on crude/product positions

# ---

# ### Version history

# | Date | Change |
# |---|---|
# | Sep 2026 | Initial release — 12 locations, CME forward curve, AAA daily prices |
# | Sep 2026 | State tax update: UT $0.385, NM $0.229/$0.270 (Jul 2025 rates) |
# | Sep 2026 | Yield defaults updated to EIA 2024 annual averages |
# | Sep 2026 | Cat Feed removed from product price inputs (intermediate stream, not saleable) |

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

#     # Sidebar: just refresh
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
#             "**Portfolio view:** overview of all locations.\n\n"
#             "**Location detail:** click any location card to drill in — "
#             "current margin, forward curve, and full calculator.\n\n"
#             "All inputs in the calculator update the dashboard instantly."
#         )

#     with st.spinner("Loading market data..."):
#         strip = get_cme()
#         lp    = get_lp()

#     margins, spot, yields = build_margins(lp)
#     render_ticker(spot, margins)

#     view = st.session_state.get("view", "portfolio")

#     if view == "portfolio":
#         show_command(margins)
#         show_methodology()
#     else:
#         show_detail(margins, strip, yields, lp)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;"
#         f"margin-top:8px'>AAA Fuel Gauge · EIA API · "
#         f"CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()

# # app.py — Rogue Refinery Economics v3 — Command + Detail Flow
# import streamlit as st
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

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── CSS ────────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;
#   flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:10px 0 6px 0}
# .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
#   padding:14px 16px;cursor:pointer;transition:border-color 0.15s}
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
# .whatif-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
# .wi-box{border-radius:8px;padding:12px;text-align:center}
# .wi-label{font-size:9px;letter-spacing:1px;text-transform:uppercase;
#   font-weight:600;margin-bottom:4px}
# .wi-base{font-size:11px;opacity:0.7;margin-bottom:2px}
# .wi-spread{font-size:20px;font-weight:700;font-family:monospace}
# .wi-delta{font-size:13px;font-weight:600;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# [data-testid="stSidebar"]{background:#161B22}
# .stTabs [data-baseweb="tab-list"]{background:#161B22;border-radius:8px;padding:4px}
# .stTabs [data-baseweb="tab"]{color:#8B949E}
# .stTabs [aria-selected="true"]{background:#21262D;color:#E6EDF3;border-radius:6px}
# div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;
#   border-radius:8px}
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
# def get_cme():    return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot():   return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec():   return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     if st.session_state.get("_init"): return
#     live  = get_spot()
#     spec  = get_spec()
#     ulsd  = live.get("ulsd_gal", 3.50) or 3.50
#     wti   = live.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         "wti":      wti,
#         "rbob":     live.get("rbob_gal", 2.50) or 2.50,
#         "ulsd":     ulsd,
#         "jet":      spec.get("jet_gal")     or ulsd * 1.05,
#         "bunker":   spec.get("bunker_gal")  or ulsd * 0.70,
#         "asphalt":  spec.get("asphalt_gal") or ulsd * 0.60,
#         "dist":     0.35,
#         "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
#         "view": "portfolio",
#         "sel_loc": None,
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
#     spot = {"wti_bbl": st.session_state["wti"],
#             "rbob_gal": st.session_state["rbob"],
#             "ulsd_gal": st.session_state["ulsd"]}
#     spec = {"jet_gal":     st.session_state["jet"],
#             "bunker_gal":  st.session_state["bunker"],
#             "asphalt_gal": st.session_state["asphalt"]}
#     yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
#               for k, v in YIELD_DEFAULTS.items()}
#     locs = loc_overrides or []
#     if not locs:
#         for loc in LOCATIONS:
#             n = loc["display"]
#             o = dict(loc)
#             o["light_diff"]   = st.session_state.get(f"lc_{n}",  loc.get("light_diff",0))
#             o["heavy_diff"]   = st.session_state.get(f"lh_{n}",  loc.get("heavy_diff",0))
#             o["catfeed_diff"] = st.session_state.get(f"lcf_{n}", loc.get("catfeed_diff",0))
#             o["gas_diff"]     = st.session_state.get(f"lg_{n}",  loc.get("gas_diff",0))
#             o["diesel_diff"]  = st.session_state.get(f"ld_{n}",  loc.get("diesel_diff",0))
#             o["throughput"]   = st.session_state.get(f"tp_{n}",  30000)
#             locs.append(o)
#     margins = compute_location_margins(
#         locations=locs, spot_prices=spot, location_prices=lp,
#         specialty=spec, yields=yields,
#         dist_margin_gal=st.session_state["dist"])
#     for r in margins:
#         r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#         r["pnl"] = fmt_grm(r.get("spread_321"), r["throughput"])
#     return margins, spot, yields


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
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
#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     pavg = round(sum(spreads)/len(spreads),2) if spreads else None
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
#     # Summary cards
#     valid = [r for r in margins if r.get("spread_321")]
#     if valid:
#         best  = max(valid, key=lambda x: x["spread_321"])
#         worst = min(valid, key=lambda x: x["spread_321"])
#         total_pnl = sum(r["pnl"] for r in valid if r.get("pnl"))
#         sc1, sc2, sc3 = st.columns(3)
#         sc1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Best Margin Today</div>
#             <div class='mc-value' style='color:#3FB950'>
#               ${best["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Thinnest Margin Today</div>
#             <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
#               ${worst["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Total Portfolio Gross Refining Margin / Mo</div>
#             <div class='mc-value' style='color:#3FB950'>
#               {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#             </div>
#             <div class='mc-sub'>at current throughput · before opex</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map — Tap a location for detail</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         c = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         map_rows.append({
#             "name": r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat": c[0], "lon": c[1],
#             "spread": s, "color": spread_color(s),
#             "pnl": r.get("pnl"),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"GRM: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
#                 f"<i>Click location card below to drill in</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"],
#         mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.90),
#         text=df_m["short"],
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text",
#     ))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]],
#                 mode="text",
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
#                  center=dict(lat=42, lon=-98), projection_scale=2.8,
#                  lonaxis_range=[-170,-50], lataxis_range=[15,72]),
#         paper_bgcolor="#0D1117",
#         margin=dict(l=0,r=0,t=0,b=0), height=400, showlegend=False)
#     for lbl, clr, ya in [("● STRONG ≥$25","#3FB950",0.13),
#                           ("● MODERATE $12–25","#E8A020",0.09),
#                           ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     # Location cards
#     st.markdown("<div class='sec-hdr'>Locations — Select to drill in</div>",
#                 unsafe_allow_html=True)
#     cols = st.columns(4)
#     for i, r in enumerate(margins):
#         s = r.get("spread_321")
#         clr = spread_color(s)
#         badge = spread_badge_class(s)
#         short = r["display"].split("—")[-1].split(",")[0].strip()
#         pnl_str = (f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—")
#         with cols[i % 4]:
#             st.markdown(f"""<div class='loc-card'>
#                 <div class='loc-card-name'>{short}</div>
#                 <div class='loc-card-spread' style='color:{clr}'>
#                     {"$"+str(s)+"/bbl" if s else "—"}
#                 </div>
#                 <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
#                 <div class='loc-card-pnl'>{pnl_str} · {r.get("source","").split("—")[-1][:12]}</div>
#             </div>""", unsafe_allow_html=True)
#             if st.button(f"Open →", key=f"btn_{i}", use_container_width=True):
#                 st.session_state["view"]    = "detail"
#                 st.session_state["sel_loc"] = r["display"]
#                 st.rerun()
#         if (i + 1) % 4 == 0 and i < len(margins)-1:
#             st.markdown("<br>", unsafe_allow_html=True)

#     # ── Portfolio download ─────────────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
#                 unsafe_allow_html=True)
#     st.caption("Full price detail for every location — retail, pre-tax, "
#                "wholesale, crude prices, specialty products, and crack spreads.")

#     jet_p     = st.session_state.get("jet",     4.07)
#     bunker_p  = st.session_state.get("bunker",  2.52)
#     asphalt_p = st.session_state.get("asphalt", 2.16)

#     dl_rows = []
#     for r in margins:
#         n  = r["display"]
#         tp = r.get("throughput", 30000)
#         grm_mo = fmt_grm(r.get("spread_321"), tp)
#         dl_rows.append({
#             "Location":                      n,
#             "Price Source":                  r.get("source", "—"),
#             "Throughput (bbl/day)":          tp,
#             "Light Crude ($/bbl)":           r.get("crude_light"),
#             "Heavy Crude ($/bbl)":           r.get("crude_heavy"),
#             "Cat Feed / HGO ($/bbl)":        r.get("crude_catfeed"),
#             "Gasoline - Retail ($/gal)":     r.get("retail_gas"),
#             "Gasoline - Federal Tax":        r.get("federal_tax_gas"),
#             "Gasoline - State Tax":          r.get("state_tax_gas"),
#             "Gasoline - Pre-tax ($/gal)":    r.get("pretax_gas"),
#             "Gasoline - Dist Margin":        r.get("dist_margin"),
#             "Gasoline - Wholesale ($/gal)":  r.get("wholesale_gas"),
#             "Diesel - Retail ($/gal)":       r.get("retail_diesel"),
#             "Diesel - Pre-tax ($/gal)":      r.get("pretax_diesel"),
#             "Diesel - Wholesale ($/gal)":    r.get("wholesale_diesel"),
#             "Jet Fuel ($/gal)":              jet_p,
#             "Bunker Fuel ($/gal)":           bunker_p,
#             "Asphalt ($/gal)":               asphalt_p,
#             "3-2-1 Spread ($/bbl)":          r.get("spread_321"),
#             "2-1-1 Spread ($/bbl)":          r.get("spread_211"),
#             "5-3-2 Spread ($/bbl)":          r.get("spread_532"),
#             "Full Yield Spread ($/bbl)":     r.get("spread_full"),
#             "Monthly GRM ($MM)":             grm_mo,
#             "Annual GRM ($MM)":              round(grm_mo * 12, 2) if grm_mo else None,
#             "As Of":                         datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })

#     df_dl = pd.DataFrame(dl_rows)

#     dl_col, tbl_col = st.columns([1, 2])
#     with dl_col:
#         st.download_button(
#             "⬇️ Download All Locations CSV",
#             data=df_dl.to_csv(index=False),
#             file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
#             mime="text/csv",
#             use_container_width=True,
#         )
#     with tbl_col:
#         st.dataframe(
#             df_dl[[
#                 "Location",
#                 "Light Crude ($/bbl)", "Heavy Crude ($/bbl)",
#                 "Gasoline - Retail ($/gal)", "Gasoline - Wholesale ($/gal)",
#                 "Diesel - Retail ($/gal)",   "Diesel - Wholesale ($/gal)",
#                 "Jet Fuel ($/gal)", "Bunker Fuel ($/gal)", "Asphalt ($/gal)",
#                 "3-2-1 Spread ($/bbl)", "Full Yield Spread ($/bbl)",
#                 "Monthly GRM ($MM)",
#             ]],
#             use_container_width=True,
#             hide_index=True,
#         )


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(margins, strip, yields, lp):
#     sel = st.session_state.get("sel_loc")
#     r   = next((m for m in margins if m["display"]==sel), None)

#     # Back nav
#     bc, tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321 = r.get("spread_321") if r else None
#         clr  = spread_color(s321)
#         short = sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
#             f"<span style='color:{clr};font-family:monospace'>"
#             f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
#             f"</h3>",
#             unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     st.markdown("---")

#     # ─── PANEL A: Current Snapshot ────────────────────────────────────────────
#     with st.expander("📊 Current Margin Snapshot", expanded=True):
#         tp   = r.get("throughput", 30000)
#         pnl  = r.get("pnl")
#         sfull= r.get("spread_full")
#         s211 = r.get("spread_211")
#         s532 = r.get("spread_532")

#         # 4 spread formula cards
#         f1,f2,f3,f4,f5 = st.columns(5)
#         for col, lbl, val in [
#             (f1,"3-2-1",s321),(f2,"2-1-1",s211),
#             (f3,"5-3-2",s532),(f4,"Full Yield",sfull),
#         ]:
#             col.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>{lbl}</div>
#                 <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                     {"$"+str(val)+"/bbl" if val else "—"}
#                 </div>
#                 <div class='mc-sub'>{spread_label(val)}</div>
#             </div>""", unsafe_allow_html=True)
#         pnl_v = fmt_grm(s321, tp)
#         f5.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Gross Refining Margin / Mo</div>
#             <div class='mc-value' style='color:#3FB950;font-size:18px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
#             </div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)
#         wa_col, wi_col = st.columns([1,1], gap="large")

#         # Waterfall — full barrel crack spread build-up
#         with wa_col:
#             st.markdown("<div class='sec-hdr'>Gross Refining Margin Build-Up ($/bbl)</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 crude_cost = r["crude_light"]
#                 ws_gas     = r.get("wholesale_gas",  0.0)
#                 ws_die     = r.get("wholesale_diesel",0.0)
#                 jet_p2     = st.session_state.get("jet",     4.07)
#                 bnk_p2     = st.session_state.get("bunker",  2.52)
#                 asp_p2     = st.session_state.get("asphalt", 2.16)

#                 y_g2 = yields.get("gasoline", 0.465)
#                 y_d2 = yields.get("ulsd",     0.286)
#                 y_j2 = yields.get("jet",      0.095)
#                 y_b2 = yields.get("bunker",   0.048)
#                 y_a2 = yields.get("asphalt",  0.036)

#                 gas_contrib  = round(ws_gas  * y_g2 * 42, 2)
#                 die_contrib  = round(ws_die  * y_d2 * 42, 2)
#                 jet_contrib  = round(jet_p2  * y_j2 * 42, 2)
#                 bnk_contrib  = round(bnk_p2  * y_b2 * 42, 2)
#                 asp_contrib  = round(asp_p2  * y_a2 * 42, 2)
#                 sfull_val    = r.get("spread_full", 0) or 0

#                 fig_wf = go.Figure(go.Waterfall(
#                     orientation="v",
#                     measure=["absolute","relative","relative","relative",
#                              "relative","relative","total"],
#                     x=["− Crude Cost","+ Gasoline","+ Diesel",
#                        "+ Jet Fuel","+ Bunker","+ Asphalt",
#                        "= GRM"],
#                     y=[-crude_cost, gas_contrib, die_contrib,
#                        jet_contrib, bnk_contrib, asp_contrib, 0],
#                     text=[
#                         f"-${crude_cost:.2f}",
#                         f"+${gas_contrib:.2f}",
#                         f"+${die_contrib:.2f}",
#                         f"+${jet_contrib:.2f}",
#                         f"+${bnk_contrib:.2f}",
#                         f"+${asp_contrib:.2f}",
#                         f"${sfull_val:.2f}",
#                     ],
#                     textposition="outside",
#                     textfont=dict(size=10, color="#E6EDF3"),
#                     connector=dict(line=dict(color="#30363D", width=1)),
#                     decreasing=dict(marker_color="#F85149"),
#                     increasing=dict(marker_color="#3FB950"),
#                     totals=dict(marker_color="#E8A020"),
#                 ))
#                 fig_wf.update_layout(
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl", gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D", tickangle=-20),
#                     margin=dict(l=0, r=0, t=8, b=0),
#                     height=300, showlegend=False)
#                 st.plotly_chart(fig_wf, use_container_width=True)
#                 st.caption(
#                     "Full Yield model · bars show each product's revenue "
#                     "contribution per barrel of crude processed · "
#                     "green = adds to margin · red = crude cost"
#                 )

#         # What-if 2×2 grid
#         with wi_col:
#             st.markdown("<div class='sec-hdr'>What-If — 4 Scenarios vs Base</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 base    = s321 or 0
#                 crude_b = r["crude_light"]
#                 gas_b   = r["wholesale_gas"]
#                 die_b   = r.get("wholesale_diesel", gas_b)

#                 scenarios = [
#                     ("Crude +25%",   crude_b*1.25, gas_b,     die_b),
#                     ("Products +25%",crude_b,      gas_b*1.25,die_b*1.25),
#                     ("Crude −25%",   crude_b*0.75, gas_b,     die_b),
#                     ("Products −25%",crude_b,      gas_b*0.75,die_b*0.75),
#                 ]
#                 boxes = []
#                 for lbl, c, g, d in scenarios:
#                     val   = round(_c321(c, g, d), 2)
#                     delta = round(val - base, 2)
#                     is_up = delta >= 0
#                     bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                     clr   = "#3FB950" if is_up else "#F85149"
#                     boxes.append((lbl, val, delta, bg, clr, is_up))

#                 # Render as 2×2 using columns
#                 r1c1, r1c2 = st.columns(2)
#                 r2c1, r2c2 = st.columns(2)
#                 for col, (lbl, val, delta, bg, clr, is_up) in zip(
#                     [r1c1,r1c2,r2c1,r2c2], boxes
#                 ):
#                     sign = "▲" if is_up else "▼"
#                     col.markdown(f"""
#                     <div style='background:{bg};border-radius:8px;padding:14px;
#                          text-align:center;margin-bottom:4px'>
#                       <div style='font-size:9px;color:{clr};letter-spacing:1px;
#                            text-transform:uppercase;font-weight:600'>{lbl}</div>
#                       <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                           Base: ${base:.2f}</div>
#                       <div style='font-size:20px;font-weight:700;
#                            font-family:monospace;color:{clr}'>${val:.2f}</div>
#                       <div style='font-size:13px;font-weight:600;color:{clr}'>
#                           {sign} {sign_str(delta)}/bbl</div>
#                     </div>""", unsafe_allow_html=True)

#                 # Product contribution bar
#                 st.markdown("<br>", unsafe_allow_html=True)
#                 st.markdown("<div class='sec-hdr'>Margin by Product Contribution</div>",
#                             unsafe_allow_html=True)
#                 ws_gas  = r.get("wholesale_gas",  0)
#                 ws_die  = r.get("wholesale_diesel",0)
#                 jet_p   = st.session_state.get("jet",    4.07)
#                 bnk_p   = st.session_state.get("bunker", 2.52)
#                 asp_p   = st.session_state.get("asphalt",2.16)
#                 crude_b2= r.get("crude_light",0)

#                 y_gas = yields.get("gasoline",0.465)
#                 y_die = yields.get("ulsd",    0.286)
#                 y_jet = yields.get("jet",     0.095)
#                 y_bnk = yields.get("bunker",  0.048)
#                 y_asp = yields.get("asphalt", 0.036)

#                 contrib = {
#                     "Gasoline": round(ws_gas*y_gas*42, 2),
#                     "Diesel":   round(ws_die*y_die*42, 2),
#                     "Jet Fuel": round(jet_p *y_jet*42, 2),
#                     "Bunker":   round(bnk_p *y_bnk*42, 2),
#                     "Asphalt":  round(asp_p *y_asp*42, 2),
#                 }
#                 colors_c = ["#4A90D9","#E8A020","#5A9E3A","#8B4FBF","#CC7722"]
#                 fig_c = go.Figure()
#                 for (prod, val_c), clr_c in zip(contrib.items(), colors_c):
#                     fig_c.add_trace(go.Bar(
#                         name=prod, x=["Product Revenue"],
#                         y=[val_c], marker_color=clr_c,
#                         text=[f"${val_c:.1f}"],
#                         textposition="inside",
#                         textfont=dict(size=10,color="#E6EDF3")))
#                 fig_c.add_hline(y=crude_b2,
#                     line_color="#F85149",line_width=2,line_dash="solid",
#                     annotation_text=f"Crude cost ${crude_b2:.2f}/bbl",
#                     annotation_font_color="#F85149",annotation_font_size=10)
#                 fig_c.update_layout(
#                     barmode="stack",
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=10),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=30,b=0),height=220)
#                 st.plotly_chart(fig_c, use_container_width=True)

#     # ─── PANEL B: Forward View ────────────────────────────────────────────────
#     with st.expander("📈 Forward Crack Spread", expanded=True):
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#         n       = sel
#         lc_d    = st.session_state.get(f"lc_{n}",  loc_cfg.get("light_diff",0))
#         lg_d    = st.session_state.get(f"lg_{n}",  loc_cfg.get("gas_diff",0))
#         ld_d    = st.session_state.get(f"ld_{n}",  loc_cfg.get("diesel_diff",0))
#         fcd     = st.session_state.get("fcd",0)
#         fgd     = st.session_state.get("fgd",0)
#         fdd     = st.session_state.get("fdd",0)
#         jet_fwd = st.session_state.get("jet",   4.07)
#         bnk_fwd = st.session_state.get("bunker",2.52)
#         asp_fwd = st.session_state.get("asphalt",2.16)

#         # Inline forward price inputs
#         fi1,fi2,fi3 = st.columns(3)
#         jet_fwd  = fi1.number_input("Jet Fuel fwd ($/gal)",0.5,15.0,
#             float(jet_fwd), 0.01,"%.3f",key="fwd_jet_d")
#         bnk_fwd  = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
#             float(bnk_fwd), 0.01,"%.3f",key="fwd_bnk_d")
#         asp_fwd  = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
#             float(asp_fwd), 0.01,"%.3f",key="fwd_asp_d")

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = fcd+lc_d,
#             gas_diff    = fgd+lg_d,
#             diesel_diff = fdd+ld_d,
#             jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
#             asphalt_fwd=asp_fwd, yields=yields)

#         if loc_fwd:
#             # Area chart: products stacked, crude as contrasting line
#             fwd_ok = [row for row in loc_fwd if row.get("crack_321")]
#             months  = [row["month"] for row in fwd_ok]
#             wti_fwd = [row["wti"]   for row in fwd_ok]
#             rbob_f  = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]
#             y_g = yields.get("gasoline",0.465)
#             y_d = yields.get("ulsd",    0.286)
#             y_j = yields.get("jet",     0.095)
#             y_b = yields.get("bunker",  0.048)
#             y_a = yields.get("asphalt", 0.036)

#             gas_rev  = [round((rb or 0)*y_g*42, 2) for rb in rbob_f]
#             die_rev  = [round((ul or 0)*y_d*42, 2) for ul in ulsd_f]
#             jet_rev  = [round(jet_fwd*y_j*42, 2)]  * len(months)
#             bnk_rev  = [round(bnk_fwd*y_b*42, 2)]  * len(months)
#             asp_rev  = [round(asp_fwd*y_a*42, 2)]   * len(months)

#             # Proper rgba color map — no string manipulation
#             AREA_COLORS = {
#                 "Gasoline": "rgba(74,144,217,0.75)",
#                 "Diesel":   "rgba(232,160,32,0.75)",
#                 "Jet Fuel": "rgba(90,158,58,0.75)",
#                 "Bunker":   "rgba(139,79,191,0.75)",
#                 "Asphalt":  "rgba(204,119,34,0.75)",
#             }

#             fig_fwd = go.Figure()
#             # Stacked area — products
#             for name, vals in [
#                 ("Gasoline", gas_rev),
#                 ("Diesel",   die_rev),
#                 ("Jet Fuel", jet_rev),
#                 ("Bunker",   bnk_rev),
#                 ("Asphalt",  asp_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one",
#                     line=dict(width=0),
#                 ))
#             # Crude cost line — white/contrast
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost (WTI+diff)",
#                 line=dict(color="#FFFFFF", width=2.5),
#                 mode="lines",
#                 hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             # 3-2-1 crack line overlay
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149", width=2, dash="dot"),
#                 yaxis="y2",
#                 hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",
#                            gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="Crack Spread ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y", side="right",
#                     showgrid=False,
#                     tickfont=dict(color="#F85149"),
#                 ),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10),
#                             orientation="h", yanchor="bottom", y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified",
#             )
#             # Annotation explaining the gap
#             fig_fwd.add_annotation(
#                 x=months[len(months)//2] if months else 0,
#                 y=wti_fwd[len(wti_fwd)//2]+5 if wti_fwd else 50,
#                 text="↑ Gap above line = Margin",
#                 showarrow=False, font=dict(color="#FFFFFF", size=10),
#                 bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = total product revenue by type. "
#                 "White line = crude cost (WTI + location diff). "
#                 "The gap above the white line is the implied refinery margin. "
#                 "Red dashed line (right axis) = 3-2-1 crack spread."
#             )

#             # Full Yield forward stress chart ±20%
#             full_vals = [row.get("crack_full") for row in fwd_ok]
#             if any(v for v in full_vals):
#                 # Stress: crude +20%, products -20% (worst case compression)
#                 fwd_stress_up = compute_forward_crack(
#                     strip=strip,
#                     crude_diff   = fcd + lc_d + (wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff     = fgd + lg_d - 0.20,
#                     diesel_diff  = fdd + ld_d - 0.20,
#                     jet_fwd      = jet_fwd * 0.80,
#                     bunker_fwd   = bnk_fwd  * 0.80,
#                     asphalt_fwd  = asp_fwd  * 0.80,
#                     yields       = yields,
#                 )
#                 fwd_stress_dn = compute_forward_crack(
#                     strip=strip,
#                     crude_diff   = fcd + lc_d - (wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff     = fgd + lg_d + 0.20,
#                     diesel_diff  = fdd + ld_d + 0.20,
#                     jet_fwd      = jet_fwd * 1.20,
#                     bunker_fwd   = bnk_fwd  * 1.20,
#                     asphalt_fwd  = asp_fwd  * 1.20,
#                     yields       = yields,
#                 )
#                 stress_up_vals = [row.get("crack_full")
#                                   for row in fwd_stress_up if row.get("crack_full")]
#                 stress_dn_vals = [row.get("crack_full")
#                                   for row in fwd_stress_dn if row.get("crack_full")]
#                 stress_mo_up   = [row["month"]
#                                   for row in fwd_stress_up if row.get("crack_full")]
#                 stress_mo_dn   = [row["month"]
#                                   for row in fwd_stress_dn if row.get("crack_full")]
#                 full_mo        = [row["month"] for row in fwd_ok if row.get("crack_full")]
#                 full_ok_vals   = [v for v in full_vals if v is not None]

#                 fig_stress = go.Figure()

#                 # Stress band fill (worst case up, best case down)
#                 if stress_up_vals and stress_dn_vals and len(stress_up_vals)==len(full_ok_vals):
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_up + stress_mo_up[::-1],
#                         y=stress_up_vals + full_ok_vals[::-1],
#                         fill="toself",
#                         fillcolor="rgba(248,81,73,0.12)",
#                         line=dict(width=0),
#                         name="Downside: crude +20%, products −20%",
#                         hoverinfo="skip",
#                     ))
#                 if stress_dn_vals and len(stress_dn_vals)==len(full_ok_vals):
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_dn + stress_mo_dn[::-1],
#                         y=stress_dn_vals + full_ok_vals[::-1],
#                         fill="toself",
#                         fillcolor="rgba(63,185,80,0.10)",
#                         line=dict(width=0),
#                         name="Upside: crude −20%, products +20%",
#                         hoverinfo="skip",
#                     ))

#                 # Base case Full Yield line
#                 fig_stress.add_trace(go.Scatter(
#                     x=full_mo, y=full_ok_vals,
#                     name="Full Yield GRM — Base",
#                     line=dict(color="#E8A020", width=2.5),
#                     mode="lines+markers", marker=dict(size=5),
#                 ))
#                 # Stress boundary lines
#                 if stress_up_vals:
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_up, y=stress_up_vals,
#                         name="Downside boundary",
#                         line=dict(color="#F85149", width=1.5, dash="dash"),
#                     ))
#                 if stress_dn_vals:
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_dn, y=stress_dn_vals,
#                         name="Upside boundary",
#                         line=dict(color="#3FB950", width=1.5, dash="dash"),
#                     ))
#                 # Breakeven reference
#                 fig_stress.add_hline(
#                     y=15, line_dash="dot", line_color="#8B949E",
#                     opacity=0.5,
#                     annotation_text="~Breakeven $15/bbl",
#                     annotation_font_color="#8B949E",
#                     annotation_font_size=9,
#                 )
#                 fig_stress.update_layout(
#                     title=dict(
#                         text="Full Yield GRM — Forward Stress Test ±20%",
#                         font=dict(color="#E6EDF3", size=13),
#                     ),
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                     yaxis=dict(title="Full Yield GRM ($/bbl)",
#                                gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                                 font=dict(size=10),
#                                 orientation="h", yanchor="bottom", y=1.02),
#                     margin=dict(l=0, r=0, t=40, b=0), height=320,
#                 )
#                 st.plotly_chart(fig_stress, use_container_width=True)
#                 st.caption(
#                     "Base case = Full Yield GRM at current inputs. "
#                     "Red band = downside scenario (crude +20%, products −20%). "
#                     "Green band = upside scenario (crude −20%, products +20%). "
#                     "The width of the band shows your margin sensitivity."
#                 )

#             # GRM forward table
#             tp = r.get("throughput", 30000)
#             if tp and crack_vals:
#                 grm_fwd = [round(v*tp*30/1e6,2) if v else None
#                            for v in crack_vals]
#                 fwd_df = pd.DataFrame({
#                     "Month":              months,
#                     "WTI ($/bbl)":        wti_fwd,
#                     "3-2-1 GRM ($/bbl)":  crack_vals,
#                     "Full Yield ($/bbl)": full_vals,
#                     "GRM ($MM/mo)":       grm_fwd,
#                 })
#                 with st.expander("Forward GRM Table"):
#                     st.dataframe(fwd_df, use_container_width=True,
#                                  hide_index=True)
#         else:
#             st.info("Forward curve data not available. Check CME connection.")

#     # ─── PANEL C: Full Calculator ─────────────────────────────────────────────
#     with st.expander("⚙️ Full Calculator — Change Any Input", expanded=False):
#         st.caption(
#             "All changes here update the snapshot and forward curve above. "
#             "Use this to answer any 'what if' question."
#         )
#         # Market prices
#         st.markdown("<div class='sec-hdr'>Market Prices</div>",
#                     unsafe_allow_html=True)
#         mp1,mp2,mp3,mp4 = st.columns(4)
#         if st.button("↺ Reset to Live", key="reset_live"):
#             live2 = get_spot(); spec2 = get_spec()
#             ul2   = live2.get("ulsd_gal",3.5) or 3.5
#             st.session_state.update({
#                 "wti":    live2.get("wti_bbl",80) or 80,
#                 "rbob":   live2.get("rbob_gal",2.5) or 2.5,
#                 "ulsd":   ul2,
#                 "jet":    spec2.get("jet_gal")    or ul2*1.05,
#                 "bunker": spec2.get("bunker_gal") or ul2*0.70,
#                 "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
#             })
#             st.rerun()
#         st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
#             float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
#         st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
#             float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
#         st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
#             float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
#         st.session_state["dist"]   = mp4.number_input("Dist. Margin ($/gal)",0.0,1.0,
#             float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

#         sp1,sp2,sp3 = st.columns(3)
#         st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
#             float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
#         st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
#             float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
#         st.session_state["asphalt"]= sp3.number_input("Asphalt ($/gal)",0.1,8.0,
#             float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")
#         st.caption("💡 Cat Feed is a refinery intermediate stream (FCC/hydrocracker feed), "
#                    "not a saleable product. It is represented as a crude cost differential — "
#                    "see Crude Differentials below.")

#         # Location diffs
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

#         # Yield %
#         st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
#                     unsafe_allow_html=True)
#         YLBLS = {"gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#                  "bunker":"Bunker","asphalt":"Asphalt","refinery_use":"Ref. Use"}
#         ycols = st.columns(6)
#         total_y = 0.0
#         for i,(k,lbl) in enumerate(YLBLS.items()):
#             default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#             val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
#                 float(st.session_state.get(f"y_{k}",default)),
#                 0.5,"%.1f",key=f"c_y_{k}_{n}")
#             st.session_state[f"y_{k}"] = val
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(f"<span style='color:{yc};font-size:12px'>"
#                     f"Total: {total_y:.1f}%</span>", unsafe_allow_html=True)

#         # Throughput
#         st.markdown("<div class='sec-hdr'>Throughput & Gross Refining Margin</div>",
#                     unsafe_allow_html=True)
#         tp_new = st.number_input("Throughput (bbl/day)",0,200000,
#             int(st.session_state.get(f"tp_{n}",30000)),1000,
#             key=f"c_tp_{n}")
#         st.session_state[f"tp_{n}"] = tp_new
#         if s321 and tp_new:
#             pnl_calc = round(s321 * tp_new * 30 / 1e6, 2)
#             annual   = round(pnl_calc * 12, 1)
#             st.markdown(
#                 f"<div style='background:#161B22;border:1px solid #30363D;"
#                 f"border-radius:8px;padding:14px;margin-top:8px'>"
#                 f"<span style='color:#8B949E;font-size:10px'>MONTHLY GRM</span><br>"
#                 f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
#                 f"font-family:monospace'>${pnl_calc:.2f}MM</span>&nbsp;"
#                 f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
#                 f"<span style='color:#8B949E;font-size:11px'>"
#                 f"${annual}MM annualized at ${s321:.2f}/bbl × "
#                 f"{tp_new:,} bbl/day</span></div>",
#                 unsafe_allow_html=True)

#         st.markdown("---")
#         # CSV download
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
#             "Cat Feed":           r.get("crude_catfeed"),
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

#     # Forward diffs (sidebar-style, at bottom of detail page)
#     with st.expander("Forward Curve Diffs", expanded=False):
#         fc1,fc2,fc3 = st.columns(3)
#         st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
#             -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",
#             key=f"fcd_{n}")
#         st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",
#             key=f"fgd_{n}")
#         st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",
#             key=f"fdd_{n}")




# # ══════════════════════════════════════════════════════════════════════════════
# # METHODOLOGY & DATA SOURCES
# # ══════════════════════════════════════════════════════════════════════════════
# def show_methodology():
#     """
#     Comprehensive audit of data sources, formulas, and assumptions.
#     Shown as a collapsed expander at the bottom of the portfolio page.
#     """
#     with st.expander("📋  Methodology & Data Sources — Audit Reference", expanded=False):
#         st.markdown("""
# <div style='color:#E6EDF3;font-size:13px;line-height:1.7'>

# ### What this tool calculates

# **Gross Refining Margin (GRM)** is the difference between the market value of
# refined products produced from one barrel of crude oil and the cost of that crude.
# It is a *gross* margin — operating costs (fuel, catalysts, labour, maintenance,
# depreciation) are **not deducted**. Typical refinery opex runs $4–8/bbl for a
# complex US refinery; simpler refineries run $3–5/bbl.

# GRM = Σ(Product Price × Yield Fraction × 42) − Crude Cost

# ---

# ### Price data sources

# | Input | Source | Frequency | Notes |
# |---|---|---|---|
# | Retail gasoline | AAA Fuel Gauge Report (metro) | Daily | ~60,000 station survey |
# | Retail diesel | AAA Fuel Gauge Report (metro) | Daily | Same survey |
# | WTI crude spot | CME first-month settle (output.xlsx) | Daily | EIA fallback if unavailable |
# | RBOB gasoline futures | CME settle strip (output.xlsx) | Daily | Front through 24 months |
# | ULSD diesel futures | CME settle strip (output.xlsx) | Daily | Front through 24 months |
# | Jet fuel spot | EIA Gulf Coast Kerosene-Type Jet Fuel | Weekly | Series EPJK/PF4/RGC |
# | Bunker/Residual | EIA Gulf Coast Residual Fuel | Weekly | Series EPPR/PF4/RGC |
# | Asphalt | EIA US Asphalt and Road Oil | Monthly | Series EPPA/PTE/NUS |
# | Federal excise tax | IRS/FHWA | Static | Unchanged since Oct 1, 1993 |
# | State excise taxes | Federation of Tax Administrators + EIA | Semiannual | Rates as of Jul 2025 |

# **CME forward curve:** Sourced from `rogueng.duckdns.org/cme_excel/output.xlsx`,
# updated daily. Contains WTI ($/bbl), ULSD ($/gal), and RBOB ($/gal) settle prices
# for all listed contract months. Specialty product forward prices (Jet, Bunker,
# Asphalt) are user inputs held flat across the curve — no exchange-traded forward
# exists for these products at the location level.

# ---

# ### Price waterfall — how retail becomes wholesale

# ```
# Retail pump price (AAA daily metro survey)
#   − Federal excise tax  ($0.184/gal gas · $0.244/gal diesel — fixed since 1993)
#   − State excise tax    (varies by state, see table below)
#   = Pre-tax price
#   − Distribution & retail margin  (default $0.35/gal — adjustable)
#   = Implied wholesale / refinery gate price
# ```

# The wholesale price is then anchored to the NYMEX benchmark
# (RBOB for gasoline, ULSD for diesel) with a local basis adjustment:
# `adj_price = NYMEX_price + (wholesale − NYMEX_price) + location_product_diff`

# ---

# ### State excise tax rates used (as of July 2025)

# | State | Gas ($/gal) | Diesel ($/gal) | Source |
# |---|---|---|---|
# | Alaska (AK) | $0.0895 | $0.0895 | FTA 2025 |
# | Texas (TX) | $0.200 | $0.200 | FTA 2025 |
# | Oklahoma (OK) | $0.190 | $0.190 | FTA 2025 |
# | North Dakota (ND) | $0.230 | $0.230 | FTA 2025 |
# | Utah (UT) | $0.385 | $0.385 | EIA Jul 2025 (updated) |
# | Louisiana (LA) | $0.200 | $0.200 | FTA 2025 |
# | New Mexico (NM) | $0.229 | $0.270 | FTA 2025 + petroleum loading fee |

# *FTA = Federation of Tax Administrators. Federal tax ($0.184/$0.244) is added separately.*

# ---

# ### Crack spread formulas

# | Formula | Equation | Use case |
# |---|---|---|
# | **3-2-1** | (2 × Gas + 1 × Diesel − 3 × WTI) ÷ 3 | Industry benchmark — most widely quoted |
# | **2-1-1** | (1 × Gas + 1 × Diesel − 2 × WTI) ÷ 2 | Balanced distillate refinery |
# | **5-3-2** | (3 × Gas + 2 × Diesel − 5 × WTI) ÷ 5 | Gasoline-heavy refinery |
# | **Full Yield GRM** | Σ(product revenue) − WTI | Complete barrel model using yield fractions |

# Product prices are in $/gal × 42 gal/bbl to convert to $/bbl equivalent.

# ---

# ### Full Yield GRM — product mix defaults

# Default yield fractions are sourced from:
# **EIA Petroleum Supply Monthly, 2024 annual average** (published March 2025).
# Reference: EIA Today in Energy, "Jet fuel made up a record share of U.S. refinery
# output in 2024," March 24, 2025. URL: eia.gov/todayinenergy/detail.php?id=64786

# | Product | Default % | EIA 2024 US Avg | Notes |
# |---|---|---|---|
# | Gasoline | 44.5% | 44.7% | Lowest since 2015 as jet share grew |
# | Diesel/Distillate | 29.0% | 28.9% | Approximately flat vs prior year |
# | Jet Fuel | 11.0% | 11.2% | Record high in 2024; expected to grow |
# | Bunker/Residual | 3.5% | 3.8% | Slightly conservative |
# | Asphalt | 2.5% | 2.8% | Road oil included |
# | Refinery Use/Loss | 5.5% | ~5.1% | Fuel gas + processing losses |
# | **Saleable total** | **90.5%** | **91.4%** | |
# | Unmodeled (LPG, other) | 4.0% | 3.5% | No price source available |

# **Note on Cat Feed / HGO:** Catalytic cracker feed (vacuum gas oil) is an
# intermediate refinery stream — a *feed* to conversion units, not a saleable product.
# It is not included in the GRM calculation. Its cost is represented through the
# heavy crude differential, which reflects the discount applied to heavy sour crude
# relative to WTI light sweet.

# ---

# ### Crude differentials

# Each location's crude input cost is derived from WTI plus a location-specific
# differential reflecting crude quality and transportation basis:

# | Differential | Meaning |
# |---|---|
# | Light crude diff | Light sweet crude vs WTI Cushing ($/bbl) |
# | Heavy crude diff | Heavy sour crude vs WTI — reflects quality discount |

# These are user-configurable defaults set from market knowledge of each location.
# They do **not** auto-update from a live feed — adjust as market conditions change.

# ---

# ### Distribution & retail margin

# Default $0.35/gal ($14.70/bbl). This covers:
# - Truck delivery from terminal to retail station
# - Terminal storage and throughput fees
# - Retail station overhead and retailer margin

# Industry range: $0.18–$0.55/gal depending on market and ownership structure.
# Source: Lundberg Survey / EIA retail margin estimates.

# ---

# ### What this tool does NOT capture

# - Refinery operating costs ($3–8/bbl — subtract from GRM for net margin)
# - Blendstock costs (ethanol, MTBE, butane)
# - RIN (Renewable Identification Number) obligations
# - Refinery maintenance / turnaround costs
# - Pipeline tariffs to/from the refinery
# - Carbon costs (where applicable)
# - Hedging gains or losses on crude/product positions

# ---

# ### Version history

# | Date | Change |
# |---|---|
# | Sep 2026 | Initial release — 12 locations, CME forward curve, AAA daily prices |
# | Sep 2026 | State tax update: UT $0.385, NM $0.229/$0.270 (Jul 2025 rates) |
# | Sep 2026 | Yield defaults updated to EIA 2024 annual averages |
# | Sep 2026 | Cat Feed removed from product price inputs (intermediate stream, not saleable) |

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

#     # Sidebar: just refresh
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
#             "**Portfolio view:** overview of all locations.\n\n"
#             "**Location detail:** click any location card to drill in — "
#             "current margin, forward curve, and full calculator.\n\n"
#             "All inputs in the calculator update the dashboard instantly."
#         )

#     with st.spinner("Loading market data..."):
#         strip = get_cme()
#         lp    = get_lp()

#     margins, spot, yields = build_margins(lp)
#     render_ticker(spot, margins)

#     view = st.session_state.get("view", "portfolio")

#     if view == "portfolio":
#         show_command(margins)
#         show_methodology()
#     else:
#         show_detail(margins, strip, yields, lp)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;"
#         f"margin-top:8px'>AAA Fuel Gauge · EIA API · "
#         f"CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()


# # app.py — Rogue Refinery Economics v3 — Command + Detail Flow
# import streamlit as st
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

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── CSS ────────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;
#   flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:10px 0 6px 0}
# .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
#   padding:14px 16px;cursor:pointer;transition:border-color 0.15s}
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
# .whatif-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
# .wi-box{border-radius:8px;padding:12px;text-align:center}
# .wi-label{font-size:9px;letter-spacing:1px;text-transform:uppercase;
#   font-weight:600;margin-bottom:4px}
# .wi-base{font-size:11px;opacity:0.7;margin-bottom:2px}
# .wi-spread{font-size:20px;font-weight:700;font-family:monospace}
# .wi-delta{font-size:13px;font-weight:600;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# [data-testid="stSidebar"]{background:#161B22}
# .stTabs [data-baseweb="tab-list"]{background:#161B22;border-radius:8px;padding:4px}
# .stTabs [data-baseweb="tab"]{color:#8B949E}
# .stTabs [aria-selected="true"]{background:#21262D;color:#E6EDF3;border-radius:6px}
# div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;
#   border-radius:8px}
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
# def get_cme():    return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot():   return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec():   return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     if st.session_state.get("_init"): return
#     live  = get_spot()
#     spec  = get_spec()
#     ulsd  = live.get("ulsd_gal", 3.50) or 3.50
#     wti   = live.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         "wti":      wti,
#         "rbob":     live.get("rbob_gal", 2.50) or 2.50,
#         "ulsd":     ulsd,
#         "jet":      spec.get("jet_gal")     or ulsd * 1.05,
#         "bunker":   spec.get("bunker_gal")  or ulsd * 0.70,
#         "catfeed":  wti * 0.95 / 42,
#         "asphalt":  spec.get("asphalt_gal") or ulsd * 0.60,
#         "dist":     0.35,
#         "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
#         "view": "portfolio",
#         "sel_loc": None,
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
#     spot = {"wti_bbl": st.session_state["wti"],
#             "rbob_gal": st.session_state["rbob"],
#             "ulsd_gal": st.session_state["ulsd"]}
#     spec = {"jet_gal":     st.session_state["jet"],
#             "bunker_gal":  st.session_state["bunker"],
#             "asphalt_gal": st.session_state["asphalt"]}
#     yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
#               for k, v in YIELD_DEFAULTS.items()}
#     locs = loc_overrides or []
#     if not locs:
#         for loc in LOCATIONS:
#             n = loc["display"]
#             o = dict(loc)
#             o["light_diff"]   = st.session_state.get(f"lc_{n}",  loc.get("light_diff",0))
#             o["heavy_diff"]   = st.session_state.get(f"lh_{n}",  loc.get("heavy_diff",0))
#             o["catfeed_diff"] = st.session_state.get(f"lcf_{n}", loc.get("catfeed_diff",0))
#             o["gas_diff"]     = st.session_state.get(f"lg_{n}",  loc.get("gas_diff",0))
#             o["diesel_diff"]  = st.session_state.get(f"ld_{n}",  loc.get("diesel_diff",0))
#             o["throughput"]   = st.session_state.get(f"tp_{n}",  30000)
#             locs.append(o)
#     margins = compute_location_margins(
#         locations=locs, spot_prices=spot, location_prices=lp,
#         specialty=spec, yields=yields,
#         dist_margin_gal=st.session_state["dist"])
#     for r in margins:
#         r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#         r["pnl"] = fmt_grm(r.get("spread_321"), r["throughput"])
#     return margins, spot, yields


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
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
#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     pavg = round(sum(spreads)/len(spreads),2) if spreads else None
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
#     # Summary cards
#     valid = [r for r in margins if r.get("spread_321")]
#     if valid:
#         best  = max(valid, key=lambda x: x["spread_321"])
#         worst = min(valid, key=lambda x: x["spread_321"])
#         total_pnl = sum(r["pnl"] for r in valid if r.get("pnl"))
#         sc1, sc2, sc3 = st.columns(3)
#         sc1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Best Margin Today</div>
#             <div class='mc-value' style='color:#3FB950'>
#               ${best["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Thinnest Margin Today</div>
#             <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
#               ${worst["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Total Portfolio Gross Refining Margin / Mo</div>
#             <div class='mc-value' style='color:#3FB950'>
#               {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#             </div>
#             <div class='mc-sub'>at current throughput · before opex</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map — Tap a location for detail</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         c = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         map_rows.append({
#             "name": r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat": c[0], "lon": c[1],
#             "spread": s, "color": spread_color(s),
#             "pnl": r.get("pnl"),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"GRM: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
#                 f"<i>Click location card below to drill in</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"],
#         mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.90),
#         text=df_m["short"],
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text",
#     ))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]],
#                 mode="text",
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
#                  center=dict(lat=42, lon=-98), projection_scale=2.8,
#                  lonaxis_range=[-170,-50], lataxis_range=[15,72]),
#         paper_bgcolor="#0D1117",
#         margin=dict(l=0,r=0,t=0,b=0), height=400, showlegend=False)
#     for lbl, clr, ya in [("● STRONG ≥$25","#3FB950",0.13),
#                           ("● MODERATE $12–25","#E8A020",0.09),
#                           ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     # Location cards
#     st.markdown("<div class='sec-hdr'>Locations — Select to drill in</div>",
#                 unsafe_allow_html=True)
#     cols = st.columns(4)
#     for i, r in enumerate(margins):
#         s = r.get("spread_321")
#         clr = spread_color(s)
#         badge = spread_badge_class(s)
#         short = r["display"].split("—")[-1].split(",")[0].strip()
#         pnl_str = (f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—")
#         with cols[i % 4]:
#             st.markdown(f"""<div class='loc-card'>
#                 <div class='loc-card-name'>{short}</div>
#                 <div class='loc-card-spread' style='color:{clr}'>
#                     {"$"+str(s)+"/bbl" if s else "—"}
#                 </div>
#                 <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
#                 <div class='loc-card-pnl'>{pnl_str} · {r.get("source","").split("—")[-1][:12]}</div>
#             </div>""", unsafe_allow_html=True)
#             if st.button(f"Open →", key=f"btn_{i}", use_container_width=True):
#                 st.session_state["view"]    = "detail"
#                 st.session_state["sel_loc"] = r["display"]
#                 st.rerun()
#         if (i + 1) % 4 == 0 and i < len(margins)-1:
#             st.markdown("<br>", unsafe_allow_html=True)

#     # ── Portfolio download ─────────────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
#                 unsafe_allow_html=True)
#     st.caption("Full price detail for every location — retail, pre-tax, "
#                "wholesale, crude prices, specialty products, and crack spreads.")

#     jet_p     = st.session_state.get("jet",     4.07)
#     bunker_p  = st.session_state.get("bunker",  2.52)
#     asphalt_p = st.session_state.get("asphalt", 2.16)

#     dl_rows = []
#     for r in margins:
#         n  = r["display"]
#         tp = r.get("throughput", 30000)
#         grm_mo = fmt_grm(r.get("spread_321"), tp)
#         dl_rows.append({
#             "Location":                      n,
#             "Price Source":                  r.get("source", "—"),
#             "Throughput (bbl/day)":          tp,
#             "Light Crude ($/bbl)":           r.get("crude_light"),
#             "Heavy Crude ($/bbl)":           r.get("crude_heavy"),
#             "Cat Feed / HGO ($/bbl)":        r.get("crude_catfeed"),
#             "Gasoline - Retail ($/gal)":     r.get("retail_gas"),
#             "Gasoline - Federal Tax":        r.get("federal_tax_gas"),
#             "Gasoline - State Tax":          r.get("state_tax_gas"),
#             "Gasoline - Pre-tax ($/gal)":    r.get("pretax_gas"),
#             "Gasoline - Dist Margin":        r.get("dist_margin"),
#             "Gasoline - Wholesale ($/gal)":  r.get("wholesale_gas"),
#             "Diesel - Retail ($/gal)":       r.get("retail_diesel"),
#             "Diesel - Pre-tax ($/gal)":      r.get("pretax_diesel"),
#             "Diesel - Wholesale ($/gal)":    r.get("wholesale_diesel"),
#             "Jet Fuel ($/gal)":              jet_p,
#             "Bunker Fuel ($/gal)":           bunker_p,
#             "Asphalt ($/gal)":               asphalt_p,
#             "3-2-1 Spread ($/bbl)":          r.get("spread_321"),
#             "2-1-1 Spread ($/bbl)":          r.get("spread_211"),
#             "5-3-2 Spread ($/bbl)":          r.get("spread_532"),
#             "Full Yield Spread ($/bbl)":     r.get("spread_full"),
#             "Monthly GRM ($MM)":             grm_mo,
#             "Annual GRM ($MM)":              round(grm_mo * 12, 2) if grm_mo else None,
#             "As Of":                         datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })

#     df_dl = pd.DataFrame(dl_rows)

#     dl_col, tbl_col = st.columns([1, 2])
#     with dl_col:
#         st.download_button(
#             "⬇️ Download All Locations CSV",
#             data=df_dl.to_csv(index=False),
#             file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
#             mime="text/csv",
#             use_container_width=True,
#         )
#     with tbl_col:
#         st.dataframe(
#             df_dl[[
#                 "Location",
#                 "Light Crude ($/bbl)", "Heavy Crude ($/bbl)",
#                 "Gasoline - Retail ($/gal)", "Gasoline - Wholesale ($/gal)",
#                 "Diesel - Retail ($/gal)",   "Diesel - Wholesale ($/gal)",
#                 "Jet Fuel ($/gal)", "Bunker Fuel ($/gal)", "Asphalt ($/gal)",
#                 "3-2-1 Spread ($/bbl)", "Full Yield Spread ($/bbl)",
#                 "Monthly GRM ($MM)",
#             ]],
#             use_container_width=True,
#             hide_index=True,
#         )


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(margins, strip, yields, lp):
#     sel = st.session_state.get("sel_loc")
#     r   = next((m for m in margins if m["display"]==sel), None)

#     # Back nav
#     bc, tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321 = r.get("spread_321") if r else None
#         clr  = spread_color(s321)
#         short = sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
#             f"<span style='color:{clr};font-family:monospace'>"
#             f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
#             f"</h3>",
#             unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     st.markdown("---")

#     # ─── PANEL A: Current Snapshot ────────────────────────────────────────────
#     with st.expander("📊 Current Margin Snapshot", expanded=True):
#         tp   = r.get("throughput", 30000)
#         pnl  = r.get("pnl")
#         sfull= r.get("spread_full")
#         s211 = r.get("spread_211")
#         s532 = r.get("spread_532")

#         # 4 spread formula cards
#         f1,f2,f3,f4,f5 = st.columns(5)
#         for col, lbl, val in [
#             (f1,"3-2-1",s321),(f2,"2-1-1",s211),
#             (f3,"5-3-2",s532),(f4,"Full Yield",sfull),
#         ]:
#             col.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>{lbl}</div>
#                 <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                     {"$"+str(val)+"/bbl" if val else "—"}
#                 </div>
#                 <div class='mc-sub'>{spread_label(val)}</div>
#             </div>""", unsafe_allow_html=True)
#         pnl_v = fmt_grm(s321, tp)
#         f5.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Gross Refining Margin / Mo</div>
#             <div class='mc-value' style='color:#3FB950;font-size:18px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
#             </div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)
#         wa_col, wi_col = st.columns([1,1], gap="large")

#         # Waterfall — full barrel crack spread build-up
#         with wa_col:
#             st.markdown("<div class='sec-hdr'>Gross Refining Margin Build-Up ($/bbl)</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 crude_cost = r["crude_light"]
#                 ws_gas     = r.get("wholesale_gas",  0.0)
#                 ws_die     = r.get("wholesale_diesel",0.0)
#                 jet_p2     = st.session_state.get("jet",     4.07)
#                 bnk_p2     = st.session_state.get("bunker",  2.52)
#                 asp_p2     = st.session_state.get("asphalt", 2.16)

#                 y_g2 = yields.get("gasoline", 0.465)
#                 y_d2 = yields.get("ulsd",     0.286)
#                 y_j2 = yields.get("jet",      0.095)
#                 y_b2 = yields.get("bunker",   0.048)
#                 y_a2 = yields.get("asphalt",  0.036)

#                 gas_contrib  = round(ws_gas  * y_g2 * 42, 2)
#                 die_contrib  = round(ws_die  * y_d2 * 42, 2)
#                 jet_contrib  = round(jet_p2  * y_j2 * 42, 2)
#                 bnk_contrib  = round(bnk_p2  * y_b2 * 42, 2)
#                 asp_contrib  = round(asp_p2  * y_a2 * 42, 2)
#                 sfull_val    = r.get("spread_full", 0) or 0

#                 fig_wf = go.Figure(go.Waterfall(
#                     orientation="v",
#                     measure=["absolute","relative","relative","relative",
#                              "relative","relative","total"],
#                     x=["− Crude Cost","+ Gasoline","+ Diesel",
#                        "+ Jet Fuel","+ Bunker","+ Asphalt",
#                        "= GRM"],
#                     y=[-crude_cost, gas_contrib, die_contrib,
#                        jet_contrib, bnk_contrib, asp_contrib, 0],
#                     text=[
#                         f"-${crude_cost:.2f}",
#                         f"+${gas_contrib:.2f}",
#                         f"+${die_contrib:.2f}",
#                         f"+${jet_contrib:.2f}",
#                         f"+${bnk_contrib:.2f}",
#                         f"+${asp_contrib:.2f}",
#                         f"${sfull_val:.2f}",
#                     ],
#                     textposition="outside",
#                     textfont=dict(size=10, color="#E6EDF3"),
#                     connector=dict(line=dict(color="#30363D", width=1)),
#                     decreasing=dict(marker_color="#F85149"),
#                     increasing=dict(marker_color="#3FB950"),
#                     totals=dict(marker_color="#E8A020"),
#                 ))
#                 fig_wf.update_layout(
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl", gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D", tickangle=-20),
#                     margin=dict(l=0, r=0, t=8, b=0),
#                     height=300, showlegend=False)
#                 st.plotly_chart(fig_wf, use_container_width=True)
#                 st.caption(
#                     "Full Yield model · bars show each product's revenue "
#                     "contribution per barrel of crude processed · "
#                     "green = adds to margin · red = crude cost"
#                 )

#         # What-if 2×2 grid
#         with wi_col:
#             st.markdown("<div class='sec-hdr'>What-If — 4 Scenarios vs Base</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 base    = s321 or 0
#                 crude_b = r["crude_light"]
#                 gas_b   = r["wholesale_gas"]
#                 die_b   = r.get("wholesale_diesel", gas_b)

#                 scenarios = [
#                     ("Crude +25%",   crude_b*1.25, gas_b,     die_b),
#                     ("Products +25%",crude_b,      gas_b*1.25,die_b*1.25),
#                     ("Crude −25%",   crude_b*0.75, gas_b,     die_b),
#                     ("Products −25%",crude_b,      gas_b*0.75,die_b*0.75),
#                 ]
#                 boxes = []
#                 for lbl, c, g, d in scenarios:
#                     val   = round(_c321(c, g, d), 2)
#                     delta = round(val - base, 2)
#                     is_up = delta >= 0
#                     bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                     clr   = "#3FB950" if is_up else "#F85149"
#                     boxes.append((lbl, val, delta, bg, clr, is_up))

#                 # Render as 2×2 using columns
#                 r1c1, r1c2 = st.columns(2)
#                 r2c1, r2c2 = st.columns(2)
#                 for col, (lbl, val, delta, bg, clr, is_up) in zip(
#                     [r1c1,r1c2,r2c1,r2c2], boxes
#                 ):
#                     sign = "▲" if is_up else "▼"
#                     col.markdown(f"""
#                     <div style='background:{bg};border-radius:8px;padding:14px;
#                          text-align:center;margin-bottom:4px'>
#                       <div style='font-size:9px;color:{clr};letter-spacing:1px;
#                            text-transform:uppercase;font-weight:600'>{lbl}</div>
#                       <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                           Base: ${base:.2f}</div>
#                       <div style='font-size:20px;font-weight:700;
#                            font-family:monospace;color:{clr}'>${val:.2f}</div>
#                       <div style='font-size:13px;font-weight:600;color:{clr}'>
#                           {sign} {sign_str(delta)}/bbl</div>
#                     </div>""", unsafe_allow_html=True)

#                 # Product contribution bar
#                 st.markdown("<br>", unsafe_allow_html=True)
#                 st.markdown("<div class='sec-hdr'>Margin by Product Contribution</div>",
#                             unsafe_allow_html=True)
#                 ws_gas  = r.get("wholesale_gas",  0)
#                 ws_die  = r.get("wholesale_diesel",0)
#                 jet_p   = st.session_state.get("jet",    4.07)
#                 bnk_p   = st.session_state.get("bunker", 2.52)
#                 asp_p   = st.session_state.get("asphalt",2.16)
#                 crude_b2= r.get("crude_light",0)

#                 y_gas = yields.get("gasoline",0.465)
#                 y_die = yields.get("ulsd",    0.286)
#                 y_jet = yields.get("jet",     0.095)
#                 y_bnk = yields.get("bunker",  0.048)
#                 y_asp = yields.get("asphalt", 0.036)

#                 contrib = {
#                     "Gasoline": round(ws_gas*y_gas*42, 2),
#                     "Diesel":   round(ws_die*y_die*42, 2),
#                     "Jet Fuel": round(jet_p *y_jet*42, 2),
#                     "Bunker":   round(bnk_p *y_bnk*42, 2),
#                     "Asphalt":  round(asp_p *y_asp*42, 2),
#                 }
#                 colors_c = ["#4A90D9","#E8A020","#5A9E3A","#8B4FBF","#CC7722"]
#                 fig_c = go.Figure()
#                 for (prod, val_c), clr_c in zip(contrib.items(), colors_c):
#                     fig_c.add_trace(go.Bar(
#                         name=prod, x=["Product Revenue"],
#                         y=[val_c], marker_color=clr_c,
#                         text=[f"${val_c:.1f}"],
#                         textposition="inside",
#                         textfont=dict(size=10,color="#E6EDF3")))
#                 fig_c.add_hline(y=crude_b2,
#                     line_color="#F85149",line_width=2,line_dash="solid",
#                     annotation_text=f"Crude cost ${crude_b2:.2f}/bbl",
#                     annotation_font_color="#F85149",annotation_font_size=10)
#                 fig_c.update_layout(
#                     barmode="stack",
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=10),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=30,b=0),height=220)
#                 st.plotly_chart(fig_c, use_container_width=True)

#     # ─── PANEL B: Forward View ────────────────────────────────────────────────
#     with st.expander("📈 Forward Crack Spread", expanded=True):
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#         n       = sel
#         lc_d    = st.session_state.get(f"lc_{n}",  loc_cfg.get("light_diff",0))
#         lg_d    = st.session_state.get(f"lg_{n}",  loc_cfg.get("gas_diff",0))
#         ld_d    = st.session_state.get(f"ld_{n}",  loc_cfg.get("diesel_diff",0))
#         fcd     = st.session_state.get("fcd",0)
#         fgd     = st.session_state.get("fgd",0)
#         fdd     = st.session_state.get("fdd",0)
#         jet_fwd = st.session_state.get("jet",   4.07)
#         bnk_fwd = st.session_state.get("bunker",2.52)
#         asp_fwd = st.session_state.get("asphalt",2.16)

#         # Inline forward price inputs
#         fi1,fi2,fi3,fi4 = st.columns(4)
#         jet_fwd  = fi1.number_input("Jet Fuel fwd ($/gal)",0.5,15.0,
#             float(jet_fwd), 0.01,"%.3f",key="fwd_jet_d")
#         bnk_fwd  = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
#             float(bnk_fwd), 0.01,"%.3f",key="fwd_bnk_d")
#         asp_fwd  = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
#             float(asp_fwd), 0.01,"%.3f",key="fwd_asp_d")
#         cat_fwd  = fi4.number_input("Cat Feed fwd ($/gal)",0.5,10.0,
#             float(st.session_state.get("catfeed",1.90)),
#             0.01,"%.3f",key="fwd_cat_d")

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = fcd+lc_d,
#             gas_diff    = fgd+lg_d,
#             diesel_diff = fdd+ld_d,
#             jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
#             asphalt_fwd=asp_fwd, yields=yields)

#         if loc_fwd:
#             # Area chart: products stacked, crude as contrasting line
#             fwd_ok = [row for row in loc_fwd if row.get("crack_321")]
#             months  = [row["month"] for row in fwd_ok]
#             wti_fwd = [row["wti"]   for row in fwd_ok]
#             rbob_f  = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]
#             y_g = yields.get("gasoline",0.465)
#             y_d = yields.get("ulsd",    0.286)
#             y_j = yields.get("jet",     0.095)
#             y_b = yields.get("bunker",  0.048)
#             y_a = yields.get("asphalt", 0.036)

#             gas_rev  = [round((rb or 0)*y_g*42, 2) for rb in rbob_f]
#             die_rev  = [round((ul or 0)*y_d*42, 2) for ul in ulsd_f]
#             jet_rev  = [round(jet_fwd*y_j*42, 2)]  * len(months)
#             bnk_rev  = [round(bnk_fwd*y_b*42, 2)]  * len(months)
#             asp_rev  = [round(asp_fwd*y_a*42, 2)]   * len(months)

#             # Proper rgba color map — no string manipulation
#             AREA_COLORS = {
#                 "Gasoline": "rgba(74,144,217,0.75)",
#                 "Diesel":   "rgba(232,160,32,0.75)",
#                 "Jet Fuel": "rgba(90,158,58,0.75)",
#                 "Bunker":   "rgba(139,79,191,0.75)",
#                 "Asphalt":  "rgba(204,119,34,0.75)",
#             }

#             fig_fwd = go.Figure()
#             # Stacked area — products
#             for name, vals in [
#                 ("Gasoline", gas_rev),
#                 ("Diesel",   die_rev),
#                 ("Jet Fuel", jet_rev),
#                 ("Bunker",   bnk_rev),
#                 ("Asphalt",  asp_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one",
#                     line=dict(width=0),
#                 ))
#             # Crude cost line — white/contrast
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost (WTI+diff)",
#                 line=dict(color="#FFFFFF", width=2.5),
#                 mode="lines",
#                 hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             # 3-2-1 crack line overlay
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149", width=2, dash="dot"),
#                 yaxis="y2",
#                 hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",
#                            gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="Crack Spread ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y", side="right",
#                     showgrid=False,
#                     tickfont=dict(color="#F85149"),
#                 ),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10),
#                             orientation="h", yanchor="bottom", y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified",
#             )
#             # Annotation explaining the gap
#             fig_fwd.add_annotation(
#                 x=months[len(months)//2] if months else 0,
#                 y=wti_fwd[len(wti_fwd)//2]+5 if wti_fwd else 50,
#                 text="↑ Gap above line = Margin",
#                 showarrow=False, font=dict(color="#FFFFFF", size=10),
#                 bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = total product revenue by type. "
#                 "White line = crude cost (WTI + location diff). "
#                 "The gap above the white line is the implied refinery margin. "
#                 "Red dashed line (right axis) = 3-2-1 crack spread."
#             )

#             # Full Yield forward stress chart ±20%
#             full_vals = [row.get("crack_full") for row in fwd_ok]
#             if any(v for v in full_vals):
#                 # Stress: crude +20%, products -20% (worst case compression)
#                 fwd_stress_up = compute_forward_crack(
#                     strip=strip,
#                     crude_diff   = fcd + lc_d + (wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff     = fgd + lg_d - 0.20,
#                     diesel_diff  = fdd + ld_d - 0.20,
#                     jet_fwd      = jet_fwd * 0.80,
#                     bunker_fwd   = bnk_fwd  * 0.80,
#                     asphalt_fwd  = asp_fwd  * 0.80,
#                     yields       = yields,
#                 )
#                 fwd_stress_dn = compute_forward_crack(
#                     strip=strip,
#                     crude_diff   = fcd + lc_d - (wti_fwd[0]*0.20 if wti_fwd else 0),
#                     gas_diff     = fgd + lg_d + 0.20,
#                     diesel_diff  = fdd + ld_d + 0.20,
#                     jet_fwd      = jet_fwd * 1.20,
#                     bunker_fwd   = bnk_fwd  * 1.20,
#                     asphalt_fwd  = asp_fwd  * 1.20,
#                     yields       = yields,
#                 )
#                 stress_up_vals = [row.get("crack_full")
#                                   for row in fwd_stress_up if row.get("crack_full")]
#                 stress_dn_vals = [row.get("crack_full")
#                                   for row in fwd_stress_dn if row.get("crack_full")]
#                 stress_mo_up   = [row["month"]
#                                   for row in fwd_stress_up if row.get("crack_full")]
#                 stress_mo_dn   = [row["month"]
#                                   for row in fwd_stress_dn if row.get("crack_full")]
#                 full_mo        = [row["month"] for row in fwd_ok if row.get("crack_full")]
#                 full_ok_vals   = [v for v in full_vals if v is not None]

#                 fig_stress = go.Figure()

#                 # Stress band fill (worst case up, best case down)
#                 if stress_up_vals and stress_dn_vals and len(stress_up_vals)==len(full_ok_vals):
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_up + stress_mo_up[::-1],
#                         y=stress_up_vals + full_ok_vals[::-1],
#                         fill="toself",
#                         fillcolor="rgba(248,81,73,0.12)",
#                         line=dict(width=0),
#                         name="Downside: crude +20%, products −20%",
#                         hoverinfo="skip",
#                     ))
#                 if stress_dn_vals and len(stress_dn_vals)==len(full_ok_vals):
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_dn + stress_mo_dn[::-1],
#                         y=stress_dn_vals + full_ok_vals[::-1],
#                         fill="toself",
#                         fillcolor="rgba(63,185,80,0.10)",
#                         line=dict(width=0),
#                         name="Upside: crude −20%, products +20%",
#                         hoverinfo="skip",
#                     ))

#                 # Base case Full Yield line
#                 fig_stress.add_trace(go.Scatter(
#                     x=full_mo, y=full_ok_vals,
#                     name="Full Yield GRM — Base",
#                     line=dict(color="#E8A020", width=2.5),
#                     mode="lines+markers", marker=dict(size=5),
#                 ))
#                 # Stress boundary lines
#                 if stress_up_vals:
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_up, y=stress_up_vals,
#                         name="Downside boundary",
#                         line=dict(color="#F85149", width=1.5, dash="dash"),
#                     ))
#                 if stress_dn_vals:
#                     fig_stress.add_trace(go.Scatter(
#                         x=stress_mo_dn, y=stress_dn_vals,
#                         name="Upside boundary",
#                         line=dict(color="#3FB950", width=1.5, dash="dash"),
#                     ))
#                 # Breakeven reference
#                 fig_stress.add_hline(
#                     y=15, line_dash="dot", line_color="#8B949E",
#                     opacity=0.5,
#                     annotation_text="~Breakeven $15/bbl",
#                     annotation_font_color="#8B949E",
#                     annotation_font_size=9,
#                 )
#                 fig_stress.update_layout(
#                     title=dict(
#                         text="Full Yield GRM — Forward Stress Test ±20%",
#                         font=dict(color="#E6EDF3", size=13),
#                     ),
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                     yaxis=dict(title="Full Yield GRM ($/bbl)",
#                                gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                                 font=dict(size=10),
#                                 orientation="h", yanchor="bottom", y=1.02),
#                     margin=dict(l=0, r=0, t=40, b=0), height=320,
#                 )
#                 st.plotly_chart(fig_stress, use_container_width=True)
#                 st.caption(
#                     "Base case = Full Yield GRM at current inputs. "
#                     "Red band = downside scenario (crude +20%, products −20%). "
#                     "Green band = upside scenario (crude −20%, products +20%). "
#                     "The width of the band shows your margin sensitivity."
#                 )

#             # GRM forward table
#             tp = r.get("throughput", 30000)
#             if tp and crack_vals:
#                 grm_fwd = [round(v*tp*30/1e6,2) if v else None
#                            for v in crack_vals]
#                 fwd_df = pd.DataFrame({
#                     "Month":              months,
#                     "WTI ($/bbl)":        wti_fwd,
#                     "3-2-1 GRM ($/bbl)":  crack_vals,
#                     "Full Yield ($/bbl)": full_vals,
#                     "GRM ($MM/mo)":       grm_fwd,
#                 })
#                 with st.expander("Forward GRM Table"):
#                     st.dataframe(fwd_df, use_container_width=True,
#                                  hide_index=True)
#         else:
#             st.info("Forward curve data not available. Check CME connection.")

#     # ─── PANEL C: Full Calculator ─────────────────────────────────────────────
#     with st.expander("⚙️ Full Calculator — Change Any Input", expanded=False):
#         st.caption(
#             "All changes here update the snapshot and forward curve above. "
#             "Use this to answer any 'what if' question."
#         )
#         # Market prices
#         st.markdown("<div class='sec-hdr'>Market Prices</div>",
#                     unsafe_allow_html=True)
#         mp1,mp2,mp3,mp4 = st.columns(4)
#         if st.button("↺ Reset to Live", key="reset_live"):
#             live2 = get_spot(); spec2 = get_spec()
#             ul2   = live2.get("ulsd_gal",3.5) or 3.5
#             st.session_state.update({
#                 "wti":    live2.get("wti_bbl",80) or 80,
#                 "rbob":   live2.get("rbob_gal",2.5) or 2.5,
#                 "ulsd":   ul2,
#                 "jet":    spec2.get("jet_gal")    or ul2*1.05,
#                 "bunker": spec2.get("bunker_gal") or ul2*0.70,
#                 "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
#             })
#             st.rerun()
#         st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
#             float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
#         st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
#             float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
#         st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
#             float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
#         st.session_state["dist"]   = mp4.number_input("Dist. Margin ($/gal)",0.0,1.0,
#             float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

#         sp1,sp2,sp3,sp4 = st.columns(4)
#         st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
#             float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
#         st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
#             float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
#         st.session_state["catfeed"]= sp3.number_input("Cat Feed ($/gal)",0.2,10.0,
#             float(st.session_state.get("catfeed",1.9)),0.01,"%.3f",key=f"c_cat_{n}")
#         st.session_state["asphalt"]= sp4.number_input("Asphalt ($/gal)",0.1,8.0,
#             float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")

#         # Location diffs
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

#         # Yield %
#         st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
#                     unsafe_allow_html=True)
#         YLBLS = {"gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#                  "bunker":"Bunker","asphalt":"Asphalt","refinery_use":"Ref. Use"}
#         ycols = st.columns(6)
#         total_y = 0.0
#         for i,(k,lbl) in enumerate(YLBLS.items()):
#             default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#             val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
#                 float(st.session_state.get(f"y_{k}",default)),
#                 0.5,"%.1f",key=f"c_y_{k}_{n}")
#             st.session_state[f"y_{k}"] = val
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(f"<span style='color:{yc};font-size:12px'>"
#                     f"Total: {total_y:.1f}%</span>", unsafe_allow_html=True)

#         # Throughput
#         st.markdown("<div class='sec-hdr'>Throughput & Gross Refining Margin</div>",
#                     unsafe_allow_html=True)
#         tp_new = st.number_input("Throughput (bbl/day)",0,200000,
#             int(st.session_state.get(f"tp_{n}",30000)),1000,
#             key=f"c_tp_{n}")
#         st.session_state[f"tp_{n}"] = tp_new
#         if s321 and tp_new:
#             pnl_calc = round(s321 * tp_new * 30 / 1e6, 2)
#             annual   = round(pnl_calc * 12, 1)
#             st.markdown(
#                 f"<div style='background:#161B22;border:1px solid #30363D;"
#                 f"border-radius:8px;padding:14px;margin-top:8px'>"
#                 f"<span style='color:#8B949E;font-size:10px'>MONTHLY GRM</span><br>"
#                 f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
#                 f"font-family:monospace'>${pnl_calc:.2f}MM</span>&nbsp;"
#                 f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
#                 f"<span style='color:#8B949E;font-size:11px'>"
#                 f"${annual}MM annualized at ${s321:.2f}/bbl × "
#                 f"{tp_new:,} bbl/day</span></div>",
#                 unsafe_allow_html=True)

#         st.markdown("---")
#         # CSV download
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
#             "Cat Feed":           r.get("crude_catfeed"),
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

#     # Forward diffs (sidebar-style, at bottom of detail page)
#     with st.expander("Forward Curve Diffs", expanded=False):
#         fc1,fc2,fc3 = st.columns(3)
#         st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
#             -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",
#             key=f"fcd_{n}")
#         st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",
#             key=f"fgd_{n}")
#         st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",
#             key=f"fdd_{n}")


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

#     # Sidebar: just refresh
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
#             "**Portfolio view:** overview of all locations.\n\n"
#             "**Location detail:** click any location card to drill in — "
#             "current margin, forward curve, and full calculator.\n\n"
#             "All inputs in the calculator update the dashboard instantly."
#         )

#     with st.spinner("Loading market data..."):
#         strip = get_cme()
#         lp    = get_lp()

#     margins, spot, yields = build_margins(lp)
#     render_ticker(spot, margins)

#     view = st.session_state.get("view", "portfolio")

#     if view == "portfolio":
#         show_command(margins)
#     else:
#         show_detail(margins, strip, yields, lp)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;"
#         f"margin-top:8px'>AAA Fuel Gauge · EIA API · "
#         f"CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()

# # app.py — Rogue Refinery Economics v3 — Command + Detail Flow
# import streamlit as st
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

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── CSS ────────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;
#   flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:10px 0 6px 0}
# .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
#   padding:14px 16px;cursor:pointer;transition:border-color 0.15s}
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
# .whatif-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
# .wi-box{border-radius:8px;padding:12px;text-align:center}
# .wi-label{font-size:9px;letter-spacing:1px;text-transform:uppercase;
#   font-weight:600;margin-bottom:4px}
# .wi-base{font-size:11px;opacity:0.7;margin-bottom:2px}
# .wi-spread{font-size:20px;font-weight:700;font-family:monospace}
# .wi-delta{font-size:13px;font-weight:600;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# .block-container{padding-top:0.5rem !important}
# [data-testid="stAppViewContainer"]{padding-top:0 !important}
# [data-testid="stSidebar"]{background:#161B22}
# .stTabs [data-baseweb="tab-list"]{background:#161B22;border-radius:8px;padding:4px}
# .stTabs [data-baseweb="tab"]{color:#8B949E}
# .stTabs [aria-selected="true"]{background:#21262D;color:#E6EDF3;border-radius:6px}
# div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;
#   border-radius:8px}
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

# def fmt_pnl(spread, throughput):
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
# def get_cme():    return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot():   return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec():   return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     if st.session_state.get("_init"): return
#     live  = get_spot()
#     spec  = get_spec()
#     ulsd  = live.get("ulsd_gal", 3.50) or 3.50
#     wti   = live.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         "wti":      wti,
#         "rbob":     live.get("rbob_gal", 2.50) or 2.50,
#         "ulsd":     ulsd,
#         "jet":      spec.get("jet_gal")     or ulsd * 1.05,
#         "bunker":   spec.get("bunker_gal")  or ulsd * 0.70,
#         "catfeed":  wti * 0.95 / 42,
#         "asphalt":  spec.get("asphalt_gal") or ulsd * 0.60,
#         "dist":     0.35,
#         "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
#         "view": "portfolio",
#         "sel_loc": None,
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
#     spot = {"wti_bbl": st.session_state["wti"],
#             "rbob_gal": st.session_state["rbob"],
#             "ulsd_gal": st.session_state["ulsd"]}
#     spec = {"jet_gal":     st.session_state["jet"],
#             "bunker_gal":  st.session_state["bunker"],
#             "asphalt_gal": st.session_state["asphalt"]}
#     yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
#               for k, v in YIELD_DEFAULTS.items()}
#     locs = loc_overrides or []
#     if not locs:
#         for loc in LOCATIONS:
#             n = loc["display"]
#             o = dict(loc)
#             o["light_diff"]   = st.session_state.get(f"lc_{n}",  loc.get("light_diff",0))
#             o["heavy_diff"]   = st.session_state.get(f"lh_{n}",  loc.get("heavy_diff",0))
#             o["catfeed_diff"] = st.session_state.get(f"lcf_{n}", loc.get("catfeed_diff",0))
#             o["gas_diff"]     = st.session_state.get(f"lg_{n}",  loc.get("gas_diff",0))
#             o["diesel_diff"]  = st.session_state.get(f"ld_{n}",  loc.get("diesel_diff",0))
#             o["throughput"]   = st.session_state.get(f"tp_{n}",  30000)
#             locs.append(o)
#     margins = compute_location_margins(
#         locations=locs, spot_prices=spot, location_prices=lp,
#         specialty=spec, yields=yields,
#         dist_margin_gal=st.session_state["dist"])
#     for r in margins:
#         r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#         r["pnl"] = fmt_pnl(r.get("spread_321"), r["throughput"])
#     return margins, spot, yields


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
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
#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     pavg = round(sum(spreads)/len(spreads),2) if spreads else None
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
#         <span class="ticker-label">Portfolio P&L/mo</span>
#         <span class="ticker-value" style="color:#3FB950">
#           {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#         </span>
#         <span class="ticker-label">at throughput</span>
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
#     # Summary cards
#     valid = [r for r in margins if r.get("spread_321")]
#     if valid:
#         best  = max(valid, key=lambda x: x["spread_321"])
#         worst = min(valid, key=lambda x: x["spread_321"])
#         total_pnl = sum(r["pnl"] for r in valid if r.get("pnl"))
#         sc1, sc2, sc3 = st.columns(3)
#         sc1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Best Margin Today</div>
#             <div class='mc-value' style='color:#3FB950'>
#               ${best["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Thinnest Margin Today</div>
#             <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
#               ${worst["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Total Portfolio P&L / Month</div>
#             <div class='mc-value' style='color:#3FB950'>
#               {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#             </div>
#             <div class='mc-sub'>at current throughput & margins</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map — Tap a location for detail</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         c = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         map_rows.append({
#             "name": r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat": c[0], "lon": c[1],
#             "spread": s, "color": spread_color(s),
#             "pnl": r.get("pnl"),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"P&L: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
#                 f"<i>Click location card below to drill in</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"],
#         mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.90),
#         text=df_m["short"],
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text",
#     ))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]],
#                 mode="text",
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
#                  center=dict(lat=42, lon=-98), projection_scale=2.8,
#                  lonaxis_range=[-170,-50], lataxis_range=[15,72]),
#         paper_bgcolor="#0D1117",
#         margin=dict(l=0,r=0,t=0,b=0), height=400, showlegend=False)
#     for lbl, clr, ya in [("● STRONG ≥$25","#3FB950",0.13),
#                           ("● MODERATE $12–25","#E8A020",0.09),
#                           ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     # Location cards
#     st.markdown("<div class='sec-hdr'>Locations — Select to drill in</div>",
#                 unsafe_allow_html=True)
#     cols = st.columns(4)
#     for i, r in enumerate(margins):
#         s = r.get("spread_321")
#         clr = spread_color(s)
#         badge = spread_badge_class(s)
#         short = r["display"].split("—")[-1].split(",")[0].strip()
#         pnl_str = (f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—")
#         with cols[i % 4]:
#             st.markdown(f"""<div class='loc-card'>
#                 <div class='loc-card-name'>{short}</div>
#                 <div class='loc-card-spread' style='color:{clr}'>
#                     {"$"+str(s)+"/bbl" if s else "—"}
#                 </div>
#                 <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
#                 <div class='loc-card-pnl'>{pnl_str} · {r.get("source","").split("—")[-1][:12]}</div>
#             </div>""", unsafe_allow_html=True)
#             if st.button(f"Open →", key=f"btn_{i}", use_container_width=True):
#                 st.session_state["view"]    = "detail"
#                 st.session_state["sel_loc"] = r["display"]
#                 st.rerun()
#         if (i + 1) % 4 == 0 and i < len(margins)-1:
#             st.markdown("<br>", unsafe_allow_html=True)

#     # ── Portfolio download ─────────────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Portfolio Data Download</div>",
#                 unsafe_allow_html=True)
#     st.caption("Full price detail for every location — retail, pre-tax, "
#                "wholesale, crude prices, specialty products, and crack spreads.")

#     jet_p     = st.session_state.get("jet",     4.07)
#     bunker_p  = st.session_state.get("bunker",  2.52)
#     asphalt_p = st.session_state.get("asphalt", 2.16)

#     dl_rows = []
#     for r in margins:
#         n  = r["display"]
#         tp = r.get("throughput", 30000)
#         pnl_mo = fmt_pnl(r.get("spread_321"), tp)
#         dl_rows.append({
#             "Location":                      n,
#             "Price Source":                  r.get("source", "—"),
#             "Throughput (bbl/day)":          tp,
#             "Light Crude ($/bbl)":           r.get("crude_light"),
#             "Heavy Crude ($/bbl)":           r.get("crude_heavy"),
#             "Cat Feed / HGO ($/bbl)":        r.get("crude_catfeed"),
#             "Gasoline - Retail ($/gal)":     r.get("retail_gas"),
#             "Gasoline - Federal Tax":        r.get("federal_tax_gas"),
#             "Gasoline - State Tax":          r.get("state_tax_gas"),
#             "Gasoline - Pre-tax ($/gal)":    r.get("pretax_gas"),
#             "Gasoline - Dist Margin":        r.get("dist_margin"),
#             "Gasoline - Wholesale ($/gal)":  r.get("wholesale_gas"),
#             "Diesel - Retail ($/gal)":       r.get("retail_diesel"),
#             "Diesel - Pre-tax ($/gal)":      r.get("pretax_diesel"),
#             "Diesel - Wholesale ($/gal)":    r.get("wholesale_diesel"),
#             "Jet Fuel ($/gal)":              jet_p,
#             "Bunker Fuel ($/gal)":           bunker_p,
#             "Asphalt ($/gal)":               asphalt_p,
#             "3-2-1 Spread ($/bbl)":          r.get("spread_321"),
#             "2-1-1 Spread ($/bbl)":          r.get("spread_211"),
#             "5-3-2 Spread ($/bbl)":          r.get("spread_532"),
#             "Full Yield Spread ($/bbl)":     r.get("spread_full"),
#             "Monthly P&L ($MM)":             pnl_mo,
#             "Annual P&L ($MM)":              round(pnl_mo * 12, 2) if pnl_mo else None,
#             "As Of":                         datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })

#     df_dl = pd.DataFrame(dl_rows)

#     dl_col, tbl_col = st.columns([1, 2])
#     with dl_col:
#         st.download_button(
#             "⬇️ Download All Locations CSV",
#             data=df_dl.to_csv(index=False),
#             file_name=f"rogue_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
#             mime="text/csv",
#             use_container_width=True,
#         )
#     with tbl_col:
#         st.dataframe(
#             df_dl[[
#                 "Location",
#                 "Light Crude ($/bbl)", "Heavy Crude ($/bbl)",
#                 "Gasoline - Retail ($/gal)", "Gasoline - Wholesale ($/gal)",
#                 "Diesel - Retail ($/gal)",   "Diesel - Wholesale ($/gal)",
#                 "Jet Fuel ($/gal)", "Bunker Fuel ($/gal)", "Asphalt ($/gal)",
#                 "3-2-1 Spread ($/bbl)", "Full Yield Spread ($/bbl)",
#                 "Monthly P&L ($MM)",
#             ]],
#             use_container_width=True,
#             hide_index=True,
#         )


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(margins, strip, yields, lp):
#     sel = st.session_state.get("sel_loc")
#     r   = next((m for m in margins if m["display"]==sel), None)

#     # Back nav
#     bc, tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321 = r.get("spread_321") if r else None
#         clr  = spread_color(s321)
#         short = sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
#             f"<span style='color:{clr};font-family:monospace'>"
#             f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
#             f"</h3>",
#             unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     st.markdown("---")

#     # ─── PANEL A: Current Snapshot ────────────────────────────────────────────
#     with st.expander("📊 Current Margin Snapshot", expanded=True):
#         tp   = r.get("throughput", 30000)
#         pnl  = r.get("pnl")
#         sfull= r.get("spread_full")
#         s211 = r.get("spread_211")
#         s532 = r.get("spread_532")

#         # 4 spread formula cards
#         f1,f2,f3,f4,f5 = st.columns(5)
#         for col, lbl, val in [
#             (f1,"3-2-1",s321),(f2,"2-1-1",s211),
#             (f3,"5-3-2",s532),(f4,"Full Yield",sfull),
#         ]:
#             col.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>{lbl}</div>
#                 <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                     {"$"+str(val)+"/bbl" if val else "—"}
#                 </div>
#                 <div class='mc-sub'>{spread_label(val)}</div>
#             </div>""", unsafe_allow_html=True)
#         pnl_v = fmt_pnl(s321, tp)
#         f5.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>P&L / Month</div>
#             <div class='mc-value' style='color:#3FB950;font-size:18px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
#             </div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)
#         wa_col, wi_col = st.columns([1,1], gap="large")

#         # Waterfall
#         with wa_col:
#             st.markdown("<div class='sec-hdr'>Where Does the Margin Come From?</div>",
#                         unsafe_allow_html=True)
#             if r.get("retail_gas"):
#                 retail  = r["retail_gas"]
#                 fed     = r.get("federal_tax_gas", 0.184)
#                 state_t = r.get("state_tax_gas", 0.0)
#                 dist    = r.get("dist_margin", 0.35)
#                 ws      = r.get("wholesale_gas", 0.0)
#                 crude_g = (r.get("crude_light",0)) / 42
#                 mg      = (s321 or 0) / 42

#                 fig_wf = go.Figure(go.Waterfall(
#                     orientation="v",
#                     measure=["absolute","relative","relative","relative",
#                              "total","relative","total"],
#                     x=["Pump Price","− Fed Tax","− State Tax","− Dist.",
#                        "Wholesale","− Crude","Margin"],
#                     y=[retail,-fed,-state_t,-dist,0,-crude_g,0],
#                     text=[f"${retail:.3f}",f"-${fed:.3f}",f"-${state_t:.3f}",
#                           f"-${dist:.3f}",f"${ws:.3f}",
#                           f"-${crude_g:.3f}",f"${mg:.3f}" if s321 else "—"],
#                     textposition="outside",
#                     textfont=dict(size=10,color="#E6EDF3"),
#                     connector=dict(line=dict(color="#30363D",width=1)),
#                     decreasing=dict(marker_color="#F85149"),
#                     increasing=dict(marker_color="#3FB950"),
#                     totals=dict(marker_color="#E8A020"),
#                 ))
#                 fig_wf.update_layout(
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/gal",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D",tickangle=-20),
#                     margin=dict(l=0,r=0,t=8,b=0),height=300,showlegend=False)
#                 st.plotly_chart(fig_wf, use_container_width=True)

#         # What-if 2×2 grid
#         with wi_col:
#             st.markdown("<div class='sec-hdr'>What-If — 4 Scenarios vs Base</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 base    = s321 or 0
#                 crude_b = r["crude_light"]
#                 gas_b   = r["wholesale_gas"]
#                 die_b   = r.get("wholesale_diesel", gas_b)

#                 scenarios = [
#                     ("Crude +25%",   crude_b*1.25, gas_b,     die_b),
#                     ("Products +25%",crude_b,      gas_b*1.25,die_b*1.25),
#                     ("Crude −25%",   crude_b*0.75, gas_b,     die_b),
#                     ("Products −25%",crude_b,      gas_b*0.75,die_b*0.75),
#                 ]
#                 boxes = []
#                 for lbl, c, g, d in scenarios:
#                     val   = round(_c321(c, g, d), 2)
#                     delta = round(val - base, 2)
#                     is_up = delta >= 0
#                     bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                     clr   = "#3FB950" if is_up else "#F85149"
#                     boxes.append((lbl, val, delta, bg, clr, is_up))

#                 # Render as 2×2 using columns
#                 r1c1, r1c2 = st.columns(2)
#                 r2c1, r2c2 = st.columns(2)
#                 for col, (lbl, val, delta, bg, clr, is_up) in zip(
#                     [r1c1,r1c2,r2c1,r2c2], boxes
#                 ):
#                     sign = "▲" if is_up else "▼"
#                     col.markdown(f"""
#                     <div style='background:{bg};border-radius:8px;padding:14px;
#                          text-align:center;margin-bottom:4px'>
#                       <div style='font-size:9px;color:{clr};letter-spacing:1px;
#                            text-transform:uppercase;font-weight:600'>{lbl}</div>
#                       <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                           Base: ${base:.2f}</div>
#                       <div style='font-size:20px;font-weight:700;
#                            font-family:monospace;color:{clr}'>${val:.2f}</div>
#                       <div style='font-size:13px;font-weight:600;color:{clr}'>
#                           {sign} {sign_str(delta)}/bbl</div>
#                     </div>""", unsafe_allow_html=True)

#                 # Product contribution bar
#                 st.markdown("<br>", unsafe_allow_html=True)
#                 st.markdown("<div class='sec-hdr'>Margin by Product Contribution</div>",
#                             unsafe_allow_html=True)
#                 ws_gas  = r.get("wholesale_gas",  0)
#                 ws_die  = r.get("wholesale_diesel",0)
#                 jet_p   = st.session_state.get("jet",    4.07)
#                 bnk_p   = st.session_state.get("bunker", 2.52)
#                 asp_p   = st.session_state.get("asphalt",2.16)
#                 crude_b2= r.get("crude_light",0)

#                 y_gas = yields.get("gasoline",0.465)
#                 y_die = yields.get("ulsd",    0.286)
#                 y_jet = yields.get("jet",     0.095)
#                 y_bnk = yields.get("bunker",  0.048)
#                 y_asp = yields.get("asphalt", 0.036)

#                 contrib = {
#                     "Gasoline": round(ws_gas*y_gas*42, 2),
#                     "Diesel":   round(ws_die*y_die*42, 2),
#                     "Jet Fuel": round(jet_p *y_jet*42, 2),
#                     "Bunker":   round(bnk_p *y_bnk*42, 2),
#                     "Asphalt":  round(asp_p *y_asp*42, 2),
#                 }
#                 colors_c = ["#4A90D9","#E8A020","#5A9E3A","#8B4FBF","#CC7722"]
#                 fig_c = go.Figure()
#                 for (prod, val_c), clr_c in zip(contrib.items(), colors_c):
#                     fig_c.add_trace(go.Bar(
#                         name=prod, x=["Product Revenue"],
#                         y=[val_c], marker_color=clr_c,
#                         text=[f"${val_c:.1f}"],
#                         textposition="inside",
#                         textfont=dict(size=10,color="#E6EDF3")))
#                 fig_c.add_hline(y=crude_b2,
#                     line_color="#F85149",line_width=2,line_dash="solid",
#                     annotation_text=f"Crude cost ${crude_b2:.2f}/bbl",
#                     annotation_font_color="#F85149",annotation_font_size=10)
#                 fig_c.update_layout(
#                     barmode="stack",
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=10),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=30,b=0),height=220)
#                 st.plotly_chart(fig_c, use_container_width=True)

#     # ─── PANEL B: Forward View ────────────────────────────────────────────────
#     with st.expander("📈 Forward Crack Spread", expanded=True):
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#         n       = sel
#         lc_d    = st.session_state.get(f"lc_{n}",  loc_cfg.get("light_diff",0))
#         lg_d    = st.session_state.get(f"lg_{n}",  loc_cfg.get("gas_diff",0))
#         ld_d    = st.session_state.get(f"ld_{n}",  loc_cfg.get("diesel_diff",0))
#         fcd     = st.session_state.get("fcd",0)
#         fgd     = st.session_state.get("fgd",0)
#         fdd     = st.session_state.get("fdd",0)
#         jet_fwd = st.session_state.get("jet",   4.07)
#         bnk_fwd = st.session_state.get("bunker",2.52)
#         asp_fwd = st.session_state.get("asphalt",2.16)

#         # Inline forward price inputs
#         fi1,fi2,fi3,fi4 = st.columns(4)
#         jet_fwd  = fi1.number_input("Jet Fuel fwd ($/gal)",0.5,15.0,
#             float(jet_fwd), 0.01,"%.3f",key="fwd_jet_d")
#         bnk_fwd  = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
#             float(bnk_fwd), 0.01,"%.3f",key="fwd_bnk_d")
#         asp_fwd  = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
#             float(asp_fwd), 0.01,"%.3f",key="fwd_asp_d")
#         cat_fwd  = fi4.number_input("Cat Feed fwd ($/gal)",0.5,10.0,
#             float(st.session_state.get("catfeed",1.90)),
#             0.01,"%.3f",key="fwd_cat_d")

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = fcd+lc_d,
#             gas_diff    = fgd+lg_d,
#             diesel_diff = fdd+ld_d,
#             jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
#             asphalt_fwd=asp_fwd, yields=yields)

#         if loc_fwd:
#             # Area chart: products stacked, crude as contrasting line
#             fwd_ok = [row for row in loc_fwd if row.get("crack_321")]
#             months  = [row["month"] for row in fwd_ok]
#             wti_fwd = [row["wti"]   for row in fwd_ok]
#             rbob_f  = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]
#             y_g = yields.get("gasoline",0.465)
#             y_d = yields.get("ulsd",    0.286)
#             y_j = yields.get("jet",     0.095)
#             y_b = yields.get("bunker",  0.048)
#             y_a = yields.get("asphalt", 0.036)

#             gas_rev  = [round((rb or 0)*y_g*42, 2) for rb in rbob_f]
#             die_rev  = [round((ul or 0)*y_d*42, 2) for ul in ulsd_f]
#             jet_rev  = [round(jet_fwd*y_j*42, 2)]  * len(months)
#             bnk_rev  = [round(bnk_fwd*y_b*42, 2)]  * len(months)
#             asp_rev  = [round(asp_fwd*y_a*42, 2)]   * len(months)

#             # Proper rgba color map — no string manipulation
#             AREA_COLORS = {
#                 "Gasoline": "rgba(74,144,217,0.75)",
#                 "Diesel":   "rgba(232,160,32,0.75)",
#                 "Jet Fuel": "rgba(90,158,58,0.75)",
#                 "Bunker":   "rgba(139,79,191,0.75)",
#                 "Asphalt":  "rgba(204,119,34,0.75)",
#             }

#             fig_fwd = go.Figure()
#             # Stacked area — products
#             for name, vals in [
#                 ("Gasoline", gas_rev),
#                 ("Diesel",   die_rev),
#                 ("Jet Fuel", jet_rev),
#                 ("Bunker",   bnk_rev),
#                 ("Asphalt",  asp_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one",
#                     line=dict(width=0),
#                 ))
#             # Crude cost line — white/contrast
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost (WTI+diff)",
#                 line=dict(color="#FFFFFF", width=2.5),
#                 mode="lines",
#                 hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             # 3-2-1 crack line overlay
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149", width=2, dash="dot"),
#                 yaxis="y2",
#                 hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",
#                            gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="Crack Spread ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y", side="right",
#                     showgrid=False,
#                     tickfont=dict(color="#F85149"),
#                 ),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10),
#                             orientation="h", yanchor="bottom", y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified",
#             )
#             # Annotation explaining the gap
#             fig_fwd.add_annotation(
#                 x=months[len(months)//2] if months else 0,
#                 y=wti_fwd[len(wti_fwd)//2]+5 if wti_fwd else 50,
#                 text="↑ Gap above line = Margin",
#                 showarrow=False, font=dict(color="#FFFFFF", size=10),
#                 bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = total product revenue by type. "
#                 "White line = crude cost (WTI + location diff). "
#                 "The gap above the white line is the implied refinery margin. "
#                 "Red dashed line (right axis) = 3-2-1 crack spread."
#             )

#             # P&L forward table
#             tp = r.get("throughput", 30000)
#             if tp and crack_vals:
#                 pnl_fwd = [round(v*tp*30/1e6,2) if v else None
#                            for v in crack_vals]
#                 fwd_df = pd.DataFrame({
#                     "Month":         months,
#                     "WTI ($/bbl)":   wti_fwd,
#                     "3-2-1 ($/bbl)": crack_vals,
#                     "P&L ($MM/mo)":  pnl_fwd,
#                 })
#                 with st.expander("Forward P&L Table"):
#                     st.dataframe(fwd_df, use_container_width=True,
#                                  hide_index=True)
#         else:
#             st.info("Forward curve data not available. Check CME connection.")

#     # ─── PANEL C: Full Calculator ─────────────────────────────────────────────
#     with st.expander("⚙️ Full Calculator — Change Any Input", expanded=False):
#         st.caption(
#             "All changes here update the snapshot and forward curve above. "
#             "Use this to answer any 'what if' question."
#         )
#         # Market prices
#         st.markdown("<div class='sec-hdr'>Market Prices</div>",
#                     unsafe_allow_html=True)
#         mp1,mp2,mp3,mp4 = st.columns(4)
#         if st.button("↺ Reset to Live", key="reset_live"):
#             live2 = get_spot(); spec2 = get_spec()
#             ul2   = live2.get("ulsd_gal",3.5) or 3.5
#             st.session_state.update({
#                 "wti":    live2.get("wti_bbl",80) or 80,
#                 "rbob":   live2.get("rbob_gal",2.5) or 2.5,
#                 "ulsd":   ul2,
#                 "jet":    spec2.get("jet_gal")    or ul2*1.05,
#                 "bunker": spec2.get("bunker_gal") or ul2*0.70,
#                 "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
#             })
#             st.rerun()
#         st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
#             float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
#         st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
#             float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
#         st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
#             float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
#         st.session_state["dist"]   = mp4.number_input("Dist. Margin ($/gal)",0.0,1.0,
#             float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

#         sp1,sp2,sp3,sp4 = st.columns(4)
#         st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
#             float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
#         st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
#             float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
#         st.session_state["catfeed"]= sp3.number_input("Cat Feed ($/gal)",0.2,10.0,
#             float(st.session_state.get("catfeed",1.9)),0.01,"%.3f",key=f"c_cat_{n}")
#         st.session_state["asphalt"]= sp4.number_input("Asphalt ($/gal)",0.1,8.0,
#             float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")

#         # Location diffs
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

#         # Yield %
#         st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
#                     unsafe_allow_html=True)
#         YLBLS = {"gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#                  "bunker":"Bunker","asphalt":"Asphalt","refinery_use":"Ref. Use"}
#         ycols = st.columns(6)
#         total_y = 0.0
#         for i,(k,lbl) in enumerate(YLBLS.items()):
#             default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#             val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
#                 float(st.session_state.get(f"y_{k}",default)),
#                 0.5,"%.1f",key=f"c_y_{k}_{n}")
#             st.session_state[f"y_{k}"] = val
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(f"<span style='color:{yc};font-size:12px'>"
#                     f"Total: {total_y:.1f}%</span>", unsafe_allow_html=True)

#         # Throughput
#         st.markdown("<div class='sec-hdr'>Throughput & P&L</div>",
#                     unsafe_allow_html=True)
#         tp_new = st.number_input("Throughput (bbl/day)",0,200000,
#             int(st.session_state.get(f"tp_{n}",30000)),1000,
#             key=f"c_tp_{n}")
#         st.session_state[f"tp_{n}"] = tp_new
#         if s321 and tp_new:
#             pnl_calc = round(s321 * tp_new * 30 / 1e6, 2)
#             annual   = round(pnl_calc * 12, 1)
#             st.markdown(
#                 f"<div style='background:#161B22;border:1px solid #30363D;"
#                 f"border-radius:8px;padding:14px;margin-top:8px'>"
#                 f"<span style='color:#8B949E;font-size:10px'>MONTHLY P&L</span><br>"
#                 f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
#                 f"font-family:monospace'>${pnl_calc:.2f}MM</span>&nbsp;"
#                 f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
#                 f"<span style='color:#8B949E;font-size:11px'>"
#                 f"${annual}MM annualized at ${s321:.2f}/bbl × "
#                 f"{tp_new:,} bbl/day</span></div>",
#                 unsafe_allow_html=True)

#         st.markdown("---")
#         # CSV download
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
#             "Cat Feed":           r.get("crude_catfeed"),
#             "3-2-1 ($/bbl)":      r.get("spread_321"),
#             "2-1-1 ($/bbl)":      r.get("spread_211"),
#             "5-3-2 ($/bbl)":      r.get("spread_532"),
#             "Full Yield ($/bbl)": r.get("spread_full"),
#             "Throughput (bbl/d)": tp_new,
#             "P&L ($MM/mo)":       fmt_pnl(s321, tp_new),
#             "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
#         }
#         st.download_button(
#             f"⬇️ Download {short} Detail CSV",
#             data=pd.DataFrame([dl_row]).to_csv(index=False),
#             file_name=f"rogue_{short.replace(' ','_').lower()}.csv",
#             mime="text/csv", use_container_width=True)

#     # Forward diffs (sidebar-style, at bottom of detail page)
#     with st.expander("Forward Curve Diffs", expanded=False):
#         fc1,fc2,fc3 = st.columns(3)
#         st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
#             -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",
#             key=f"fcd_{n}")
#         st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",
#             key=f"fgd_{n}")
#         st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",
#             key=f"fdd_{n}")


# # ══════════════════════════════════════════════════════════════════════════════
# # MAIN
# # ══════════════════════════════════════════════════════════════════════════════
# def main():
#     check_password()
#     init_state()

#     st.markdown(
#         "<h2 style='color:#E6EDF3;margin-bottom:2px;margin-top:-2px'>"
#         "🏭 Rogue Refinery Economics</h2>"
#         "<p style='color:#8B949E;margin-bottom:10px;font-size:12px'>"
#         "Portfolio intelligence · CME forward curves · "
#         "Scenario analysis · Throughput P&L</p>",
#         unsafe_allow_html=True)

#     # Sidebar: just refresh
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
#             "**Portfolio view:** overview of all locations.\n\n"
#             "**Location detail:** click any location card to drill in — "
#             "current margin, forward curve, and full calculator.\n\n"
#             "All inputs in the calculator update the dashboard instantly."
#         )

#     with st.spinner("Loading market data..."):
#         strip = get_cme()
#         lp    = get_lp()

#     margins, spot, yields = build_margins(lp)
#     render_ticker(spot, margins)

#     view = st.session_state.get("view", "portfolio")

#     if view == "portfolio":
#         show_command(margins)
#     else:
#         show_detail(margins, strip, yields, lp)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;"
#         f"margin-top:8px'>AAA Fuel Gauge · EIA API · "
#         f"CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()



# # app.py — Rogue Refinery Economics v3 — Command + Detail Flow
# import streamlit as st
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

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── CSS ────────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:24px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:10px 20px;margin-bottom:12px;align-items:center;
#   flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:9px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:18px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:32px;background:#30363D;flex-shrink:0}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:10px 0 6px 0}
# .loc-card{background:#161B22;border:1px solid #30363D;border-radius:10px;
#   padding:14px 16px;cursor:pointer;transition:border-color 0.15s}
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
# .whatif-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
# .wi-box{border-radius:8px;padding:12px;text-align:center}
# .wi-label{font-size:9px;letter-spacing:1px;text-transform:uppercase;
#   font-weight:600;margin-bottom:4px}
# .wi-base{font-size:11px;opacity:0.7;margin-bottom:2px}
# .wi-spread{font-size:20px;font-weight:700;font-family:monospace}
# .wi-delta{font-size:13px;font-weight:600;margin-top:2px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# [data-testid="stSidebar"]{background:#161B22}
# .stTabs [data-baseweb="tab-list"]{background:#161B22;border-radius:8px;padding:4px}
# .stTabs [data-baseweb="tab"]{color:#8B949E}
# .stTabs [aria-selected="true"]{background:#21262D;color:#E6EDF3;border-radius:6px}
# div[data-testid="stExpander"]{background:#161B22;border:1px solid #30363D;
#   border-radius:8px}
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

# def fmt_pnl(spread, throughput):
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
# def get_cme():    return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot():   return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_lp():     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_spec():   return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     if st.session_state.get("_init"): return
#     live  = get_spot()
#     spec  = get_spec()
#     ulsd  = live.get("ulsd_gal", 3.50) or 3.50
#     wti   = live.get("wti_bbl",  80.0) or 80.0
#     st.session_state.update({
#         "wti":      wti,
#         "rbob":     live.get("rbob_gal", 2.50) or 2.50,
#         "ulsd":     ulsd,
#         "jet":      spec.get("jet_gal")     or ulsd * 1.05,
#         "bunker":   spec.get("bunker_gal")  or ulsd * 0.70,
#         "catfeed":  wti * 0.95 / 42,
#         "asphalt":  spec.get("asphalt_gal") or ulsd * 0.60,
#         "dist":     0.35,
#         "fcd": 0.0, "fgd": 0.0, "fdd": 0.0,
#         "view": "portfolio",
#         "sel_loc": None,
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
#     spot = {"wti_bbl": st.session_state["wti"],
#             "rbob_gal": st.session_state["rbob"],
#             "ulsd_gal": st.session_state["ulsd"]}
#     spec = {"jet_gal":     st.session_state["jet"],
#             "bunker_gal":  st.session_state["bunker"],
#             "asphalt_gal": st.session_state["asphalt"]}
#     yields = {k: round(st.session_state.get(f"y_{k}", v*100)/100, 6)
#               for k, v in YIELD_DEFAULTS.items()}
#     locs = loc_overrides or []
#     if not locs:
#         for loc in LOCATIONS:
#             n = loc["display"]
#             o = dict(loc)
#             o["light_diff"]   = st.session_state.get(f"lc_{n}",  loc.get("light_diff",0))
#             o["heavy_diff"]   = st.session_state.get(f"lh_{n}",  loc.get("heavy_diff",0))
#             o["catfeed_diff"] = st.session_state.get(f"lcf_{n}", loc.get("catfeed_diff",0))
#             o["gas_diff"]     = st.session_state.get(f"lg_{n}",  loc.get("gas_diff",0))
#             o["diesel_diff"]  = st.session_state.get(f"ld_{n}",  loc.get("diesel_diff",0))
#             o["throughput"]   = st.session_state.get(f"tp_{n}",  30000)
#             locs.append(o)
#     margins = compute_location_margins(
#         locations=locs, spot_prices=spot, location_prices=lp,
#         specialty=spec, yields=yields,
#         dist_margin_gal=st.session_state["dist"])
#     for r in margins:
#         r["throughput"] = st.session_state.get(f"tp_{r['display']}", 30000)
#         r["pnl"] = fmt_pnl(r.get("spread_321"), r["throughput"])
#     return margins, spot, yields


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
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
#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     pavg = round(sum(spreads)/len(spreads),2) if spreads else None
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
#         <span class="ticker-label">Portfolio P&L/mo</span>
#         <span class="ticker-value" style="color:#3FB950">
#           {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#         </span>
#         <span class="ticker-label">at throughput</span>
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
#     # Summary cards
#     valid = [r for r in margins if r.get("spread_321")]
#     if valid:
#         best  = max(valid, key=lambda x: x["spread_321"])
#         worst = min(valid, key=lambda x: x["spread_321"])
#         total_pnl = sum(r["pnl"] for r in valid if r.get("pnl"))
#         sc1, sc2, sc3 = st.columns(3)
#         sc1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Best Margin Today</div>
#             <div class='mc-value' style='color:#3FB950'>
#               ${best["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{best["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Thinnest Margin Today</div>
#             <div class='mc-value' style='color:{spread_color(worst["spread_321"])}'>
#               ${worst["spread_321"]:.2f}/bbl
#             </div>
#             <div class='mc-sub'>{worst["display"].split("—")[-1].split(",")[0].strip()}</div>
#         </div>""", unsafe_allow_html=True)
#         sc3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Total Portfolio P&L / Month</div>
#             <div class='mc-value' style='color:#3FB950'>
#               {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#             </div>
#             <div class='mc-sub'>at current throughput & margins</div>
#         </div>""", unsafe_allow_html=True)
#         st.markdown("<br>", unsafe_allow_html=True)

#     # Map
#     st.markdown("<div class='sec-hdr'>Portfolio Map — Tap a location for detail</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         c = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         map_rows.append({
#             "name": r["display"],
#             "short": r["display"].split("—")[-1].split(",")[0].strip(),
#             "lat": c[0], "lon": c[1],
#             "spread": s, "color": spread_color(s),
#             "pnl": r.get("pnl"),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1: {'$'+str(s)+'/bbl' if s else '—'} — {spread_label(s)}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"P&L: {'$'+str(r['pnl'])+'MM/mo' if r.get('pnl') else '—'}<br>"
#                 f"<i>Click location card below to drill in</i>"
#             ),
#         })
#     df_m = pd.DataFrame(map_rows)
#     fig_m = go.Figure()
#     fig_m.add_trace(go.Scattergeo(
#         lat=df_m["lat"], lon=df_m["lon"],
#         mode="markers+text",
#         marker=dict(size=20, color=df_m["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.90),
#         text=df_m["short"],
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_m["hover"], hoverinfo="text",
#     ))
#     for _, row in df_m.iterrows():
#         if row["spread"]:
#             fig_m.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.9], lon=[row["lon"]],
#                 mode="text",
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
#                  center=dict(lat=42, lon=-98), projection_scale=2.8,
#                  lonaxis_range=[-170,-50], lataxis_range=[15,72]),
#         paper_bgcolor="#0D1117",
#         margin=dict(l=0,r=0,t=0,b=0), height=400, showlegend=False)
#     for lbl, clr, ya in [("● STRONG ≥$25","#3FB950",0.13),
#                           ("● MODERATE $12–25","#E8A020",0.09),
#                           ("● THIN <$12","#F85149",0.05)]:
#         fig_m.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_m, use_container_width=True)

#     # Location cards
#     st.markdown("<div class='sec-hdr'>Locations — Select to drill in</div>",
#                 unsafe_allow_html=True)
#     cols = st.columns(4)
#     for i, r in enumerate(margins):
#         s = r.get("spread_321")
#         clr = spread_color(s)
#         badge = spread_badge_class(s)
#         short = r["display"].split("—")[-1].split(",")[0].strip()
#         pnl_str = (f"${r['pnl']:.1f}MM/mo" if r.get("pnl") else "—")
#         with cols[i % 4]:
#             st.markdown(f"""<div class='loc-card'>
#                 <div class='loc-card-name'>{short}</div>
#                 <div class='loc-card-spread' style='color:{clr}'>
#                     {"$"+str(s)+"/bbl" if s else "—"}
#                 </div>
#                 <span class='loc-card-badge {badge}'>{spread_label(s)}</span>
#                 <div class='loc-card-pnl'>{pnl_str} · {r.get("source","").split("—")[-1][:12]}</div>
#             </div>""", unsafe_allow_html=True)
#             if st.button(f"Open →", key=f"btn_{i}", use_container_width=True):
#                 st.session_state["view"]    = "detail"
#                 st.session_state["sel_loc"] = r["display"]
#                 st.rerun()
#         if (i + 1) % 4 == 0 and i < len(margins)-1:
#             st.markdown("<br>", unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # PAGE 2 — LOCATION DETAIL
# # ══════════════════════════════════════════════════════════════════════════════
# def show_detail(margins, strip, yields, lp):
#     sel = st.session_state.get("sel_loc")
#     r   = next((m for m in margins if m["display"]==sel), None)

#     # Back nav
#     bc, tc = st.columns([1,8])
#     with bc:
#         if st.button("← Portfolio"):
#             st.session_state["view"] = "portfolio"
#             st.rerun()
#     with tc:
#         s321 = r.get("spread_321") if r else None
#         clr  = spread_color(s321)
#         short = sel.split("—")[-1].split(",")[0].strip() if sel else "—"
#         st.markdown(
#             f"<h3 style='color:#E6EDF3;margin:0'>{short} &nbsp;"
#             f"<span style='color:{clr};font-family:monospace'>"
#             f"{'$'+str(s321)+'/bbl' if s321 else '—'}</span>&nbsp;"
#             f"<span style='font-size:14px;color:{clr}'>{spread_label(s321)}</span>"
#             f"</h3>",
#             unsafe_allow_html=True)

#     if not r:
#         st.warning("No data for this location.")
#         return

#     st.markdown("---")

#     # ─── PANEL A: Current Snapshot ────────────────────────────────────────────
#     with st.expander("📊 Current Margin Snapshot", expanded=True):
#         tp   = r.get("throughput", 30000)
#         pnl  = r.get("pnl")
#         sfull= r.get("spread_full")
#         s211 = r.get("spread_211")
#         s532 = r.get("spread_532")

#         # 4 spread formula cards
#         f1,f2,f3,f4,f5 = st.columns(5)
#         for col, lbl, val in [
#             (f1,"3-2-1",s321),(f2,"2-1-1",s211),
#             (f3,"5-3-2",s532),(f4,"Full Yield",sfull),
#         ]:
#             col.markdown(f"""<div class='metric-card'>
#                 <div class='mc-label'>{lbl}</div>
#                 <div class='mc-value' style='color:{spread_color(val)};font-size:18px'>
#                     {"$"+str(val)+"/bbl" if val else "—"}
#                 </div>
#                 <div class='mc-sub'>{spread_label(val)}</div>
#             </div>""", unsafe_allow_html=True)
#         pnl_v = fmt_pnl(s321, tp)
#         f5.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>P&L / Month</div>
#             <div class='mc-value' style='color:#3FB950;font-size:18px'>
#                 {"$"+str(pnl_v)+"MM" if pnl_v else "—"}
#             </div>
#             <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         st.markdown("<br>", unsafe_allow_html=True)
#         wa_col, wi_col = st.columns([1,1], gap="large")

#         # Waterfall
#         with wa_col:
#             st.markdown("<div class='sec-hdr'>Where Does the Margin Come From?</div>",
#                         unsafe_allow_html=True)
#             if r.get("retail_gas"):
#                 retail  = r["retail_gas"]
#                 fed     = r.get("federal_tax_gas", 0.184)
#                 state_t = r.get("state_tax_gas", 0.0)
#                 dist    = r.get("dist_margin", 0.35)
#                 ws      = r.get("wholesale_gas", 0.0)
#                 crude_g = (r.get("crude_light",0)) / 42
#                 mg      = (s321 or 0) / 42

#                 fig_wf = go.Figure(go.Waterfall(
#                     orientation="v",
#                     measure=["absolute","relative","relative","relative",
#                              "total","relative","total"],
#                     x=["Pump Price","− Fed Tax","− State Tax","− Dist.",
#                        "Wholesale","− Crude","Margin"],
#                     y=[retail,-fed,-state_t,-dist,0,-crude_g,0],
#                     text=[f"${retail:.3f}",f"-${fed:.3f}",f"-${state_t:.3f}",
#                           f"-${dist:.3f}",f"${ws:.3f}",
#                           f"-${crude_g:.3f}",f"${mg:.3f}" if s321 else "—"],
#                     textposition="outside",
#                     textfont=dict(size=10,color="#E6EDF3"),
#                     connector=dict(line=dict(color="#30363D",width=1)),
#                     decreasing=dict(marker_color="#F85149"),
#                     increasing=dict(marker_color="#3FB950"),
#                     totals=dict(marker_color="#E8A020"),
#                 ))
#                 fig_wf.update_layout(
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/gal",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D",tickangle=-20),
#                     margin=dict(l=0,r=0,t=8,b=0),height=300,showlegend=False)
#                 st.plotly_chart(fig_wf, use_container_width=True)

#         # What-if 2×2 grid
#         with wi_col:
#             st.markdown("<div class='sec-hdr'>What-If — 4 Scenarios vs Base</div>",
#                         unsafe_allow_html=True)
#             if r.get("crude_light") and r.get("wholesale_gas"):
#                 base    = s321 or 0
#                 crude_b = r["crude_light"]
#                 gas_b   = r["wholesale_gas"]
#                 die_b   = r.get("wholesale_diesel", gas_b)

#                 scenarios = [
#                     ("Crude +25%",   crude_b*1.25, gas_b,     die_b),
#                     ("Products +25%",crude_b,      gas_b*1.25,die_b*1.25),
#                     ("Crude −25%",   crude_b*0.75, gas_b,     die_b),
#                     ("Products −25%",crude_b,      gas_b*0.75,die_b*0.75),
#                 ]
#                 boxes = []
#                 for lbl, c, g, d in scenarios:
#                     val   = round(_c321(c, g, d), 2)
#                     delta = round(val - base, 2)
#                     is_up = delta >= 0
#                     bg    = "#0D2A1A" if is_up else "#2A0D0D"
#                     clr   = "#3FB950" if is_up else "#F85149"
#                     boxes.append((lbl, val, delta, bg, clr, is_up))

#                 # Render as 2×2 using columns
#                 r1c1, r1c2 = st.columns(2)
#                 r2c1, r2c2 = st.columns(2)
#                 for col, (lbl, val, delta, bg, clr, is_up) in zip(
#                     [r1c1,r1c2,r2c1,r2c2], boxes
#                 ):
#                     sign = "▲" if is_up else "▼"
#                     col.markdown(f"""
#                     <div style='background:{bg};border-radius:8px;padding:14px;
#                          text-align:center;margin-bottom:4px'>
#                       <div style='font-size:9px;color:{clr};letter-spacing:1px;
#                            text-transform:uppercase;font-weight:600'>{lbl}</div>
#                       <div style='font-size:10px;color:#8B949E;margin:2px 0'>
#                           Base: ${base:.2f}</div>
#                       <div style='font-size:20px;font-weight:700;
#                            font-family:monospace;color:{clr}'>${val:.2f}</div>
#                       <div style='font-size:13px;font-weight:600;color:{clr}'>
#                           {sign} {sign_str(delta)}/bbl</div>
#                     </div>""", unsafe_allow_html=True)

#                 # Product contribution bar
#                 st.markdown("<br>", unsafe_allow_html=True)
#                 st.markdown("<div class='sec-hdr'>Margin by Product Contribution</div>",
#                             unsafe_allow_html=True)
#                 ws_gas  = r.get("wholesale_gas",  0)
#                 ws_die  = r.get("wholesale_diesel",0)
#                 jet_p   = st.session_state.get("jet",    4.07)
#                 bnk_p   = st.session_state.get("bunker", 2.52)
#                 asp_p   = st.session_state.get("asphalt",2.16)
#                 crude_b2= r.get("crude_light",0)

#                 y_gas = yields.get("gasoline",0.465)
#                 y_die = yields.get("ulsd",    0.286)
#                 y_jet = yields.get("jet",     0.095)
#                 y_bnk = yields.get("bunker",  0.048)
#                 y_asp = yields.get("asphalt", 0.036)

#                 contrib = {
#                     "Gasoline": round(ws_gas*y_gas*42, 2),
#                     "Diesel":   round(ws_die*y_die*42, 2),
#                     "Jet Fuel": round(jet_p *y_jet*42, 2),
#                     "Bunker":   round(bnk_p *y_bnk*42, 2),
#                     "Asphalt":  round(asp_p *y_asp*42, 2),
#                 }
#                 colors_c = ["#4A90D9","#E8A020","#5A9E3A","#8B4FBF","#CC7722"]
#                 fig_c = go.Figure()
#                 for (prod, val_c), clr_c in zip(contrib.items(), colors_c):
#                     fig_c.add_trace(go.Bar(
#                         name=prod, x=["Product Revenue"],
#                         y=[val_c], marker_color=clr_c,
#                         text=[f"${val_c:.1f}"],
#                         textposition="inside",
#                         textfont=dict(size=10,color="#E6EDF3")))
#                 fig_c.add_hline(y=crude_b2,
#                     line_color="#F85149",line_width=2,line_dash="solid",
#                     annotation_text=f"Crude cost ${crude_b2:.2f}/bbl",
#                     annotation_font_color="#F85149",annotation_font_size=10)
#                 fig_c.update_layout(
#                     barmode="stack",
#                     paper_bgcolor="#0D1117",plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     yaxis=dict(title="$/bbl",gridcolor="#21262D"),
#                     xaxis=dict(gridcolor="#21262D"),
#                     legend=dict(bgcolor="#161B22",font=dict(size=10),
#                                 orientation="h",yanchor="bottom",y=1.02),
#                     margin=dict(l=0,r=0,t=30,b=0),height=220)
#                 st.plotly_chart(fig_c, use_container_width=True)

#     # ─── PANEL B: Forward View ────────────────────────────────────────────────
#     with st.expander("📈 Forward Crack Spread", expanded=True):
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#         n       = sel
#         lc_d    = st.session_state.get(f"lc_{n}",  loc_cfg.get("light_diff",0))
#         lg_d    = st.session_state.get(f"lg_{n}",  loc_cfg.get("gas_diff",0))
#         ld_d    = st.session_state.get(f"ld_{n}",  loc_cfg.get("diesel_diff",0))
#         fcd     = st.session_state.get("fcd",0)
#         fgd     = st.session_state.get("fgd",0)
#         fdd     = st.session_state.get("fdd",0)
#         jet_fwd = st.session_state.get("jet",   4.07)
#         bnk_fwd = st.session_state.get("bunker",2.52)
#         asp_fwd = st.session_state.get("asphalt",2.16)

#         # Inline forward price inputs
#         fi1,fi2,fi3,fi4 = st.columns(4)
#         jet_fwd  = fi1.number_input("Jet Fuel fwd ($/gal)",0.5,15.0,
#             float(jet_fwd), 0.01,"%.3f",key="fwd_jet_d")
#         bnk_fwd  = fi2.number_input("Bunker fwd ($/gal)",0.2,10.0,
#             float(bnk_fwd), 0.01,"%.3f",key="fwd_bnk_d")
#         asp_fwd  = fi3.number_input("Asphalt fwd ($/gal)",0.1,8.0,
#             float(asp_fwd), 0.01,"%.3f",key="fwd_asp_d")
#         cat_fwd  = fi4.number_input("Cat Feed fwd ($/gal)",0.5,10.0,
#             float(st.session_state.get("catfeed",1.90)),
#             0.01,"%.3f",key="fwd_cat_d")

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = fcd+lc_d,
#             gas_diff    = fgd+lg_d,
#             diesel_diff = fdd+ld_d,
#             jet_fwd=jet_fwd, bunker_fwd=bnk_fwd,
#             asphalt_fwd=asp_fwd, yields=yields)

#         if loc_fwd:
#             # Area chart: products stacked, crude as contrasting line
#             fwd_ok = [row for row in loc_fwd if row.get("crack_321")]
#             months  = [row["month"] for row in fwd_ok]
#             wti_fwd = [row["wti"]   for row in fwd_ok]
#             rbob_f  = [row.get("rbob",0) for row in fwd_ok]
#             ulsd_f  = [row.get("ulsd",0) for row in fwd_ok]
#             y_g = yields.get("gasoline",0.465)
#             y_d = yields.get("ulsd",    0.286)
#             y_j = yields.get("jet",     0.095)
#             y_b = yields.get("bunker",  0.048)
#             y_a = yields.get("asphalt", 0.036)

#             gas_rev  = [round((rb or 0)*y_g*42, 2) for rb in rbob_f]
#             die_rev  = [round((ul or 0)*y_d*42, 2) for ul in ulsd_f]
#             jet_rev  = [round(jet_fwd*y_j*42, 2)]  * len(months)
#             bnk_rev  = [round(bnk_fwd*y_b*42, 2)]  * len(months)
#             asp_rev  = [round(asp_fwd*y_a*42, 2)]   * len(months)

#             # Proper rgba color map — no string manipulation
#             AREA_COLORS = {
#                 "Gasoline": "rgba(74,144,217,0.75)",
#                 "Diesel":   "rgba(232,160,32,0.75)",
#                 "Jet Fuel": "rgba(90,158,58,0.75)",
#                 "Bunker":   "rgba(139,79,191,0.75)",
#                 "Asphalt":  "rgba(204,119,34,0.75)",
#             }

#             fig_fwd = go.Figure()
#             # Stacked area — products
#             for name, vals in [
#                 ("Gasoline", gas_rev),
#                 ("Diesel",   die_rev),
#                 ("Jet Fuel", jet_rev),
#                 ("Bunker",   bnk_rev),
#                 ("Asphalt",  asp_rev),
#             ]:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=vals, name=name,
#                     mode="none", fill="tonexty",
#                     fillcolor=AREA_COLORS[name],
#                     stackgroup="one",
#                     line=dict(width=0),
#                 ))
#             # Crude cost line — white/contrast
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=wti_fwd,
#                 name="Crude Cost (WTI+diff)",
#                 line=dict(color="#FFFFFF", width=2.5),
#                 mode="lines",
#                 hovertemplate="%{x}<br>Crude: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             # 3-2-1 crack line overlay
#             crack_vals = [row.get("crack_321") for row in fwd_ok]
#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=crack_vals,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#F85149", width=2, dash="dot"),
#                 yaxis="y2",
#                 hovertemplate="%{x}<br>3-2-1: $%{y:.2f}/bbl<extra></extra>",
#             ))
#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(title="Product Revenue ($/bbl)",
#                            gridcolor="#21262D"),
#                 yaxis2=dict(
#                     title=dict(text="Crack Spread ($/bbl)",
#                                font=dict(color="#F85149")),
#                     overlaying="y", side="right",
#                     showgrid=False,
#                     tickfont=dict(color="#F85149"),
#                 ),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10),
#                             orientation="h", yanchor="bottom", y=1.02),
#                 margin=dict(l=0,r=60,t=30,b=0), height=380,
#                 hovermode="x unified",
#             )
#             # Annotation explaining the gap
#             fig_fwd.add_annotation(
#                 x=months[len(months)//2] if months else 0,
#                 y=wti_fwd[len(wti_fwd)//2]+5 if wti_fwd else 50,
#                 text="↑ Gap above line = Margin",
#                 showarrow=False, font=dict(color="#FFFFFF", size=10),
#                 bgcolor="rgba(0,0,0,0.5)")
#             st.plotly_chart(fig_fwd, use_container_width=True)
#             st.caption(
#                 "Stacked areas = total product revenue by type. "
#                 "White line = crude cost (WTI + location diff). "
#                 "The gap above the white line is the implied refinery margin. "
#                 "Red dashed line (right axis) = 3-2-1 crack spread."
#             )

#             # P&L forward table
#             tp = r.get("throughput", 30000)
#             if tp and crack_vals:
#                 pnl_fwd = [round(v*tp*30/1e6,2) if v else None
#                            for v in crack_vals]
#                 fwd_df = pd.DataFrame({
#                     "Month":         months,
#                     "WTI ($/bbl)":   wti_fwd,
#                     "3-2-1 ($/bbl)": crack_vals,
#                     "P&L ($MM/mo)":  pnl_fwd,
#                 })
#                 with st.expander("Forward P&L Table"):
#                     st.dataframe(fwd_df, use_container_width=True,
#                                  hide_index=True)
#         else:
#             st.info("Forward curve data not available. Check CME connection.")

#     # ─── PANEL C: Full Calculator ─────────────────────────────────────────────
#     with st.expander("⚙️ Full Calculator — Change Any Input", expanded=False):
#         st.caption(
#             "All changes here update the snapshot and forward curve above. "
#             "Use this to answer any 'what if' question."
#         )
#         # Market prices
#         st.markdown("<div class='sec-hdr'>Market Prices</div>",
#                     unsafe_allow_html=True)
#         mp1,mp2,mp3,mp4 = st.columns(4)
#         if st.button("↺ Reset to Live", key="reset_live"):
#             live2 = get_spot(); spec2 = get_spec()
#             ul2   = live2.get("ulsd_gal",3.5) or 3.5
#             st.session_state.update({
#                 "wti":    live2.get("wti_bbl",80) or 80,
#                 "rbob":   live2.get("rbob_gal",2.5) or 2.5,
#                 "ulsd":   ul2,
#                 "jet":    spec2.get("jet_gal")    or ul2*1.05,
#                 "bunker": spec2.get("bunker_gal") or ul2*0.70,
#                 "asphalt":spec2.get("asphalt_gal")or ul2*0.60,
#             })
#             st.rerun()
#         st.session_state["wti"]    = mp1.number_input("WTI ($/bbl)",20.0,200.0,
#             float(st.session_state["wti"]),0.25,"%.2f",key=f"c_wti_{n}")
#         st.session_state["rbob"]   = mp2.number_input("RBOB ($/gal)",0.5,10.0,
#             float(st.session_state["rbob"]),0.01,"%.3f",key=f"c_rbob_{n}")
#         st.session_state["ulsd"]   = mp3.number_input("ULSD ($/gal)",0.5,10.0,
#             float(st.session_state["ulsd"]),0.01,"%.3f",key=f"c_ulsd_{n}")
#         st.session_state["dist"]   = mp4.number_input("Dist. Margin ($/gal)",0.0,1.0,
#             float(st.session_state["dist"]),0.01,"%.2f",key=f"c_dist_{n}")

#         sp1,sp2,sp3,sp4 = st.columns(4)
#         st.session_state["jet"]    = sp1.number_input("Jet Fuel ($/gal)",0.5,15.0,
#             float(st.session_state["jet"]),0.01,"%.3f",key=f"c_jet_{n}")
#         st.session_state["bunker"] = sp2.number_input("Bunker ($/gal)",0.2,10.0,
#             float(st.session_state["bunker"]),0.01,"%.3f",key=f"c_bunker_{n}")
#         st.session_state["catfeed"]= sp3.number_input("Cat Feed ($/gal)",0.2,10.0,
#             float(st.session_state.get("catfeed",1.9)),0.01,"%.3f",key=f"c_cat_{n}")
#         st.session_state["asphalt"]= sp4.number_input("Asphalt ($/gal)",0.1,8.0,
#             float(st.session_state["asphalt"]),0.01,"%.3f",key=f"c_asp_{n}")

#         # Location diffs
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

#         # Yield %
#         st.markdown("<div class='sec-hdr'>Yield Configuration (%)</div>",
#                     unsafe_allow_html=True)
#         YLBLS = {"gasoline":"Gasoline","ulsd":"Diesel","jet":"Jet",
#                  "bunker":"Bunker","asphalt":"Asphalt","refinery_use":"Ref. Use"}
#         ycols = st.columns(6)
#         total_y = 0.0
#         for i,(k,lbl) in enumerate(YLBLS.items()):
#             default = round(YIELD_DEFAULTS.get(k,0)*100,1)
#             val = ycols[i].number_input(f"{lbl} (%)",0.0,100.0,
#                 float(st.session_state.get(f"y_{k}",default)),
#                 0.5,"%.1f",key=f"c_y_{k}_{n}")
#             st.session_state[f"y_{k}"] = val
#             total_y += val
#         yc = "#3FB950" if total_y <= 100 else "#F85149"
#         st.markdown(f"<span style='color:{yc};font-size:12px'>"
#                     f"Total: {total_y:.1f}%</span>", unsafe_allow_html=True)

#         # Throughput
#         st.markdown("<div class='sec-hdr'>Throughput & P&L</div>",
#                     unsafe_allow_html=True)
#         tp_new = st.number_input("Throughput (bbl/day)",0,200000,
#             int(st.session_state.get(f"tp_{n}",30000)),1000,
#             key=f"c_tp_{n}")
#         st.session_state[f"tp_{n}"] = tp_new
#         if s321 and tp_new:
#             pnl_calc = round(s321 * tp_new * 30 / 1e6, 2)
#             annual   = round(pnl_calc * 12, 1)
#             st.markdown(
#                 f"<div style='background:#161B22;border:1px solid #30363D;"
#                 f"border-radius:8px;padding:14px;margin-top:8px'>"
#                 f"<span style='color:#8B949E;font-size:10px'>MONTHLY P&L</span><br>"
#                 f"<span style='color:#3FB950;font-size:24px;font-weight:700;"
#                 f"font-family:monospace'>${pnl_calc:.2f}MM</span>&nbsp;"
#                 f"<span style='color:#8B949E;font-size:12px'>/ month</span><br>"
#                 f"<span style='color:#8B949E;font-size:11px'>"
#                 f"${annual}MM annualized at ${s321:.2f}/bbl × "
#                 f"{tp_new:,} bbl/day</span></div>",
#                 unsafe_allow_html=True)

#         st.markdown("---")
#         # CSV download
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
#             "Cat Feed":           r.get("crude_catfeed"),
#             "3-2-1 ($/bbl)":      r.get("spread_321"),
#             "2-1-1 ($/bbl)":      r.get("spread_211"),
#             "5-3-2 ($/bbl)":      r.get("spread_532"),
#             "Full Yield ($/bbl)": r.get("spread_full"),
#             "Throughput (bbl/d)": tp_new,
#             "P&L ($MM/mo)":       fmt_pnl(s321, tp_new),
#             "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
#         }
#         st.download_button(
#             f"⬇️ Download {short} Detail CSV",
#             data=pd.DataFrame([dl_row]).to_csv(index=False),
#             file_name=f"rogue_{short.replace(' ','_').lower()}.csv",
#             mime="text/csv", use_container_width=True)

#     # Forward diffs (sidebar-style, at bottom of detail page)
#     with st.expander("Forward Curve Diffs", expanded=False):
#         fc1,fc2,fc3 = st.columns(3)
#         st.session_state["fcd"] = fc1.number_input("Crude diff fwd ($/bbl)",
#             -15.0,15.0,float(st.session_state.get("fcd",0)),0.25,"%.2f",
#             key=f"fcd_{n}")
#         st.session_state["fgd"] = fc2.number_input("Gas diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fgd",0)),0.01,"%.3f",
#             key=f"fgd_{n}")
#         st.session_state["fdd"] = fc3.number_input("Diesel diff fwd ($/gal)",
#             -1.0,1.0,float(st.session_state.get("fdd",0)),0.01,"%.3f",
#             key=f"fdd_{n}")


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
#         "Scenario analysis · Throughput P&L</p>",
#         unsafe_allow_html=True)

#     # Sidebar: just refresh
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
#             "**Portfolio view:** overview of all locations.\n\n"
#             "**Location detail:** click any location card to drill in — "
#             "current margin, forward curve, and full calculator.\n\n"
#             "All inputs in the calculator update the dashboard instantly."
#         )

#     with st.spinner("Loading market data..."):
#         strip = get_cme()
#         lp    = get_lp()

#     margins, spot, yields = build_margins(lp)
#     render_ticker(spot, margins)

#     view = st.session_state.get("view", "portfolio")

#     if view == "portfolio":
#         show_command(margins)
#     else:
#         show_detail(margins, strip, yields, lp)

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;"
#         f"margin-top:8px'>AAA Fuel Gauge · EIA API · "
#         f"CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True)


# if __name__ == "__main__":
#     main()

# # app.py — Rogue Refinery Economics — Trading Dashboard v2
# import streamlit as st
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
# from engine.stress_test import run_stress_test, SCENARIOS
# from engine.crack import crack_321 as _c321

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── CSS ────────────────────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# .stApp{background:#0D1117}
# .ticker-bar{display:flex;gap:28px;background:#161B22;border:1px solid #30363D;
#   border-radius:8px;padding:12px 20px;margin-bottom:14px;align-items:center;
#   flex-wrap:wrap}
# .ticker-item{display:flex;flex-direction:column;align-items:center}
# .ticker-label{font-size:10px;color:#8B949E;letter-spacing:1px;text-transform:uppercase}
# .ticker-value{font-size:20px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .ticker-divider{width:1px;height:36px;background:#30363D}
# .sec-hdr{font-size:10px;font-weight:600;color:#8B949E;letter-spacing:2px;
#   text-transform:uppercase;margin:8px 0 4px 0}
# .metric-card{background:#161B22;border:1px solid #30363D;border-radius:8px;
#   padding:14px;text-align:center}
# .mc-label{font-size:10px;color:#8B949E;text-transform:uppercase;letter-spacing:1px}
# .mc-value{font-size:22px;font-weight:700;color:#E6EDF3;font-family:monospace}
# .mc-sub{font-size:11px;color:#8B949E;margin-top:2px}
# .input-panel{background:#161B22;border:1px solid #30363D;border-radius:8px;padding:16px;margin-bottom:12px}
# .input-panel-title{font-size:11px;font-weight:600;color:#E8A020;letter-spacing:1px;
#   text-transform:uppercase;margin-bottom:10px}
# #MainMenu{visibility:hidden}footer{visibility:hidden}header{visibility:hidden}
# .stTabs [data-baseweb="tab-list"]{background:#161B22;border-radius:8px;padding:4px}
# .stTabs [data-baseweb="tab"]{color:#8B949E}
# .stTabs [aria-selected="true"]{background:#21262D;color:#E6EDF3;border-radius:6px}
# [data-testid="stSidebar"]{background:#161B22}
# </style>
# """, unsafe_allow_html=True)


# # ── Helpers ────────────────────────────────────────────────────────────────────
# def spread_color(v):
#     if v is None: return "#8B949E"
#     return "#3FB950" if v >= 25 else ("#E8A020" if v >= 12 else "#F85149")

# def spread_label(v):
#     if v is None: return "—"
#     return "STRONG" if v >= 25 else ("MODERATE" if v >= 12 else "THIN")

# def fmt_bbl(v):  return f"${v:.2f}" if v is not None else "—"
# def fmt_gal(v):  return f"${v:.3f}" if v is not None else "—"
# def fmt_pnl(spread_bbl, throughput_bbl_day):
#     """Monthly P&L in $MM given spread $/bbl and throughput bbl/day."""
#     if spread_bbl is None or not throughput_bbl_day:
#         return None
#     return round(spread_bbl * throughput_bbl_day * 30 / 1_000_000, 2)


# # ── Password gate ──────────────────────────────────────────────────────────────
# def check_password():
#     try:
#         correct = st.secrets.get("APP_PASSWORD")
#     except Exception:
#         return
#     if not correct:
#         return
#     if not st.session_state.get("authenticated"):
#         st.title("🏭 Rogue Refinery Economics")
#         pwd = st.text_input("Password", type="password")
#         if st.button("Login"):
#             if pwd == correct:
#                 st.session_state["authenticated"] = True
#                 st.rerun()
#             else:
#                 st.error("Incorrect password")
#         st.stop()


# # ── Cached fetchers ────────────────────────────────────────────────────────────
# @st.cache_data(ttl=3600)
# def get_cme_strip():
#     return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot_prices_live():
#     return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_location_prices():
#     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_specialty_live():
#     return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Session state init ─────────────────────────────────────────────────────────
# def init_state():
#     """Initialise session state with live prices + config defaults."""
#     if "inputs_initialised" not in st.session_state:
#         live_spot = get_spot_prices_live()
#         live_spec = get_specialty_live()
#         ulsd_live = live_spot.get("ulsd_gal", 3.50)

#         st.session_state["wti_override"]    = live_spot.get("wti_bbl",  80.0) or 80.0
#         st.session_state["rbob_override"]   = live_spot.get("rbob_gal",  2.50) or 2.50
#         st.session_state["ulsd_override"]   = live_spot.get("ulsd_gal",  3.50) or 3.50
#         st.session_state["jet_override"]    = live_spec.get("jet_gal")  or ulsd_live * 1.05
#         st.session_state["bunker_override"] = live_spec.get("bunker_gal") or ulsd_live * 0.70
#         st.session_state["catfeed_override"]= (live_spot.get("wti_bbl", 80.0) or 80.0) * 0.95 / 42
#         st.session_state["asphalt_override"]= live_spec.get("asphalt_gal") or ulsd_live * 0.60

#         st.session_state["dist_margin"]     = 0.35
#         st.session_state["fwd_crude_diff"]  = 0.0
#         st.session_state["fwd_gas_diff"]    = 0.0
#         st.session_state["fwd_diesel_diff"] = 0.0

#         # Yield percentages
#         for k, v in YIELD_DEFAULTS.items():
#             st.session_state[f"yield_{k}"] = round(v * 100, 1)

#         # Per-location diffs & throughput
#         for loc in LOCATIONS:
#             n = loc["display"]
#             st.session_state[f"ldiff_crude_{n}"]   = loc.get("light_diff",   0.0)
#             st.session_state[f"ldiff_heavy_{n}"]   = loc.get("heavy_diff",   0.0)
#             st.session_state[f"ldiff_catfeed_{n}"] = loc.get("catfeed_diff", 0.0)
#             st.session_state[f"ldiff_gas_{n}"]     = loc.get("gas_diff",     0.0)
#             st.session_state[f"ldiff_diesel_{n}"]  = loc.get("diesel_diff",  0.0)
#             st.session_state[f"ldiff_jet_{n}"]     = 0.0
#             st.session_state[f"throughput_{n}"]    = loc.get("throughput", 30000)

#         st.session_state["inputs_initialised"] = True


# # ── Sidebar (minimal) ──────────────────────────────────────────────────────────
# def render_sidebar():
#     st.sidebar.markdown(
#         "<div style='text-align:center;padding:10px 0'>"
#         "<span style='font-size:26px'>🏭</span><br>"
#         "<span style='color:#E8A020;font-weight:700;font-size:13px;letter-spacing:2px'>"
#         "ROGUE REFINERY</span><br>"
#         "<span style='color:#8B949E;font-size:10px;letter-spacing:1px'>ECONOMICS DASHBOARD</span>"
#         "</div>",
#         unsafe_allow_html=True,
#     )
#     st.sidebar.markdown("---")

#     if st.sidebar.button("🔄  Refresh Market Data", use_container_width=True):
#         get_cme_strip.clear()
#         get_spot_prices_live.clear()
#         get_location_prices.clear()
#         get_specialty_live.clear()
#         for k in list(st.session_state.keys()):
#             del st.session_state[k]
#         st.rerun()

#     st.sidebar.markdown("---")
#     st.sidebar.markdown(
#         "<div class='sec-hdr'>Forward Curve Diffs</div>",
#         unsafe_allow_html=True,
#     )
#     st.session_state["fwd_crude_diff"]  = st.sidebar.number_input(
#         "Crude diff ($/bbl)", min_value=-15.0, max_value=15.0,
#         value=st.session_state.get("fwd_crude_diff", 0.0),
#         step=0.25, format="%.2f", key="sb_fcd")
#     st.session_state["fwd_gas_diff"]    = st.sidebar.number_input(
#         "Gasoline diff ($/gal)", min_value=-1.0, max_value=1.0,
#         value=st.session_state.get("fwd_gas_diff", 0.0),
#         step=0.01, format="%.3f", key="sb_fgd")
#     st.session_state["fwd_diesel_diff"] = st.sidebar.number_input(
#         "Diesel diff ($/gal)", min_value=-1.0, max_value=1.0,
#         value=st.session_state.get("fwd_diesel_diff", 0.0),
#         step=0.01, format="%.3f", key="sb_fdd")

#     st.sidebar.markdown("---")
#     st.sidebar.caption(
#         "All price overrides, yield config, and per-location "
#         "differentials live in the **⚙️ Inputs** tab."
#     )


# # ── Build margins from session state ──────────────────────────────────────────
# def build_margins(loc_prices):
#     """Assemble margins using all session-state overrides."""
#     spot = {
#         "wti_bbl":  st.session_state["wti_override"],
#         "rbob_gal": st.session_state["rbob_override"],
#         "ulsd_gal": st.session_state["ulsd_override"],
#     }
#     specialty = {
#         "jet_gal":     st.session_state["jet_override"],
#         "bunker_gal":  st.session_state["bunker_override"],
#         "asphalt_gal": st.session_state["asphalt_override"],
#     }
#     yields = {
#         k: round(st.session_state.get(f"yield_{k}", v * 100) / 100, 6)
#         for k, v in YIELD_DEFAULTS.items()
#     }
#     dist_margin = st.session_state["dist_margin"]

#     # Build per-location overrides
#     loc_overrides = []
#     for loc in LOCATIONS:
#         n   = loc["display"]
#         ovr = dict(loc)
#         ovr["light_diff"]   = st.session_state.get(f"ldiff_crude_{n}",   loc.get("light_diff",   0.0))
#         ovr["heavy_diff"]   = st.session_state.get(f"ldiff_heavy_{n}",   loc.get("heavy_diff",   0.0))
#         ovr["catfeed_diff"] = st.session_state.get(f"ldiff_catfeed_{n}", loc.get("catfeed_diff", 0.0))
#         ovr["gas_diff"]     = st.session_state.get(f"ldiff_gas_{n}",     loc.get("gas_diff",     0.0))
#         ovr["diesel_diff"]  = st.session_state.get(f"ldiff_diesel_{n}",  loc.get("diesel_diff",  0.0))
#         ovr["throughput"]   = st.session_state.get(f"throughput_{n}",    30000)
#         loc_overrides.append(ovr)

#     margins = compute_location_margins(
#         locations        = loc_overrides,
#         spot_prices      = spot,
#         location_prices  = loc_prices,
#         specialty        = specialty,
#         yields           = yields,
#         dist_margin_gal  = dist_margin,
#     )
#     # Attach throughput to each row
#     tp_map = {l["display"]: st.session_state.get(f"throughput_{l['display']}", 30000)
#               for l in LOCATIONS}
#     for r in margins:
#         r["throughput"] = tp_map.get(r["display"], 30000)
#         r["pnl_monthly"] = fmt_pnl(r.get("spread_321"), r["throughput"])
#     return margins, spot, specialty, yields, dist_margin


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
# def render_ticker(spot, margins):
#     wti  = spot.get("wti_bbl")
#     rbob = spot.get("rbob_gal")
#     ulsd = spot.get("ulsd_gal")
#     live = get_spot_prices_live()
#     wti_live = live.get("wti_bbl")
#     wti_delta = ""
#     if wti and wti_live:
#         diff = round(wti - wti_live, 2)
#         wti_delta = (f"<span style='color:#3FB950'>▲ ${diff:.2f}</span>"
#                      if diff >= 0 else
#                      f"<span style='color:#F85149'>▼ ${abs(diff):.2f}</span>")

#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     port_avg = round(sum(spreads)/len(spreads), 2) if spreads else None
#     total_pnl = sum(r["pnl_monthly"] for r in margins if r.get("pnl_monthly"))

#     pc = spread_color(port_avg)
#     st.markdown(f"""
#     <div class="ticker-bar">
#       <div class="ticker-item">
#         <span class="ticker-label">WTI Crude</span>
#         <span class="ticker-value">{fmt_bbl(wti)}</span>
#         <span class="ticker-label">{wti_delta}&nbsp;vs live</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">RBOB Gasoline</span>
#         <span class="ticker-value">{fmt_gal(rbob)}</span>
#         <span class="ticker-label">per gallon</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">ULSD Diesel</span>
#         <span class="ticker-value">{fmt_gal(ulsd)}</span>
#         <span class="ticker-label">per gallon</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">RBOB $/bbl equiv</span>
#         <span class="ticker-value">{fmt_bbl(round(rbob*42,2) if rbob else None)}</span>
#         <span class="ticker-label">×42</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Portfolio Avg 3-2-1</span>
#         <span class="ticker-value" style="color:{pc}">
#           {"$"+str(port_avg)+"/bbl" if port_avg else "—"}
#         </span>
#         <span class="ticker-label" style="color:{pc}">{spread_label(port_avg)}</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Portfolio P&L / Mo</span>
#         <span class="ticker-value" style="color:#3FB950">
#           {"$"+str(round(total_pnl,1))+"MM" if total_pnl else "—"}
#         </span>
#         <span class="ticker-label">at current throughput</span>
#       </div><div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Active Locations</span>
#         <span class="ticker-value">{len([r for r in margins if r.get("spread_321")])}</span>
#         <span class="ticker-label">of {len(LOCATIONS)}</span>
#       </div>
#     </div>
#     """, unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # TAB 1 — Portfolio Overview
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

# def show_portfolio(margins, strip, yields):
#     # Map
#     st.markdown("<div class='sec-hdr'>Refinery Location Map — 3-2-1 Crack Spread ($/bbl)</div>",
#                 unsafe_allow_html=True)
#     map_rows = []
#     for r in margins:
#         coords = LOC_COORDS.get(r["display"], (39.5,-98.35))
#         s = r.get("spread_321")
#         pnl = r.get("pnl_monthly")
#         map_rows.append({
#             "location": r["display"],
#             "lat": coords[0], "lon": coords[1],
#             "spread": s, "color": spread_color(s),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1 Crack: {'$'+str(s)+'/bbl' if s else '—'}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"Monthly P&L: {'$'+str(pnl)+'MM' if pnl else '—'}<br>"
#                 f"Throughput: {r.get('throughput',30000):,} bbl/day<br>"
#                 f"Retail Gas: {'$'+str(r.get('retail_gas'))+'/gal' if r.get('retail_gas') else '—'}<br>"
#                 f"Wholesale: {'$'+str(r.get('wholesale_gas'))+'/gal' if r.get('wholesale_gas') else '—'}<br>"
#                 f"Light Crude: {'$'+str(r.get('crude_light'))+'/bbl' if r.get('crude_light') else '—'}<br>"
#                 f"Status: {spread_label(s)}"
#             ),
#         })
#     df_map = pd.DataFrame(map_rows)

#     fig_map = go.Figure()
#     fig_map.add_trace(go.Scattergeo(
#         lat=df_map["lat"], lon=df_map["lon"],
#         mode="markers+text",
#         marker=dict(size=18, color=df_map["color"].tolist(),
#                     line=dict(width=2, color="#0D1117"), opacity=0.92),
#         text=df_map["location"].apply(
#             lambda x: x.split("—")[-1].split(",")[0].strip()),
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_map["hover"], hoverinfo="text",
#     ))
#     for _, row in df_map.iterrows():
#         if row["spread"]:
#             fig_map.add_trace(go.Scattergeo(
#                 lat=[row["lat"]-1.8], lon=[row["lon"]],
#                 mode="text",
#                 text=[f"${row['spread']:.0f}"],
#                 textfont=dict(size=9, color=row["color"]),
#                 hoverinfo="skip", showlegend=False,
#             ))
#     fig_map.update_layout(
#         geo=dict(scope="world", showland=True, landcolor="#1C2128",
#                  showocean=True, oceancolor="#0D1117",
#                  showlakes=True, lakecolor="#0D1117",
#                  showcountries=True, countrycolor="#30363D",
#                  showcoastlines=True, coastlinecolor="#30363D",
#                  showframe=False, bgcolor="#0D1117",
#                  center=dict(lat=42, lon=-98), projection_scale=2.8,
#                  lonaxis_range=[-170,-50], lataxis_range=[15,72]),
#         paper_bgcolor="#0D1117", margin=dict(l=0,r=0,t=0,b=0),
#         height=400, showlegend=False,
#     )
#     for lbl, clr, ya in [("● STRONG ≥$25","#3FB950",0.12),
#                           ("● MODERATE $12–25","#E8A020",0.08),
#                           ("● THIN <$12","#F85149",0.04)]:
#         fig_map.add_annotation(x=0.01,y=ya,xref="paper",yref="paper",
#             text=lbl,showarrow=False,font=dict(color=clr,size=10),
#             bgcolor="#0D1117",align="left")
#     st.plotly_chart(fig_map, use_container_width=True)

#     # Ranking + Forward
#     lc, rc = st.columns([1,1], gap="large")

#     with lc:
#         st.markdown("<div class='sec-hdr'>Margin Ranking — 3-2-1 ($/bbl)</div>",
#                     unsafe_allow_html=True)
#         ranked = sorted([r for r in margins if r.get("spread_321")],
#                         key=lambda x: x["spread_321"])
#         if ranked:
#             names  = [r["display"].split("—")[-1].split(",")[0].strip()
#                       for r in ranked]
#             vals   = [r["spread_321"] for r in ranked]
#             pnls   = [r.get("pnl_monthly") for r in ranked]
#             colors = [spread_color(v) for v in vals]
#             hover  = [f"${v:.2f}/bbl<br>${p:.1f}MM/mo" if p else f"${v:.2f}/bbl"
#                       for v, p in zip(vals, pnls)]

#             fig_r = go.Figure(go.Bar(
#                 x=vals, y=names, orientation="h",
#                 marker_color=colors, marker_line_width=0,
#                 text=[f"${v:.1f}" for v in vals],
#                 textposition="outside",
#                 textfont=dict(color="#E6EDF3", size=11),
#                 hovertext=hover, hoverinfo="text",
#             ))
#             for thresh, clr, lbl in [(25,"#3FB950","Strong"),
#                                       (12,"#E8A020","Moderate")]:
#                 fig_r.add_vline(x=thresh, line_dash="dot",
#                                 line_color=clr, opacity=0.5,
#                                 annotation_text=lbl,
#                                 annotation_font_color=clr,
#                                 annotation_font_size=9)
#             fig_r.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(title="$/bbl", gridcolor="#21262D",
#                            zeroline=True, zerolinecolor="#30363D"),
#                 yaxis=dict(gridcolor="#21262D"),
#                 margin=dict(l=0,r=60,t=8,b=0), height=360,
#                 showlegend=False,
#             )
#             st.plotly_chart(fig_r, use_container_width=True)

#     with rc:
#         st.markdown("<div class='sec-hdr'>Portfolio Forward Curve — CME Settle</div>",
#                     unsafe_allow_html=True)
#         fcd = st.session_state.get("fwd_crude_diff", 0.0)
#         fgd = st.session_state.get("fwd_gas_diff",   0.0)
#         fdd = st.session_state.get("fwd_diesel_diff",0.0)
#         jet    = st.session_state.get("jet_override",    4.07)
#         bunker = st.session_state.get("bunker_override", 2.52)
#         asph   = st.session_state.get("asphalt_override",2.16)

#         fwd = compute_forward_crack(strip=strip, crude_diff=fcd,
#               gas_diff=fgd, diesel_diff=fdd, jet_fwd=jet,
#               bunker_fwd=bunker, asphalt_fwd=asph, yields=yields)
#         fwd_stress = compute_forward_crack(
#               strip=strip,
#               crude_diff=fcd + (strip.get("wti",[{}])[0].get("price",80)*0.20
#                                 if strip.get("wti") else 0),
#               gas_diff=fgd-0.20, diesel_diff=fdd-0.20,
#               jet_fwd=jet*0.80, bunker_fwd=bunker*0.80, asphalt_fwd=asph*0.80,
#               yields=yields)

#         if fwd:
#             mo   = [r["month"]      for r in fwd if r.get("crack_321")]
#             f321 = [r["crack_321"]  for r in fwd if r.get("crack_321")]
#             ffull= [r["crack_full"] for r in fwd if r.get("crack_full")]
#             s321 = [r.get("crack_321") for r in fwd_stress if r.get("crack_321")]

#             fig_f = go.Figure()
#             if s321 and len(s321)==len(f321):
#                 fig_f.add_trace(go.Scatter(
#                     x=mo+mo[::-1], y=f321+s321[::-1],
#                     fill="toself", fillcolor="rgba(248,81,73,0.10)",
#                     line=dict(width=0), name="Stress Band −20%",
#                     hoverinfo="skip"))
#             fig_f.add_trace(go.Scatter(x=mo, y=f321,
#                 name="3-2-1 ($/bbl)", line=dict(color="#E8A020",width=2.5),
#                 mode="lines+markers", marker=dict(size=5)))
#             if ffull:
#                 fig_f.add_trace(go.Scatter(x=mo, y=ffull,
#                     name="Full Yield", line=dict(color="#5A9E3A",width=2,dash="dot")))
#             if s321:
#                 fig_f.add_trace(go.Scatter(
#                     x=[r["month"] for r in fwd_stress if r.get("crack_321")],
#                     y=s321, name="Stress −20%",
#                     line=dict(color="#F85149",width=1.5,dash="dash")))
#             fig_f.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(gridcolor="#21262D", title="$/bbl"),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10)),
#                 margin=dict(l=0,r=0,t=8,b=0), height=360)
#             st.plotly_chart(fig_f, use_container_width=True)

#     # Audit downloads
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Audit Downloads</div>",
#                 unsafe_allow_html=True)
#     d1,d2,d3 = st.columns(3)
#     wf_rows = []
#     for r in margins:
#         wf_rows.append({
#             "Location":             r["display"],
#             "Source":               r.get("source"),
#             "Throughput (bbl/day)": r.get("throughput"),
#             "Retail Gas ($/gal)":   r.get("retail_gas"),
#             "Federal Tax":          r.get("federal_tax_gas"),
#             "State Tax":            r.get("state_tax_gas"),
#             "Total Tax":            r.get("total_tax_gas"),
#             "Pre-tax Gas":          r.get("pretax_gas"),
#             "Distribution Margin":  r.get("dist_margin"),
#             "Wholesale Gas":        r.get("wholesale_gas"),
#             "Retail Diesel":        r.get("retail_diesel"),
#             "Wholesale Diesel":     r.get("wholesale_diesel"),
#             "Light Crude ($/bbl)":  r.get("crude_light"),
#             "Heavy Crude":          r.get("crude_heavy"),
#             "Cat Feed":             r.get("crude_catfeed"),
#             "3-2-1 ($/bbl)":        r.get("spread_321"),
#             "2-1-1 ($/bbl)":        r.get("spread_211"),
#             "5-3-2 ($/bbl)":        r.get("spread_532"),
#             "Full Yield ($/bbl)":   r.get("spread_full"),
#             "Monthly P&L ($MM)":    r.get("pnl_monthly"),
#             "As Of":                datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })
#     with d1:
#         st.download_button("⬇️ Price Waterfall",
#             data=pd.DataFrame(wf_rows).to_csv(index=False),
#             file_name="rogue_waterfall.csv", mime="text/csv",
#             use_container_width=True)
#     if fwd:
#         with d2:
#             st.download_button("⬇️ Forward Curve",
#                 data=pd.DataFrame(fwd).to_csv(index=False),
#                 file_name="rogue_forward.csv", mime="text/csv",
#                 use_container_width=True)
#     sr = run_stress_test(margins)
#     if sr["base"]:
#         locs   = sr["locations"]
#         st_rows= [{"Scenario": sc,
#                    **{l: round(sr["grid"][sc].get(l),2)
#                       if sr["grid"][sc].get(l) else None for l in locs}}
#                   for sc in sr["scenarios"]]
#         with d3:
#             st.download_button("⬇️ Stress Test",
#                 data=pd.DataFrame(st_rows).to_csv(index=False),
#                 file_name="rogue_stress.csv", mime="text/csv",
#                 use_container_width=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # TAB 2 — Location Detail
# # ══════════════════════════════════════════════════════════════════════════════
# def show_location_detail(margins, strip, yields):
#     loc_names = [r["display"] for r in margins if r.get("spread_321")]
#     if not loc_names:
#         st.warning("No margin data available.")
#         return

#     selected = st.selectbox("Select Refinery Location", options=loc_names,
#                             index=0, key="loc_sel")
#     r = next((m for m in margins if m["display"] == selected), None)
#     if not r:
#         return

#     tp    = r.get("throughput", 30000)
#     pnl   = r.get("pnl_monthly")
#     s321  = r.get("spread_321")
#     sfull = r.get("spread_full")

#     # KPI row
#     k1,k2,k3,k4,k5,k6 = st.columns(6)
#     for col, lbl, val, sub in [
#         (k1, "3-2-1 Crack",   ("$"+str(s321)+"/bbl" if s321 else "—"),
#          spread_label(s321)),
#         (k2, "Full Yield",    ("$"+str(sfull)+"/bbl" if sfull else "—"),
#          spread_label(sfull)),
#         (k3, "Monthly P&L",   ("$"+str(pnl)+"MM" if pnl else "—"),
#          f"{tp:,} bbl/day"),
#         (k4, "Light Crude",   fmt_bbl(r.get("crude_light")), "WTI + diff"),
#         (k5, "Wholesale Gas", fmt_gal(r.get("wholesale_gas")), "after taxes+dist"),
#         (k6, "Price Source",
#          r.get("source","—").replace("AAA Metro — ","").replace("AAA Metro","AAA"),
#          "AAA daily"),
#     ]:
#         clr = spread_color(s321) if "Crack" in lbl or "Yield" in lbl or "P&L" in lbl else "#E6EDF3"
#         col.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>{lbl}</div>
#             <div class='mc-value' style='color:{clr};font-size:18px'>{val}</div>
#             <div class='mc-sub'>{sub}</div>
#         </div>""", unsafe_allow_html=True)

#     st.markdown("<br>", unsafe_allow_html=True)
#     wf_col, fwd_col = st.columns([1,1], gap="large")

#     # Waterfall
#     with wf_col:
#         st.markdown("<div class='sec-hdr'>Price Waterfall — Gas ($/gal)</div>",
#                     unsafe_allow_html=True)
#         if r.get("retail_gas"):
#             retail    = r["retail_gas"]
#             fed       = r.get("federal_tax_gas", 0.184)
#             state_t   = r.get("state_tax_gas", 0.0)
#             dist      = r.get("dist_margin", 0.35)
#             wholesale = r.get("wholesale_gas", 0.0)
#             crude_gal = (r.get("crude_light",0)) / 42
#             margin_gal= (s321 or 0) / 42

#             fig_wf = go.Figure(go.Waterfall(
#                 orientation="v",
#                 measure=["absolute","relative","relative","relative",
#                          "total","relative","total"],
#                 x=["Retail","− Fed Tax","− State Tax","− Dist",
#                    "= Wholesale","− Crude/gal","= Margin/gal"],
#                 y=[retail,-fed,-state_t,-dist,0,-crude_gal,0],
#                 text=[f"${retail:.3f}",f"-${fed:.3f}",f"-${state_t:.3f}",
#                       f"-${dist:.3f}",f"${wholesale:.3f}",
#                       f"-${crude_gal:.3f}",
#                       f"${margin_gal:.3f}" if s321 else "—"],
#                 textposition="outside",
#                 textfont=dict(size=10,color="#E6EDF3"),
#                 connector=dict(line=dict(color="#30363D",width=1)),
#                 decreasing=dict(marker_color="#F85149"),
#                 increasing=dict(marker_color="#3FB950"),
#                 totals=dict(marker_color="#E8A020"),
#             ))
#             fig_wf.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 yaxis=dict(title="$/gal", gridcolor="#21262D"),
#                 xaxis=dict(gridcolor="#21262D", tickangle=-30),
#                 margin=dict(l=0,r=0,t=8,b=0), height=320,
#                 showlegend=False)
#             st.plotly_chart(fig_wf, use_container_width=True)

#     # Per-location forward curve
#     with fwd_col:
#         st.markdown("<div class='sec-hdr'>Forward Crack — This Location</div>",
#                     unsafe_allow_html=True)
#         loc_cfg = next((l for l in LOCATIONS if l["display"]==selected), {})
#         n = selected
#         lc_diff = st.session_state.get(f"ldiff_crude_{n}", loc_cfg.get("light_diff",0))
#         lg_diff = st.session_state.get(f"ldiff_gas_{n}",   loc_cfg.get("gas_diff",0))
#         ld_diff = st.session_state.get(f"ldiff_diesel_{n}",loc_cfg.get("diesel_diff",0))

#         loc_fwd = compute_forward_crack(
#             strip=strip,
#             crude_diff  = st.session_state.get("fwd_crude_diff",0)  + lc_diff,
#             gas_diff    = st.session_state.get("fwd_gas_diff",0)     + lg_diff,
#             diesel_diff = st.session_state.get("fwd_diesel_diff",0)  + ld_diff,
#             jet_fwd     = st.session_state.get("jet_override",4.07),
#             bunker_fwd  = st.session_state.get("bunker_override",2.52),
#             asphalt_fwd = st.session_state.get("asphalt_override",2.16),
#             yields      = yields,
#         )
#         if loc_fwd:
#             mo   = [r2["month"]      for r2 in loc_fwd if r2.get("crack_321")]
#             f321 = [r2["crack_321"]  for r2 in loc_fwd if r2.get("crack_321")]
#             ffull= [r2["crack_full"] for r2 in loc_fwd if r2.get("crack_full")]
#             fig_lf = go.Figure()
#             fig_lf.add_trace(go.Scatter(x=mo, y=f321, name="3-2-1",
#                 line=dict(color="#E8A020",width=2.5), mode="lines+markers",
#                 marker=dict(size=6), fill="tozeroy",
#                 fillcolor="rgba(232,160,32,0.08)"))
#             if ffull:
#                 fig_lf.add_trace(go.Scatter(x=mo, y=ffull, name="Full Yield",
#                     line=dict(color="#5A9E3A",width=2,dash="dot")))
#             # P&L axis annotation
#             if tp and f321:
#                 pnl_line = [round(v*tp*30/1e6,2) for v in f321]
#                 fig_lf.add_trace(go.Scatter(x=mo, y=pnl_line,
#                     name="P&L $MM/mo", yaxis="y2",
#                     line=dict(color="#8B949E",width=1.5,dash="dot"),
#                     opacity=0.7))
#                 fig_lf.update_layout(
#                     yaxis2=dict(title="$MM/month", overlaying="y",
#                                 side="right", gridcolor="#21262D",
#                                 showgrid=False))
#             fig_lf.add_hline(y=15, line_dash="dot", line_color="#8B949E",
#                              opacity=0.4, annotation_text="~Breakeven $15",
#                              annotation_font_color="#8B949E",
#                              annotation_font_size=9)
#             fig_lf.update_layout(
#                 paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(gridcolor="#21262D", title="$/bbl"),
#                 legend=dict(bgcolor="#161B22", font=dict(size=10)),
#                 margin=dict(l=0,r=50,t=8,b=0), height=320)
#             st.plotly_chart(fig_lf, use_container_width=True)

#     # All 4 spreads
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>All Spread Formulas</div>",
#                 unsafe_allow_html=True)
#     s1,s2,s3,s4,s5 = st.columns(5)
#     for col, key, lbl in [
#         (s1,"spread_321","3-2-1"),
#         (s2,"spread_211","2-1-1"),
#         (s3,"spread_532","5-3-2"),
#         (s4,"spread_full","Full Yield"),
#     ]:
#         v = r.get(key)
#         col.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>{lbl}</div>
#             <div class='mc-value' style='color:{spread_color(v)};font-size:20px'>
#                 {"$"+str(v)+"/bbl" if v else "—"}
#             </div>
#             <div class='mc-sub'>{spread_label(v)}</div>
#         </div>""", unsafe_allow_html=True)
#     pnl_321 = fmt_pnl(s321, tp)
#     s5.markdown(f"""<div class='metric-card'>
#         <div class='mc-label'>Monthly P&L</div>
#         <div class='mc-value' style='color:#3FB950;font-size:20px'>
#             {"$"+str(pnl_321)+"MM" if pnl_321 else "—"}
#         </div>
#         <div class='mc-sub'>{f"{tp:,} bbl/day"}</div>
#     </div>""", unsafe_allow_html=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # TAB 3 — Scenario Builder
# # ══════════════════════════════════════════════════════════════════════════════
# def show_scenario_builder(margins, strip, yields):
#     view_mode = st.radio(
#         "Scenario view",
#         ["All Locations — Portfolio Stress Grid",
#          "Single Location — Deep What-If"],
#         horizontal=True, label_visibility="collapsed",
#     )

#     if "Portfolio" in view_mode:
#         # 2D heatmap: crude % × product %
#         st.markdown("<div class='sec-hdr'>2D Crack Spread Heatmap — Crude vs Product Price</div>",
#                     unsafe_allow_html=True)
#         st.caption("Each cell = portfolio-average 3-2-1 spread ($/bbl) under that scenario combination")

#         crude_steps   = [-25,-15,-10,-5,0,5,10,15,25]
#         product_steps = [-25,-15,-10,-5,0,5,10,15,25]
#         base_margins  = {r["display"]: r for r in margins if r.get("spread_321")}

#         heat_z  = []
#         hover_z = []
#         for pp in product_steps:
#             row_z   = []
#             row_h   = []
#             for cp in crude_steps:
#                 cm = 1 + cp/100
#                 pm = 1 + pp/100
#                 vals = []
#                 for r in margins:
#                     if r.get("spread_321") is None: continue
#                     v = _c321(
#                         r["crude_light"]      * cm,
#                         r["wholesale_gas"]    * pm,
#                         r["wholesale_diesel"] * pm,
#                     )
#                     vals.append(v)
#                 avg = round(sum(vals)/len(vals), 2) if vals else None
#                 row_z.append(avg)
#                 row_h.append(
#                     f"Crude {cp:+d}% / Products {pp:+d}%<br>"
#                     f"Avg 3-2-1: {'$'+str(avg)+'/bbl' if avg else '—'}<br>"
#                     f"Status: {spread_label(avg)}"
#                 )
#             heat_z.append(row_z)
#             hover_z.append(row_h)

#         fig_heat = go.Figure(go.Heatmap(
#             z=heat_z,
#             x=[f"{c:+d}%" for c in crude_steps],
#             y=[f"{p:+d}%" for p in product_steps],
#             text=[[f"${v:.0f}" if v else "—" for v in row] for row in heat_z],
#             texttemplate="%{text}",
#             textfont=dict(size=10, color="#E6EDF3"),
#             hovertext=hover_z, hoverinfo="text",
#             colorscale=[
#                 [0.0,"#8B0000"],[0.2,"#F85149"],[0.4,"#E8A020"],
#                 [0.6,"#5A9E3A"],[1.0,"#1A5C1A"],
#             ],
#             zmid=18,
#             colorbar=dict(title=dict(text="$/bbl", font=dict(color="#E6EDF3")),
#                 tickfont=dict(color="#E6EDF3")),
#         ))
#         fig_heat.update_layout(
#             paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#             font_color="#E6EDF3",
#             xaxis=dict(title="Crude Price Change", gridcolor="#21262D"),
#             yaxis=dict(title="Product Price Change", gridcolor="#21262D"),
#             margin=dict(l=0,r=0,t=8,b=0), height=380,
#         )
#         st.plotly_chart(fig_heat, use_container_width=True)

#         # Standard stress grid below heatmap
#         st.markdown("<div class='sec-hdr'>Standard Stress Scenarios</div>",
#                     unsafe_allow_html=True)
#         sr = run_stress_test(margins)
#         locs  = sr["locations"]
#         short = [l.split("—")[-1].split(",")[0].strip() for l in locs]
#         rows  = []
#         for sc in sr["scenarios"]:
#             row = {"Scenario": sc}
#             for loc, srt in zip(locs, short):
#                 v = sr["grid"][sc].get(loc)
#                 row[srt] = round(v,1) if v else None
#             rows.append(row)
#         df_s = pd.DataFrame(rows)
#         base  = {srt: sr["base"].get(loc) for loc, srt in zip(locs, short)}

#         def cstyle(row):
#             out = []
#             for col in df_s.columns:
#                 if col=="Scenario":
#                     out.append("color:#E6EDF3;background:#161B22;font-weight:600"); continue
#                 v = row[col]; b = base.get(col)
#                 if v is None or b is None:
#                     out.append("color:#8B949E"); continue
#                 out.append("background:#0D2A1A;color:#3FB950;font-weight:600"
#                             if v > b+0.5 else
#                             ("background:#2A0D0D;color:#F85149;font-weight:600"
#                              if v < b-0.5 else "color:#E6EDF3"))
#             return out
#         st.dataframe(df_s.style.apply(cstyle,axis=1),
#                      use_container_width=True, hide_index=True)

#     else:
#         # Single location deep what-if
#         loc_names = [r["display"] for r in margins if r.get("spread_321")]
#         sel = st.selectbox("Select Location", loc_names, key="sc_loc")
#         r   = next((m for m in margins if m["display"]==sel), None)
#         if not r:
#             return

#         st.markdown("---")
#         st.markdown(f"<div class='sec-hdr'>What-If Calculator — {sel}</div>",
#                     unsafe_allow_html=True)
#         st.caption("Adjust any input below — results update instantly")

#         # Input levers
#         ia, ib, ic = st.columns(3)
#         with ia:
#             st.markdown("**Price Adjustments**")
#             wti_adj  = st.number_input("WTI change ($/bbl)",
#                 min_value=-30.0, max_value=30.0, value=0.0, step=1.0, key="sc_wti")
#             gas_adj  = st.number_input("Gasoline change ($/gal)",
#                 min_value=-1.0, max_value=1.0, value=0.0, step=0.05, key="sc_gas")
#             dies_adj = st.number_input("Diesel change ($/gal)",
#                 min_value=-1.0, max_value=1.0, value=0.0, step=0.05, key="sc_die")
#         with ib:
#             st.markdown("**Crude Differentials**")
#             crude_diff_sc = st.number_input("Light crude diff vs base ($/bbl)",
#                 min_value=-10.0, max_value=10.0, value=0.0, step=0.25, key="sc_cd")
#             tp_sc = st.number_input("Throughput (bbl/day)",
#                 min_value=0, max_value=200000,
#                 value=int(r.get("throughput",30000)), step=1000, key="sc_tp")
#         with ic:
#             st.markdown("**Yield Adjustments (%)**")
#             gas_yld = st.number_input("Gasoline yield",
#                 min_value=0.0, max_value=70.0,
#                 value=round(st.session_state.get("yield_gasoline",46.5),1),
#                 step=1.0, key="sc_gy")
#             die_yld = st.number_input("Diesel yield",
#                 min_value=0.0, max_value=50.0,
#                 value=round(st.session_state.get("yield_ulsd",28.6),1),
#                 step=1.0, key="sc_dy")

#         # Compute scenario
#         base_321   = r.get("spread_321",0)
#         new_crude  = (r.get("crude_light",80))  + wti_adj + crude_diff_sc
#         new_gas    = (r.get("wholesale_gas",2.50))  + gas_adj
#         new_diesel = (r.get("wholesale_diesel",3.50)) + dies_adj
#         sc_yields  = {**yields, "gasoline": gas_yld/100, "ulsd": die_yld/100}
#         sc_321     = round(_c321(new_crude, new_gas, new_diesel), 2)
#         sc_delta   = round(sc_321 - base_321, 2)
#         sc_pnl     = fmt_pnl(sc_321, tp_sc)
#         base_pnl   = fmt_pnl(base_321, tp_sc)
#         pnl_delta  = round((sc_pnl or 0) - (base_pnl or 0), 2) if sc_pnl and base_pnl else None
#         delta_clr  = "#3FB950" if sc_delta >= 0 else "#F85149"
#         sign       = "+" if sc_delta >= 0 else ""

#         st.markdown("---")
#         r1,r2,r3,r4 = st.columns(4)
#         r1.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Base 3-2-1</div>
#             <div class='mc-value'>${base_321}/bbl</div>
#             <div class='mc-sub'>{spread_label(base_321)}</div>
#         </div>""", unsafe_allow_html=True)
#         r2.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Scenario 3-2-1</div>
#             <div class='mc-value' style='color:{spread_color(sc_321)}'>${sc_321}/bbl</div>
#             <div class='mc-sub'>{spread_label(sc_321)}</div>
#         </div>""", unsafe_allow_html=True)
#         r3.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>Spread Change</div>
#             <div class='mc-value' style='color:{delta_clr}'>{sign}${sc_delta}/bbl</div>
#             <div class='mc-sub'>vs base case</div>
#         </div>""", unsafe_allow_html=True)
#         r4.markdown(f"""<div class='metric-card'>
#             <div class='mc-label'>P&L Impact / Month</div>
#             <div class='mc-value' style='color:{delta_clr}'>
#                 {('+' if (pnl_delta or 0)>=0 else '')+"$"+str(abs(pnl_delta))+"MM"
#                  if pnl_delta else "—"}
#             </div>
#             <div class='mc-sub'>{f"{tp_sc:,} bbl/day"}</div>
#         </div>""", unsafe_allow_html=True)

#         # Comparison bar
#         st.markdown("<br>", unsafe_allow_html=True)
#         fig_cmp = go.Figure(go.Bar(
#             x=["Base Case", "Scenario"],
#             y=[base_321, sc_321],
#             marker_color=[spread_color(base_321), spread_color(sc_321)],
#             text=[f"${base_321:.2f}/bbl\n${base_pnl:.1f}MM/mo" if base_pnl
#                   else f"${base_321:.2f}/bbl",
#                   f"${sc_321:.2f}/bbl\n${sc_pnl:.1f}MM/mo" if sc_pnl
#                   else f"${sc_321:.2f}/bbl"],
#             textposition="outside",
#             textfont=dict(color="#E6EDF3"),
#             width=0.4,
#         ))
#         for thresh, clr, lbl in [(25,"#3FB950","Strong $25"),
#                                   (12,"#E8A020","Moderate $12")]:
#             fig_cmp.add_hline(y=thresh, line_dash="dot", line_color=clr,
#                               opacity=0.5, annotation_text=lbl,
#                               annotation_font_color=clr,
#                               annotation_font_size=9)
#         fig_cmp.update_layout(
#             paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#             font_color="#E6EDF3",
#             yaxis=dict(title="3-2-1 Crack ($/bbl)", gridcolor="#21262D"),
#             xaxis=dict(gridcolor="#21262D"),
#             margin=dict(l=0,r=0,t=8,b=20),
#             height=280, showlegend=False)
#         st.plotly_chart(fig_cmp, use_container_width=True)

#         # Scenario forward curve
#         if strip and any(strip.values()):
#             st.markdown("<div class='sec-hdr'>Scenario Forward Curve — "
#                         "Base vs What-If</div>", unsafe_allow_html=True)
#             loc_cfg = next((l for l in LOCATIONS if l["display"]==sel), {})
#             n = sel
#             lc = st.session_state.get(f"ldiff_crude_{n}", loc_cfg.get("light_diff",0))
#             lg = st.session_state.get(f"ldiff_gas_{n}",   loc_cfg.get("gas_diff",0))
#             ld = st.session_state.get(f"ldiff_diesel_{n}",loc_cfg.get("diesel_diff",0))
#             fcd= st.session_state.get("fwd_crude_diff",0)
#             fgd= st.session_state.get("fwd_gas_diff",0)
#             fdd= st.session_state.get("fwd_diesel_diff",0)

#             base_fwd = compute_forward_crack(strip=strip,
#                 crude_diff=fcd+lc, gas_diff=fgd+lg, diesel_diff=fdd+ld,
#                 jet_fwd=st.session_state.get("jet_override",4.07),
#                 bunker_fwd=st.session_state.get("bunker_override",2.52),
#                 asphalt_fwd=st.session_state.get("asphalt_override",2.16),
#                 yields=yields)
#             sc_fwd = compute_forward_crack(strip=strip,
#                 crude_diff=fcd+lc+wti_adj+crude_diff_sc,
#                 gas_diff=fgd+lg+gas_adj,
#                 diesel_diff=fdd+ld+dies_adj,
#                 jet_fwd=st.session_state.get("jet_override",4.07),
#                 bunker_fwd=st.session_state.get("bunker_override",2.52),
#                 asphalt_fwd=st.session_state.get("asphalt_override",2.16),
#                 yields=sc_yields)

#             if base_fwd and sc_fwd:
#                 bmo   = [r2["month"]     for r2 in base_fwd if r2.get("crack_321")]
#                 b321  = [r2["crack_321"] for r2 in base_fwd if r2.get("crack_321")]
#                 smo   = [r2["month"]     for r2 in sc_fwd   if r2.get("crack_321")]
#                 s321_ = [r2["crack_321"] for r2 in sc_fwd   if r2.get("crack_321")]

#                 fig_sf = go.Figure()
#                 fig_sf.add_trace(go.Scatter(x=bmo, y=b321,
#                     name="Base Case", line=dict(color="#4A90D9",width=2)))
#                 fig_sf.add_trace(go.Scatter(x=smo, y=s321_,
#                     name="Scenario",
#                     line=dict(color="#E8A020" if sc_delta>=0 else "#F85149",
#                               width=2.5, dash="dash")))
#                 fig_sf.update_layout(
#                     paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#                     font_color="#E6EDF3",
#                     xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                     yaxis=dict(gridcolor="#21262D", title="$/bbl"),
#                     legend=dict(bgcolor="#161B22"),
#                     margin=dict(l=0,r=0,t=8,b=0), height=280)
#                 st.plotly_chart(fig_sf, use_container_width=True)

#         # P&L sensitivity table
#         st.markdown("<div class='sec-hdr'>P&L Sensitivity — "
#                     "$/bbl × Throughput</div>", unsafe_allow_html=True)
#         tp_range = [10000,20000,30000,50000,75000,100000]
#         spread_range = [max(0,sc_321-10), max(0,sc_321-5), sc_321,
#                         sc_321+5, sc_321+10]
#         sens_rows = []
#         for sp in spread_range:
#             row = {"Spread ($/bbl)": f"${sp:.1f}"}
#             for tp_v in tp_range:
#                 pnl_v = round(sp * tp_v * 30 / 1e6, 2)
#                 row[f"{tp_v//1000}k bbl/d"] = f"${pnl_v:.1f}MM"
#             sens_rows.append(row)
#         df_sens = pd.DataFrame(sens_rows)

#         def hl_current(row):
#             spread_str = row["Spread ($/bbl)"]
#             is_current = str(sc_321) in spread_str
#             if is_current:
#                 return [f"background:#21262D;color:#E8A020;font-weight:600"]*len(row)
#             return [""]*len(row)
#         st.dataframe(df_sens.style.apply(hl_current,axis=1),
#                      use_container_width=True, hide_index=True)


# # ══════════════════════════════════════════════════════════════════════════════
# # TAB 4 — Inputs & Configuration
# # ══════════════════════════════════════════════════════════════════════════════
# def show_inputs():
#     st.markdown("<div class='sec-hdr'>Market Price Overrides</div>",
#                 unsafe_allow_html=True)
#     st.caption("Values pre-populated from live CME/EIA data. "
#                "Edit to model specific scenarios.")

#     live = get_spot_prices_live()
#     live_spec = get_specialty_live()

#     if st.button("↺  Reset All to Live Market Prices"):
#         ulsd_l = live.get("ulsd_gal", 3.50) or 3.50
#         wti_l  = live.get("wti_bbl",  80.0) or 80.0
#         st.session_state["wti_override"]     = wti_l
#         st.session_state["rbob_override"]    = live.get("rbob_gal", 2.50) or 2.50
#         st.session_state["ulsd_override"]    = ulsd_l
#         st.session_state["jet_override"]     = live_spec.get("jet_gal")     or ulsd_l*1.05
#         st.session_state["bunker_override"]  = live_spec.get("bunker_gal")  or ulsd_l*0.70
#         st.session_state["catfeed_override"] = wti_l * 0.95 / 42
#         st.session_state["asphalt_override"] = live_spec.get("asphalt_gal") or ulsd_l*0.60
#         st.rerun()

#     p1,p2,p3,p4 = st.columns(4)
#     st.session_state["wti_override"] = p1.number_input(
#         "WTI Crude ($/bbl)", min_value=20.0, max_value=200.0,
#         value=float(st.session_state.get("wti_override",80.0)),
#         step=0.25, format="%.2f", key="inp_wti")
#     st.session_state["rbob_override"] = p2.number_input(
#         "RBOB Gasoline ($/gal)", min_value=0.50, max_value=10.0,
#         value=float(st.session_state.get("rbob_override",2.50)),
#         step=0.01, format="%.3f", key="inp_rbob")
#     st.session_state["ulsd_override"] = p3.number_input(
#         "ULSD Diesel ($/gal)", min_value=0.50, max_value=10.0,
#         value=float(st.session_state.get("ulsd_override",3.50)),
#         step=0.01, format="%.3f", key="inp_ulsd")
#     st.session_state["dist_margin"] = p4.number_input(
#         "Distribution Margin ($/gal)", min_value=0.0, max_value=1.0,
#         value=float(st.session_state.get("dist_margin",0.35)),
#         step=0.01, format="%.2f", key="inp_dist")

#     q1,q2,q3,q4 = st.columns(4)
#     st.session_state["jet_override"] = q1.number_input(
#         "Jet Fuel ($/gal)", min_value=0.50, max_value=15.0,
#         value=float(st.session_state.get("jet_override",4.07)),
#         step=0.01, format="%.3f", key="inp_jet")
#     st.session_state["bunker_override"] = q2.number_input(
#         "Bunker Fuel ($/gal)", min_value=0.20, max_value=10.0,
#         value=float(st.session_state.get("bunker_override",2.52)),
#         step=0.01, format="%.3f", key="inp_bnk")
#     st.session_state["catfeed_override"] = q3.number_input(
#         "Cat Feed / HGO ($/gal)", min_value=0.20, max_value=10.0,
#         value=float(st.session_state.get("catfeed_override",1.90)),
#         step=0.01, format="%.3f", key="inp_cat")
#     st.session_state["asphalt_override"] = q4.number_input(
#         "Asphalt ($/gal)", min_value=0.10, max_value=8.0,
#         value=float(st.session_state.get("asphalt_override",2.16)),
#         step=0.01, format="%.3f", key="inp_asp")

#     # Yield configuration
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Full Yield Configuration (%)</div>",
#                 unsafe_allow_html=True)
#     st.caption("Percentages must sum to ≤ 100%. Refinery Use is consumed, not sold.")

#     YLABELS = {
#         "gasoline":     "Gasoline",
#         "ulsd":         "Diesel/ULSD",
#         "jet":          "Jet Fuel",
#         "bunker":       "Bunker",
#         "asphalt":      "Asphalt",
#         "refinery_use": "Refinery Use",
#     }
#     ycols = st.columns(6)
#     total_y = 0.0
#     for i, (k, lbl) in enumerate(YLABELS.items()):
#         default = round(YIELD_DEFAULTS.get(k, 0.0)*100, 1)
#         val = ycols[i].number_input(
#             f"{lbl} (%)", min_value=0.0, max_value=100.0,
#             value=float(st.session_state.get(f"yield_{k}", default)),
#             step=0.5, format="%.1f", key=f"inp_y_{k}")
#         st.session_state[f"yield_{k}"] = val
#         total_y += val

#     yc = "#3FB950" if total_y <= 100 else "#F85149"
#     st.markdown(
#         f"<span style='color:{yc};font-weight:600'>"
#         f"Total: {total_y:.1f}% "
#         f"({'OK — {:.1f}% unaccounted'.format(100-total_y) if total_y<=100 else 'EXCEEDS 100%'})"
#         f"</span>",
#         unsafe_allow_html=True,
#     )

#     # Per-location differentials
#     st.markdown("---")
#     st.markdown("<div class='sec-hdr'>Per-Location Differentials & Throughput</div>",
#                 unsafe_allow_html=True)
#     st.caption("All diffs are vs NYMEX benchmark. Crude diffs in $/bbl, "
#                "product diffs in $/gal.")

#     hdr = st.columns([2,1,1,1,1,1,1,1])
#     for col, lbl in zip(hdr, ["Location","Crude Light","Crude Heavy",
#                                 "Cat Feed","Gas Diff","Diesel Diff",
#                                 "Jet Diff","Throughput"]):
#         col.markdown(f"<span style='color:#8B949E;font-size:10px;font-weight:600;"
#                      f"text-transform:uppercase'>{lbl}</span>",
#                      unsafe_allow_html=True)

#     for loc in LOCATIONS:
#         n  = loc["display"]
#         short = n.split("—")[-1].split(",")[0].strip()
#         row = st.columns([2,1,1,1,1,1,1,1])
#         row[0].markdown(f"<span style='color:#E6EDF3;font-size:12px'>{short}</span>",
#                         unsafe_allow_html=True)
#         st.session_state[f"ldiff_crude_{n}"] = row[1].number_input(
#             "", min_value=-20.0, max_value=20.0,
#             value=float(st.session_state.get(f"ldiff_crude_{n}",
#                          loc.get("light_diff",0))),
#             step=0.25, format="%.2f", key=f"tbl_lc_{n}",
#             label_visibility="collapsed")
#         st.session_state[f"ldiff_heavy_{n}"] = row[2].number_input(
#             "", min_value=-20.0, max_value=20.0,
#             value=float(st.session_state.get(f"ldiff_heavy_{n}",
#                          loc.get("heavy_diff",0))),
#             step=0.25, format="%.2f", key=f"tbl_lh_{n}",
#             label_visibility="collapsed")
#         st.session_state[f"ldiff_catfeed_{n}"] = row[3].number_input(
#             "", min_value=-20.0, max_value=20.0,
#             value=float(st.session_state.get(f"ldiff_catfeed_{n}",
#                          loc.get("catfeed_diff",0))),
#             step=0.25, format="%.2f", key=f"tbl_cf_{n}",
#             label_visibility="collapsed")
#         st.session_state[f"ldiff_gas_{n}"] = row[4].number_input(
#             "", min_value=-1.0, max_value=1.0,
#             value=float(st.session_state.get(f"ldiff_gas_{n}",
#                          loc.get("gas_diff",0))),
#             step=0.01, format="%.3f", key=f"tbl_g_{n}",
#             label_visibility="collapsed")
#         st.session_state[f"ldiff_diesel_{n}"] = row[5].number_input(
#             "", min_value=-1.0, max_value=1.0,
#             value=float(st.session_state.get(f"ldiff_diesel_{n}",
#                          loc.get("diesel_diff",0))),
#             step=0.01, format="%.3f", key=f"tbl_d_{n}",
#             label_visibility="collapsed")
#         st.session_state[f"ldiff_jet_{n}"] = row[6].number_input(
#             "", min_value=-1.0, max_value=1.0,
#             value=float(st.session_state.get(f"ldiff_jet_{n}", 0.0)),
#             step=0.01, format="%.3f", key=f"tbl_j_{n}",
#             label_visibility="collapsed")
#         st.session_state[f"throughput_{n}"] = int(row[7].number_input(
#             "", min_value=0, max_value=200000,
#             value=int(st.session_state.get(f"throughput_{n}", 30000)),
#             step=1000, key=f"tbl_tp_{n}",
#             label_visibility="collapsed"))


# # ══════════════════════════════════════════════════════════════════════════════
# # MAIN
# # ══════════════════════════════════════════════════════════════════════════════
# def main():
#     check_password()
#     init_state()
#     render_sidebar()

#     st.markdown(
#         "<h2 style='color:#E6EDF3;margin-bottom:2px;margin-top:-8px'>"
#         "🏭 Rogue Refinery Economics</h2>"
#         "<p style='color:#8B949E;margin-bottom:10px;font-size:12px'>"
#         "Portfolio intelligence · CME forward curves · Scenario analysis · "
#         "Throughput P&L</p>",
#         unsafe_allow_html=True,
#     )

#     with st.spinner("Loading..."):
#         strip      = get_cme_strip()
#         loc_prices = get_location_prices()

#     margins, spot, specialty, yields, dist_margin = build_margins(loc_prices)

#     render_ticker(spot, margins)

#     tab1, tab2, tab3, tab4 = st.tabs([
#         "🗺️  Portfolio",
#         "🔬  Location Detail",
#         "🧪  Scenario Builder",
#         "⚙️  Inputs & Config",
#     ])

#     with tab1:
#         show_portfolio(margins, strip, yields)
#     with tab2:
#         show_location_detail(margins, strip, yields)
#     with tab3:
#         show_scenario_builder(margins, strip, yields)
#     with tab4:
#         show_inputs()

#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:6px'>"
#         f"AAA Fuel Gauge · EIA API · CME via rogueng.duckdns.org · "
#         f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>",
#         unsafe_allow_html=True,
#     )


# if __name__ == "__main__":
#     main()



# # app.py — Rogue Refinery Economics — Trading Dashboard
# import streamlit as st
# import pandas as pd
# import plotly.graph_objects as go
# import plotly.express as px
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
# from engine.stress_test import run_stress_test, SCENARIOS

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )

# # ── Dark dashboard CSS ─────────────────────────────────────────────────────────
# st.markdown("""
# <style>
# /* Base */
# .stApp { background-color: #0D1117; }

# /* Ticker bar */
# .ticker-bar {
#     display: flex;
#     gap: 32px;
#     background: #161B22;
#     border: 1px solid #30363D;
#     border-radius: 8px;
#     padding: 12px 24px;
#     margin-bottom: 16px;
#     align-items: center;
# }
# .ticker-item { display: flex; flex-direction: column; align-items: center; }
# .ticker-label { font-size: 10px; color: #8B949E; letter-spacing: 1px; text-transform: uppercase; }
# .ticker-value { font-size: 22px; font-weight: 700; color: #E6EDF3; font-family: monospace; }
# .ticker-delta-up   { font-size: 12px; color: #3FB950; }
# .ticker-delta-down { font-size: 12px; color: #F85149; }
# .ticker-divider { width: 1px; height: 40px; background: #30363D; }

# /* Section headers */
# .section-header {
#     font-size: 11px;
#     font-weight: 600;
#     color: #8B949E;
#     letter-spacing: 2px;
#     text-transform: uppercase;
#     margin-bottom: 8px;
#     margin-top: 4px;
# }

# /* Metric cards */
# .metric-card {
#     background: #161B22;
#     border: 1px solid #30363D;
#     border-radius: 8px;
#     padding: 16px;
#     text-align: center;
# }
# .metric-card-label { font-size: 11px; color: #8B949E; text-transform: uppercase; letter-spacing: 1px; }
# .metric-card-value { font-size: 28px; font-weight: 700; color: #E6EDF3; font-family: monospace; }
# .metric-card-sub   { font-size: 12px; color: #8B949E; margin-top: 2px; }

# /* Portfolio header stat */
# .port-stat {
#     background: #0D1117;
#     border: 1px solid #E8A020;
#     border-radius: 6px;
#     padding: 8px 16px;
#     text-align: center;
#     display: inline-block;
# }

# /* Hide Streamlit chrome */
# #MainMenu {visibility:hidden;}
# footer {visibility:hidden;}
# header {visibility:hidden;}

# /* Tabs */
# .stTabs [data-baseweb="tab-list"] { background: #161B22; border-radius: 8px; padding: 4px; }
# .stTabs [data-baseweb="tab"] { color: #8B949E; }
# .stTabs [aria-selected="true"] { background: #21262D; color: #E6EDF3; border-radius: 6px; }

# /* Sidebar */
# .css-1d391kg, [data-testid="stSidebar"] { background-color: #161B22; }
# </style>
# """, unsafe_allow_html=True)


# # ── Password gate ──────────────────────────────────────────────────────────────
# def check_password():
#     try:
#         correct = st.secrets.get("APP_PASSWORD")
#     except Exception:
#         return
#     if not correct:
#         return
#     if not st.session_state.get("authenticated"):
#         st.title("🏭 Rogue Refinery Economics")
#         st.markdown("---")
#         pwd = st.text_input("Password", type="password")
#         if st.button("Login"):
#             if pwd == correct:
#                 st.session_state["authenticated"] = True
#                 st.rerun()
#             else:
#                 st.error("Incorrect password")
#         st.stop()


# # ── Cached fetchers ────────────────────────────────────────────────────────────
# @st.cache_data(ttl=3600)
# def get_cme_strip():
#     return fetch_cme_forward_curve()

# @st.cache_data(ttl=3600)
# def get_spot_prices():
#     return fetch_spot_prices(EIA_API_KEY)

# @st.cache_data(ttl=3600)
# def get_location_prices():
#     return fetch_location_prices(LOCATIONS)

# @st.cache_data(ttl=86400)
# def get_specialty():
#     return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Colour helpers ─────────────────────────────────────────────────────────────
# def spread_color(val):
#     """Return hex colour for a crack spread value."""
#     if val is None:
#         return "#8B949E"
#     if val >= 25:
#         return "#3FB950"   # green
#     if val >= 12:
#         return "#E8A020"   # amber
#     return "#F85149"       # red

# def spread_label(val):
#     if val is None:
#         return "—"
#     if val >= 25:
#         return "STRONG"
#     if val >= 12:
#         return "MODERATE"
#     return "THIN"


# # ── Sidebar ────────────────────────────────────────────────────────────────────
# def render_sidebar():
#     st.sidebar.markdown(
#         "<div style='text-align:center;padding:12px 0 4px 0;'>"
#         "<span style='font-size:28px'>🏭</span><br>"
#         "<span style='color:#E8A020;font-weight:700;font-size:14px;letter-spacing:2px'>"
#         "ROGUE REFINERY</span><br>"
#         "<span style='color:#8B949E;font-size:10px;letter-spacing:1px'>ECONOMICS DASHBOARD</span>"
#         "</div>",
#         unsafe_allow_html=True,
#     )
#     st.sidebar.markdown("---")

#     refresh = st.sidebar.button("🔄  Refresh Market Data", use_container_width=True)
#     if refresh:
#         get_cme_strip.clear()
#         get_spot_prices.clear()
#         get_location_prices.clear()
#         get_specialty.clear()
#         st.rerun()

#     st.sidebar.markdown("---")
#     st.sidebar.markdown(
#         "<div class='section-header'>Market Assumptions</div>",
#         unsafe_allow_html=True,
#     )
#     dist_margin = st.sidebar.number_input(
#         "Distribution margin ($/gal)",
#         min_value=0.00, max_value=1.00,
#         value=0.35, step=0.01, format="%.2f",
#         help="Retail → Wholesale deduction. Industry range $0.18–$0.55.",
#     )

#     st.sidebar.markdown("---")
#     st.sidebar.markdown(
#         "<div class='section-header'>Product Differentials</div>",
#         unsafe_allow_html=True,
#     )
#     global_gas_diff = st.sidebar.number_input(
#         "Gasoline diff ($/gal)", min_value=-1.0, max_value=1.0,
#         value=0.0, step=0.01, format="%.3f", key="gg",
#     )
#     global_diesel_diff = st.sidebar.number_input(
#         "Diesel diff ($/gal)", min_value=-1.0, max_value=1.0,
#         value=0.0, step=0.01, format="%.3f", key="gd",
#     )

#     st.sidebar.markdown("---")
#     st.sidebar.markdown(
#         "<div class='section-header'>Full Yield Configuration</div>",
#         unsafe_allow_html=True,
#     )
#     st.sidebar.caption("Percentages — must sum to ≤ 100%")
#     YLABELS = {
#         "gasoline":     "Gasoline (%)",
#         "ulsd":         "Diesel / ULSD (%)",
#         "jet":          "Jet Fuel (%)",
#         "bunker":       "Bunker Fuel (%)",
#         "asphalt":      "Asphalt (%)",
#         "refinery_use": "Refinery Use (%)",
#     }
#     yield_pct = {}
#     for key, lbl in YLABELS.items():
#         default = round(YIELD_DEFAULTS.get(key, 0.0) * 100, 1)
#         yield_pct[key] = st.sidebar.number_input(
#             lbl, min_value=0.0, max_value=100.0,
#             value=default, step=0.5, format="%.1f", key=f"y_{key}",
#         )
#     total_pct = sum(yield_pct.values())
#     icon = "🟢" if total_pct <= 100 else "🔴"
#     st.sidebar.caption(f"{icon} Total: {total_pct:.1f}%")
#     yields = {k: round(v / 100, 6) for k, v in yield_pct.items()}

#     st.sidebar.markdown("---")
#     st.sidebar.markdown(
#         "<div class='section-header'>Specialty Prices ($/gal)</div>",
#         unsafe_allow_html=True,
#     )
#     spec_overrides = {}
#     for key, lbl in [
#         ("jet_gal", "Jet Fuel"),
#         ("bunker_gal", "Bunker / Residual"),
#         ("asphalt_gal", "Asphalt"),
#     ]:
#         spec_overrides[key] = st.sidebar.number_input(
#             lbl, min_value=0.0, max_value=20.0,
#             value=float(SPECIALTY_DEFAULTS[key]),
#             step=0.01, format="%.3f", key=f"sp_{key}",
#         )

#     st.sidebar.markdown("---")
#     st.sidebar.markdown(
#         "<div class='section-header'>Forward Curve Diffs</div>",
#         unsafe_allow_html=True,
#     )
#     fwd_crude_diff  = st.sidebar.number_input("Crude diff ($/bbl)",
#         min_value=-15.0, max_value=15.0, value=0.0, step=0.25, format="%.2f", key="fc")
#     fwd_gas_diff    = st.sidebar.number_input("Gasoline diff ($/gal)",
#         min_value=-1.0, max_value=1.0, value=0.0, step=0.01, format="%.3f", key="fg")
#     fwd_diesel_diff = st.sidebar.number_input("Diesel diff ($/gal)",
#         min_value=-1.0, max_value=1.0, value=0.0, step=0.01, format="%.3f", key="fd")

#     return (
#         dist_margin, yields, spec_overrides,
#         global_gas_diff, global_diesel_diff,
#         fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#     )


# # ── Ticker bar ─────────────────────────────────────────────────────────────────
# def render_ticker(spot, margins):
#     wti  = spot.get("wti_bbl")
#     rbob = spot.get("rbob_gal")
#     ulsd = spot.get("ulsd_gal")
#     spreads = [r["spread_321"] for r in margins if r.get("spread_321")]
#     port_avg = round(sum(spreads) / len(spreads), 2) if spreads else None
#     port_color = spread_color(port_avg)

#     def fmt_bbl(v):  return f"${v:.2f}" if v else "—"
#     def fmt_gal(v):  return f"${v:.3f}" if v else "—"

#     st.markdown(f"""
#     <div class="ticker-bar">
#       <div class="ticker-item">
#         <span class="ticker-label">WTI Crude</span>
#         <span class="ticker-value">{fmt_bbl(wti)}</span>
#         <span class="ticker-label">per barrel</span>
#       </div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">RBOB Gasoline</span>
#         <span class="ticker-value">{fmt_gal(rbob)}</span>
#         <span class="ticker-label">per gallon</span>
#       </div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">ULSD Diesel</span>
#         <span class="ticker-value">{fmt_gal(ulsd)}</span>
#         <span class="ticker-label">per gallon</span>
#       </div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">RBOB ($/bbl equiv)</span>
#         <span class="ticker-value">{fmt_bbl(round(rbob*42,2) if rbob else None)}</span>
#         <span class="ticker-label">×42 gal/bbl</span>
#       </div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Portfolio Avg 3-2-1</span>
#         <span class="ticker-value" style="color:{port_color}">
#           {"$"+str(port_avg)+"/bbl" if port_avg else "—"}
#         </span>
#         <span class="ticker-label" style="color:{port_color}">
#           {spread_label(port_avg)}
#         </span>
#       </div>
#       <div class="ticker-divider"></div>
#       <div class="ticker-item">
#         <span class="ticker-label">Locations</span>
#         <span class="ticker-value">{len([r for r in margins if r.get("spread_321")])}</span>
#         <span class="ticker-label">active</span>
#       </div>
#     </div>
#     """, unsafe_allow_html=True)


# # ── TAB 1: Portfolio Overview ──────────────────────────────────────────────────
# def show_portfolio(margins, strip, yields, spec_overrides,
#                    fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff):

#     # ── US Map ────────────────────────────────────────────────────────────────
#     st.markdown(
#         "<div class='section-header'>Refinery Location Map — 3-2-1 Crack Spread</div>",
#         unsafe_allow_html=True,
#     )

#     # Location coordinates (city-level centroids)
#     LOC_COORDS = {
#         "Alaska — Port Mackenzie":  (61.35, -150.02),
#         "Greenport — Austin, TX":   (30.27, -97.74),
#         "Victoria, TX":             (28.81, -97.00),
#         "Duncan, OK":               (34.50, -97.96),
#         "Dewey, OK":                (36.80, -95.93),
#         "North Dakota — Stampede":  (48.40, -101.30),
#         "Big Spring, TX":           (32.25, -101.48),
#         "Utah":                     (40.76, -111.89),
#         "SE New Mexico":            (33.39, -104.52),
#         "Louisiana":                (30.22, -92.02),
#         "Edmonton, Alberta":        (53.55, -113.49),
#         "Puerto Rico":              (18.22, -66.59),
#     }

#     map_rows = []
#     for r in margins:
#         coords = LOC_COORDS.get(r["display"], (39.5, -98.35))
#         spread = r.get("spread_321")
#         map_rows.append({
#             "location":  r["display"],
#             "lat":       coords[0],
#             "lon":       coords[1],
#             "spread_321": spread,
#             "spread_full": r.get("spread_full"),
#             "retail_gas": r.get("retail_gas"),
#             "wholesale_gas": r.get("wholesale_gas"),
#             "crude_light": r.get("crude_light"),
#             "status":    spread_label(spread),
#             "color":     spread_color(spread),
#             "hover": (
#                 f"<b>{r['display']}</b><br>"
#                 f"3-2-1 Crack: {'$'+str(spread)+'/bbl' if spread else '—'}<br>"
#                 f"Full Yield: {'$'+str(r.get('spread_full'))+'/bbl' if r.get('spread_full') else '—'}<br>"
#                 f"Retail Gas: {'$'+str(r.get('retail_gas'))+'/gal' if r.get('retail_gas') else '—'}<br>"
#                 f"Wholesale Gas: {'$'+str(r.get('wholesale_gas'))+'/gal' if r.get('wholesale_gas') else '—'}<br>"
#                 f"Light Crude: {'$'+str(r.get('crude_light'))+'/bbl' if r.get('crude_light') else '—'}<br>"
#                 f"Status: {spread_label(spread)}"
#             ),
#         })

#     df_map = pd.DataFrame(map_rows)

#     fig_map = go.Figure()
#     fig_map.add_trace(go.Scattergeo(
#         lat=df_map["lat"],
#         lon=df_map["lon"],
#         mode="markers+text",
#         marker=dict(
#             size=18,
#             color=df_map["color"].tolist(),
#             line=dict(width=2, color="#0D1117"),
#             opacity=0.92,
#         ),
#         text=df_map["location"].apply(lambda x: x.split("—")[-1].split(",")[0].strip()),
#         textposition="top center",
#         textfont=dict(size=10, color="#E6EDF3"),
#         hovertext=df_map["hover"],
#         hoverinfo="text",
#         customdata=df_map[["spread_321", "status"]].values,
#     ))

#     # Add spread labels on map
#     for _, row in df_map.iterrows():
#         if row["spread_321"]:
#             fig_map.add_trace(go.Scattergeo(
#                 lat=[row["lat"] - 1.8],
#                 lon=[row["lon"]],
#                 mode="text",
#                 text=[f"${row['spread_321']:.0f}"],
#                 textfont=dict(size=9, color=row["color"]),
#                 hoverinfo="skip",
#                 showlegend=False,
#             ))

#     fig_map.update_layout(
#         geo=dict(
#             scope="world",
#             showland=True,    landcolor="#1C2128",
#             showocean=True,   oceancolor="#0D1117",
#             showlakes=True,   lakecolor="#0D1117",
#             showcountries=True, countrycolor="#30363D",
#             showcoastlines=True, coastlinecolor="#30363D",
#             showframe=False,
#             bgcolor="#0D1117",
#             center=dict(lat=42, lon=-98),
#             projection_scale=2.8,
#             lonaxis_range=[-170, -50],
#             lataxis_range=[15,  72],
#         ),
#         paper_bgcolor="#0D1117",
#         margin=dict(l=0, r=0, t=0, b=0),
#         height=420,
#         showlegend=False,
#     )

#     # Legend annotation
#     for label, color, min_v, max_v in [
#         ("STRONG ≥$25", "#3FB950", None, None),
#         ("MODERATE $12-25", "#E8A020", None, None),
#         ("THIN <$12", "#F85149", None, None),
#     ]:
#         fig_map.add_annotation(
#             x=0.01, y=0.12 if "STRONG" in label else (0.08 if "MOD" in label else 0.04),
#             xref="paper", yref="paper",
#             text=f"● {label}",
#             showarrow=False,
#             font=dict(color=color, size=11),
#             bgcolor="#0D1117",
#             align="left",
#         )

#     st.plotly_chart(fig_map, use_container_width=True)

#     # ── Two column layout: Ranking + Forward ──────────────────────────────────
#     left, right = st.columns([1, 1], gap="large")

#     with left:
#         st.markdown(
#             "<div class='section-header'>Portfolio Margin Ranking — 3-2-1 ($/bbl)</div>",
#             unsafe_allow_html=True,
#         )

#         ranked = sorted(
#             [r for r in margins if r.get("spread_321")],
#             key=lambda x: x["spread_321"],
#         )
#         if ranked:
#             short_names = [r["display"].split("—")[-1].split(",")[0].strip()
#                            for r in ranked]
#             spreads_321 = [r["spread_321"] for r in ranked]
#             colors_bar  = [spread_color(v) for v in spreads_321]

#             fig_rank = go.Figure(go.Bar(
#                 x=spreads_321,
#                 y=short_names,
#                 orientation="h",
#                 marker_color=colors_bar,
#                 marker_line_width=0,
#                 text=[f"${v:.1f}" for v in spreads_321],
#                 textposition="outside",
#                 textfont=dict(color="#E6EDF3", size=11),
#             ))
#             fig_rank.update_layout(
#                 paper_bgcolor="#0D1117",
#                 plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(
#                     title="$/bbl",
#                     gridcolor="#21262D",
#                     zeroline=True, zerolinecolor="#30363D",
#                 ),
#                 yaxis=dict(gridcolor="#21262D"),
#                 margin=dict(l=0, r=60, t=8, b=0),
#                 height=360,
#                 showlegend=False,
#             )
#             # Threshold lines
#             for thresh, color, label in [(25, "#3FB950", "Strong"), (12, "#E8A020", "Moderate")]:
#                 fig_rank.add_vline(
#                     x=thresh, line_dash="dot",
#                     line_color=color, opacity=0.5,
#                     annotation_text=label,
#                     annotation_font_color=color,
#                     annotation_font_size=9,
#                 )
#             st.plotly_chart(fig_rank, use_container_width=True)

#     with right:
#         st.markdown(
#             "<div class='section-header'>Portfolio Forward Curve — CME Settle</div>",
#             unsafe_allow_html=True,
#         )

#         jet_fwd     = spec_overrides.get("jet_gal",     4.07)
#         bunker_fwd  = spec_overrides.get("bunker_gal",  2.52)
#         asphalt_fwd = spec_overrides.get("asphalt_gal", 2.16)

#         fwd_rows = compute_forward_crack(
#             strip        = strip,
#             crude_diff   = fwd_crude_diff,
#             gas_diff     = fwd_gas_diff,
#             diesel_diff  = fwd_diesel_diff,
#             jet_fwd      = jet_fwd,
#             bunker_fwd   = bunker_fwd,
#             asphalt_fwd  = asphalt_fwd,
#             yields       = yields,
#         )

#         if fwd_rows:
#             months     = [r["month"]     for r in fwd_rows if r.get("crack_321")]
#             fwd_321    = [r["crack_321"] for r in fwd_rows if r.get("crack_321")]
#             fwd_full   = [r["crack_full"]for r in fwd_rows if r.get("crack_full")]

#             # Stress case: −20% crude, −20% products
#             fwd_stress = compute_forward_crack(
#                 strip        = strip,
#                 crude_diff   = fwd_crude_diff + (strip.get("wti", [{}])[0].get("price", 80) * 0.20)
#                                if strip.get("wti") else fwd_crude_diff,
#                 gas_diff     = fwd_gas_diff    - 0.20,
#                 diesel_diff  = fwd_diesel_diff - 0.20,
#                 jet_fwd      = jet_fwd * 0.80,
#                 bunker_fwd   = bunker_fwd * 0.80,
#                 asphalt_fwd  = asphalt_fwd * 0.80,
#                 yields       = yields,
#             )
#             stress_321 = [r.get("crack_321") for r in fwd_stress if r.get("crack_321")]
#             stress_m   = [r["month"] for r in fwd_stress if r.get("crack_321")]

#             fig_fwd = go.Figure()

#             # Stress band fill
#             if stress_321 and len(stress_321) == len(fwd_321):
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months + months[::-1],
#                     y=fwd_321 + stress_321[::-1],
#                     fill="toself",
#                     fillcolor="rgba(248,81,73,0.10)",
#                     line=dict(width=0),
#                     name="Stress Band (−20%)",
#                     hoverinfo="skip",
#                 ))

#             fig_fwd.add_trace(go.Scatter(
#                 x=months, y=fwd_321,
#                 name="3-2-1 Crack ($/bbl)",
#                 line=dict(color="#E8A020", width=2.5),
#                 mode="lines+markers",
#                 marker=dict(size=5),
#             ))
#             if fwd_full:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=months, y=fwd_full,
#                     name="Full Yield ($/bbl)",
#                     line=dict(color="#5A9E3A", width=2, dash="dot"),
#                 ))
#             if stress_321:
#                 fig_fwd.add_trace(go.Scatter(
#                     x=stress_m, y=stress_321,
#                     name="Stress Case −20%",
#                     line=dict(color="#F85149", width=1.5, dash="dash"),
#                 ))

#             fig_fwd.update_layout(
#                 paper_bgcolor="#0D1117",
#                 plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(gridcolor="#21262D", title="$/bbl"),
#                 legend=dict(bgcolor="#161B22", bordercolor="#30363D",
#                             font=dict(size=10)),
#                 margin=dict(l=0, r=0, t=8, b=0),
#                 height=360,
#             )
#             st.plotly_chart(fig_fwd, use_container_width=True)
#         else:
#             st.info("Forward curve data loading...")

#     # ── Audit downloads ────────────────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown(
#         "<div class='section-header'>Audit Downloads</div>",
#         unsafe_allow_html=True,
#     )
#     dl1, dl2, dl3 = st.columns(3)

#     # Full price waterfall CSV
#     wf_rows = []
#     for r in margins:
#         wf_rows.append({
#             "Location":           r["display"],
#             "Source":             r.get("source"),
#             "Retail Gas ($/gal)": r.get("retail_gas"),
#             "Federal Tax":        r.get("federal_tax_gas"),
#             "State Tax":          r.get("state_tax_gas"),
#             "Total Tax":          r.get("total_tax_gas"),
#             "Pre-tax Gas":        r.get("pretax_gas"),
#             "Distribution Margin":r.get("dist_margin"),
#             "Wholesale Gas":      r.get("wholesale_gas"),
#             "Retail Diesel":      r.get("retail_diesel"),
#             "Pre-tax Diesel":     r.get("pretax_diesel"),
#             "Wholesale Diesel":   r.get("wholesale_diesel"),
#             "Light Crude ($/bbl)":r.get("crude_light"),
#             "Heavy Crude":        r.get("crude_heavy"),
#             "Cat Feed":           r.get("crude_catfeed"),
#             "3-2-1 Spread":       r.get("spread_321"),
#             "2-1-1 Spread":       r.get("spread_211"),
#             "5-3-2 Spread":       r.get("spread_532"),
#             "Full Yield Spread":  r.get("spread_full"),
#             "As Of":              datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })

#     with dl1:
#         st.download_button(
#             "⬇️ Price Waterfall (all locations)",
#             data=pd.DataFrame(wf_rows).to_csv(index=False),
#             file_name="rogue_price_waterfall.csv",
#             mime="text/csv",
#             use_container_width=True,
#         )

#     # Forward curve CSV
#     if fwd_rows:
#         with dl2:
#             st.download_button(
#                 "⬇️ Forward Curve (CME settle)",
#                 data=pd.DataFrame(fwd_rows).to_csv(index=False),
#                 file_name="rogue_forward_curve.csv",
#                 mime="text/csv",
#                 use_container_width=True,
#             )

#     # Stress test CSV
#     stress_result = run_stress_test(margins)
#     if stress_result["base"]:
#         locs = stress_result["locations"]
#         stress_rows = []
#         for scenario in stress_result["scenarios"]:
#             row = {"Scenario": scenario}
#             for loc in locs:
#                 val = stress_result["grid"][scenario].get(loc)
#                 row[loc] = round(val, 2) if val is not None else None
#             stress_rows.append(row)
#         with dl3:
#             st.download_button(
#                 "⬇️ Stress Test Grid",
#                 data=pd.DataFrame(stress_rows).to_csv(index=False),
#                 file_name="rogue_stress_test.csv",
#                 mime="text/csv",
#                 use_container_width=True,
#             )


# # ── TAB 2: Location Deep Dive ──────────────────────────────────────────────────
# def show_location_detail(margins, strip, yields, spec_overrides,
#                           fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff):
#     loc_names = [r["display"] for r in margins if r.get("spread_321")]
#     if not loc_names:
#         st.warning("No margin data available.")
#         return

#     selected = st.selectbox(
#         "Select Refinery Location",
#         options=loc_names,
#         index=0,
#         key="loc_select",
#     )

#     r = next((m for m in margins if m["display"] == selected), None)
#     if not r:
#         st.warning("Location data not found.")
#         return

#     # ── Header KPIs ───────────────────────────────────────────────────────────
#     k1, k2, k3, k4, k5 = st.columns(5)
#     spread_c = spread_color(r.get("spread_321"))
#     k1.markdown(f"""<div class='metric-card'>
#         <div class='metric-card-label'>3-2-1 Crack</div>
#         <div class='metric-card-value' style='color:{spread_c}'>
#             {"$"+str(r['spread_321'])+"/bbl" if r.get('spread_321') else '—'}
#         </div>
#         <div class='metric-card-sub'>{spread_label(r.get("spread_321"))}</div>
#     </div>""", unsafe_allow_html=True)
#     k2.markdown(f"""<div class='metric-card'>
#         <div class='metric-card-label'>Full Yield</div>
#         <div class='metric-card-value' style='color:{spread_color(r.get("spread_full"))}'>
#             {"$"+str(r['spread_full'])+"/bbl" if r.get('spread_full') else '—'}
#         </div>
#         <div class='metric-card-sub'>{spread_label(r.get("spread_full"))}</div>
#     </div>""", unsafe_allow_html=True)
#     k3.markdown(f"""<div class='metric-card'>
#         <div class='metric-card-label'>Light Crude</div>
#         <div class='metric-card-value'>
#             {"$"+str(r['crude_light'])+"/bbl" if r.get('crude_light') else '—'}
#         </div>
#         <div class='metric-card-sub'>WTI + diff</div>
#     </div>""", unsafe_allow_html=True)
#     k4.markdown(f"""<div class='metric-card'>
#         <div class='metric-card-label'>Wholesale Gas</div>
#         <div class='metric-card-value'>
#             {"$"+str(r['wholesale_gas'])+"/gal" if r.get('wholesale_gas') else '—'}
#         </div>
#         <div class='metric-card-sub'>after taxes + dist</div>
#     </div>""", unsafe_allow_html=True)
#     k5.markdown(f"""<div class='metric-card'>
#         <div class='metric-card-label'>Price Source</div>
#         <div class='metric-card-value' style='font-size:14px;padding-top:8px'>
#             {r.get('source','—').replace('AAA Metro — ','').replace('AAA Metro','AAA')}
#         </div>
#         <div class='metric-card-sub'>AAA daily</div>
#     </div>""", unsafe_allow_html=True)

#     st.markdown("<br>", unsafe_allow_html=True)

#     # ── Waterfall + Forward side by side ──────────────────────────────────────
#     wf_col, fwd_col = st.columns([1, 1], gap="large")

#     with wf_col:
#         st.markdown(
#             "<div class='section-header'>Price Waterfall — Gas ($/gal → $/bbl margin)</div>",
#             unsafe_allow_html=True,
#         )
#         if r.get("retail_gas"):
#             retail    = r["retail_gas"]
#             fed_tax   = r.get("federal_tax_gas", 0.184)
#             state_tax = r.get("state_tax_gas", 0.0)
#             dist      = r.get("dist_margin", 0.35)
#             wholesale = r.get("wholesale_gas", 0.0)
#             crude_bbl = r.get("crude_light", 0.0)
#             margin    = r.get("spread_321", 0.0)

#             wf_labels  = ["Retail Price","− Fed Tax","− State Tax",
#                           "− Dist. Margin","= Wholesale","− Crude Cost","= 3-2-1 Margin"]
#             wf_values  = [retail, -fed_tax, -state_tax, -dist,
#                           0, -(crude_bbl/42), 0]
#             wf_measure = ["absolute","relative","relative","relative",
#                           "total","relative","total"]
#             wf_text    = [f"${retail:.3f}",f"-${fed_tax:.3f}",f"-${state_tax:.3f}",
#                           f"-${dist:.3f}", f"${wholesale:.3f}",
#                           f"-${crude_bbl/42:.3f}",
#                           f"${margin/42:.3f}" if margin else "—"]
#             wf_colors  = ["#4A90D9","#F85149","#F85149","#F85149",
#                           "#8B949E","#F85149",spread_color(margin)]

#             fig_wf = go.Figure(go.Waterfall(
#                 orientation="v",
#                 measure=wf_measure,
#                 x=wf_labels,
#                 y=wf_values,
#                 text=wf_text,
#                 textposition="outside",
#                 textfont=dict(size=10, color="#E6EDF3"),
#                 connector=dict(line=dict(color="#30363D", width=1)),
#                 decreasing=dict(marker_color="#F85149"),
#                 increasing=dict(marker_color="#3FB950"),
#                 totals=dict(marker_color="#E8A020"),
#             ))
#             fig_wf.update_layout(
#                 paper_bgcolor="#0D1117",
#                 plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 yaxis=dict(title="$/gal", gridcolor="#21262D"),
#                 xaxis=dict(gridcolor="#21262D", tickangle=-30),
#                 margin=dict(l=0, r=0, t=8, b=0),
#                 height=340,
#                 showlegend=False,
#             )
#             st.plotly_chart(fig_wf, use_container_width=True)

#     with fwd_col:
#         st.markdown(
#             "<div class='section-header'>Forward Crack Spread — This Location</div>",
#             unsafe_allow_html=True,
#         )
#         # Apply this location's crude diff to the forward curve
#         loc_crude_diff = next(
#             (l.get("light_diff", 0) for l in LOCATIONS if l["display"] == selected), 0
#         )
#         loc_gas_diff   = next(
#             (l.get("gas_diff", 0) for l in LOCATIONS if l["display"] == selected), 0
#         )
#         loc_diesel_diff= next(
#             (l.get("diesel_diff", 0) for l in LOCATIONS if l["display"] == selected), 0
#         )

#         jet_fwd    = spec_overrides.get("jet_gal",     4.07)
#         bunker_fwd = spec_overrides.get("bunker_gal",  2.52)
#         asph_fwd   = spec_overrides.get("asphalt_gal", 2.16)

#         loc_fwd = compute_forward_crack(
#             strip       = strip,
#             crude_diff  = fwd_crude_diff + loc_crude_diff,
#             gas_diff    = fwd_gas_diff   + loc_gas_diff,
#             diesel_diff = fwd_diesel_diff+ loc_diesel_diff,
#             jet_fwd     = jet_fwd,
#             bunker_fwd  = bunker_fwd,
#             asphalt_fwd = asph_fwd,
#             yields      = yields,
#         )

#         if loc_fwd:
#             months   = [r2["month"]     for r2 in loc_fwd if r2.get("crack_321")]
#             f321     = [r2["crack_321"] for r2 in loc_fwd if r2.get("crack_321")]
#             ffull    = [r2["crack_full"]for r2 in loc_fwd if r2.get("crack_full")]

#             fig_lfwd = go.Figure()
#             fig_lfwd.add_trace(go.Scatter(
#                 x=months, y=f321,
#                 name="3-2-1 ($/bbl)",
#                 line=dict(color="#E8A020", width=2.5),
#                 mode="lines+markers", marker=dict(size=6),
#                 fill="tozeroy", fillcolor="rgba(232,160,32,0.08)",
#             ))
#             if ffull:
#                 fig_lfwd.add_trace(go.Scatter(
#                     x=months, y=ffull,
#                     name="Full Yield",
#                     line=dict(color="#5A9E3A", width=2, dash="dot"),
#                 ))
#             # Breakeven line
#             fig_lfwd.add_hline(
#                 y=15, line_dash="dot", line_color="#8B949E", opacity=0.5,
#                 annotation_text="Typical breakeven ~$15",
#                 annotation_font_color="#8B949E", annotation_font_size=9,
#             )
#             fig_lfwd.update_layout(
#                 paper_bgcolor="#0D1117",
#                 plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 xaxis=dict(gridcolor="#21262D", tickangle=-45),
#                 yaxis=dict(gridcolor="#21262D", title="$/bbl"),
#                 legend=dict(bgcolor="#161B22", font=dict(size=10)),
#                 margin=dict(l=0, r=0, t=8, b=0),
#                 height=340,
#             )
#             st.plotly_chart(fig_lfwd, use_container_width=True)
#         else:
#             st.info("Forward curve data loading...")

#     # ── All 4 spreads comparison ───────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown(
#         "<div class='section-header'>All Spread Formulas — Current Market</div>",
#         unsafe_allow_html=True,
#     )
#     s1, s2, s3, s4 = st.columns(4)
#     for col, key, label in [
#         (s1, "spread_321", "3-2-1"),
#         (s2, "spread_211", "2-1-1"),
#         (s3, "spread_532", "5-3-2"),
#         (s4, "spread_full", "Full Yield"),
#     ]:
#         val = r.get(key)
#         col.markdown(f"""<div class='metric-card'>
#             <div class='metric-card-label'>{label} Crack</div>
#             <div class='metric-card-value' style='color:{spread_color(val)}'>
#                 {"$"+str(val)+"/bbl" if val else '—'}
#             </div>
#             <div class='metric-card-sub'>{spread_label(val)}</div>
#         </div>""", unsafe_allow_html=True)


# # ── TAB 3: Scenario Builder ────────────────────────────────────────────────────
# def show_scenario_builder(margins):
#     st.markdown(
#         "<div class='section-header'>What-If Scenario Analysis</div>",
#         unsafe_allow_html=True,
#     )

#     # ── Stress grid ───────────────────────────────────────────────────────────
#     result = run_stress_test(margins)
#     if not result["base"]:
#         st.warning("No base case data available.")
#         return

#     locs = result["locations"]
#     short = [l.split("—")[-1].split(",")[0].strip() for l in locs]
#     rows  = []
#     for scenario in result["scenarios"]:
#         row = {"Scenario": scenario}
#         for loc, srt in zip(locs, short):
#             val  = result["grid"][scenario].get(loc)
#             row[srt] = round(val, 1) if val is not None else None
#         rows.append(row)

#     df_stress = pd.DataFrame(rows)
#     base_vals  = {srt: result["base"].get(loc) for loc, srt in zip(locs, short)}

#     def color_row(row):
#         out = []
#         for col in df_stress.columns:
#             if col == "Scenario":
#                 out.append("color:#E6EDF3;background:#161B22;font-weight:600")
#                 continue
#             val  = row[col]
#             base = base_vals.get(col)
#             if val is None or base is None:
#                 out.append("color:#8B949E")
#             elif val > base + 0.5:
#                 out.append("background:#0D2A1A;color:#3FB950;font-weight:600")
#             elif val < base - 0.5:
#                 out.append("background:#2A0D0D;color:#F85149;font-weight:600")
#             else:
#                 out.append("color:#E6EDF3")
#         return out

#     styled = df_stress.style.apply(color_row, axis=1)
#     st.dataframe(styled, use_container_width=True, hide_index=True)

#     # ── Custom scenario ────────────────────────────────────────────────────────
#     st.markdown("---")
#     st.markdown(
#         "<div class='section-header'>Custom Scenario Calculator</div>",
#         unsafe_allow_html=True,
#     )
#     cc1, cc2, cc3 = st.columns(3)
#     crude_chg = cc1.number_input(
#         "Crude price change (%)",
#         min_value=-50.0, max_value=50.0, value=0.0, step=5.0,
#     )
#     prod_chg = cc2.number_input(
#         "Product price change (%)",
#         min_value=-50.0, max_value=50.0, value=0.0, step=5.0,
#     )
#     cc3.markdown("<br>", unsafe_allow_html=True)
#     run_custom = cc3.button("▶  Run Scenario", use_container_width=True)

#     if run_custom or (crude_chg != 0 or prod_chg != 0):
#         from engine.crack import crack_321 as c321
#         crude_mult = 1 + crude_chg / 100
#         prod_mult  = 1 + prod_chg  / 100

#         custom_vals = {}
#         for r in margins:
#             if r.get("spread_321") is None:
#                 continue
#             custom_vals[r["display"]] = round(c321(
#                 r["crude_light"]      * crude_mult,
#                 r["wholesale_gas"]    * prod_mult,
#                 r["wholesale_diesel"] * prod_mult,
#             ), 2)

#         # Visual comparison
#         if custom_vals:
#             base_list    = [result["base"].get(l) for l in locs]
#             custom_list  = [custom_vals.get(l) for l in locs]
#             delta_list   = [
#                 round(c - b, 2) if c is not None and b is not None else None
#                 for c, b in zip(custom_list, base_list)
#             ]

#             fig_compare = go.Figure()
#             fig_compare.add_trace(go.Bar(
#                 name="Base Case",
#                 x=short,
#                 y=base_list,
#                 marker_color="#4A90D9",
#                 opacity=0.7,
#             ))
#             fig_compare.add_trace(go.Bar(
#                 name=f"Scenario (crude {crude_chg:+.0f}%, products {prod_chg:+.0f}%)",
#                 x=short,
#                 y=custom_list,
#                 marker_color=[
#                     "#3FB950" if (c or 0) >= (b or 0) else "#F85149"
#                     for c, b in zip(custom_list, base_list)
#                 ],
#             ))
#             fig_compare.update_layout(
#                 paper_bgcolor="#0D1117",
#                 plot_bgcolor="#161B22",
#                 font_color="#E6EDF3",
#                 barmode="group",
#                 xaxis=dict(tickangle=-35, gridcolor="#21262D"),
#                 yaxis=dict(title="3-2-1 Crack ($/bbl)", gridcolor="#21262D"),
#                 legend=dict(bgcolor="#161B22"),
#                 margin=dict(l=0, r=0, t=8, b=0),
#                 height=340,
#             )
#             st.plotly_chart(fig_compare, use_container_width=True)

#             # Delta table
#             delta_rows = [{"Location": srt, "Base ($/bbl)": b,
#                            "Scenario ($/bbl)": c,
#                            "Change ($/bbl)": d}
#                           for srt, b, c, d in zip(short, base_list, custom_list, delta_list)]
#             df_delta = pd.DataFrame(delta_rows)

#             def color_delta(row):
#                 d = row["Change ($/bbl)"]
#                 if d is None:
#                     return [""] * len(row)
#                 clr = "#3FB950" if d >= 0 else "#F85149"
#                 return [""] * 3 + [f"color:{clr};font-weight:600"]

#             st.dataframe(
#                 df_delta.style.apply(color_delta, axis=1),
#                 use_container_width=True, hide_index=True,
#             )

#             st.download_button(
#                 "⬇️ Download Scenario Comparison",
#                 data=df_delta.to_csv(index=False),
#                 file_name="rogue_scenario.csv",
#                 mime="text/csv",
#             )


# # ── Main ───────────────────────────────────────────────────────────────────────
# def main():
#     check_password()

#     (
#         dist_margin, yields, spec_overrides,
#         global_gas_diff, global_diesel_diff,
#         fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#     ) = render_sidebar()

#     # ── Page header ────────────────────────────────────────────────────────────
#     st.markdown(
#         "<h2 style='color:#E6EDF3;margin-bottom:4px;margin-top:-8px'>"
#         "🏭 Rogue Refinery Economics"
#         "</h2>"
#         "<p style='color:#8B949E;margin-bottom:12px;font-size:13px'>"
#         "Portfolio intelligence · CME forward curves · Scenario analysis"
#         "</p>",
#         unsafe_allow_html=True,
#     )

#     # ── Fetch all data ─────────────────────────────────────────────────────────
#     with st.spinner("Loading market data..."):
#         strip      = get_cme_strip()
#         spot       = get_spot_prices()
#         specialty  = get_specialty()
#         loc_prices = get_location_prices()

#     merged_specialty = {
#         "jet_gal":    spec_overrides.get("jet_gal")    or specialty.get("jet_gal"),
#         "bunker_gal": spec_overrides.get("bunker_gal") or specialty.get("bunker_gal"),
#         "asphalt_gal":spec_overrides.get("asphalt_gal")or specialty.get("asphalt_gal"),
#     }

#     gas_diff_override    = global_gas_diff    if global_gas_diff    != 0 else None
#     diesel_diff_override = global_diesel_diff if global_diesel_diff != 0 else None

#     margins = compute_location_margins(
#         locations             = LOCATIONS,
#         spot_prices           = spot,
#         location_prices       = loc_prices,
#         specialty             = merged_specialty,
#         yields                = yields,
#         dist_margin_gal       = dist_margin,
#         gas_diff_override     = gas_diff_override,
#         diesel_diff_override  = diesel_diff_override,
#     )

#     # ── Ticker ─────────────────────────────────────────────────────────────────
#     render_ticker(spot, margins)

#     # ── Tabs ───────────────────────────────────────────────────────────────────
#     tab1, tab2, tab3 = st.tabs([
#         "🗺️  Portfolio Overview",
#         "🔬  Location Detail",
#         "🧪  Scenario Builder",
#     ])

#     with tab1:
#         show_portfolio(
#             margins, strip, yields, spec_overrides,
#             fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#         )

#     with tab2:
#         show_location_detail(
#             margins, strip, yields, spec_overrides,
#             fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#         )

#     with tab3:
#         show_scenario_builder(margins)

#     # ── Footer ─────────────────────────────────────────────────────────────────
#     st.markdown(
#         f"<div style='color:#484F58;font-size:10px;text-align:right;margin-top:8px'>"
#         f"Data: AAA Fuel Gauge · EIA API · CME via rogueng.duckdns.org · "
#         f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC"
#         f"</div>",
#         unsafe_allow_html=True,
#     )


# if __name__ == "__main__":
#     main()


# # app.py — Rogue Refinery Economics
# import streamlit as st
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
# from engine.stress_test import run_stress_test, SCENARIOS

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )


# # ── Password gate ─────────────────────────────────────────────────────────────

# def check_password():
#     try:
#         correct = st.secrets.get("APP_PASSWORD")
#     except Exception:
#         return
#     if not correct:
#         return
#     if not st.session_state.get("authenticated"):
#         st.title("🏭 Rogue Refinery Economics")
#         st.markdown("---")
#         pwd = st.text_input("Password", type="password")
#         if st.button("Login"):
#             if pwd == correct:
#                 st.session_state["authenticated"] = True
#                 st.rerun()
#             else:
#                 st.error("Incorrect password")
#         st.stop()


# # ── Cached fetchers ───────────────────────────────────────────────────────────

# @st.cache_data(ttl=3600)
# def get_cme_strip():
#     return fetch_cme_forward_curve()


# @st.cache_data(ttl=3600)
# def get_spot_prices():
#     return fetch_spot_prices(EIA_API_KEY)


# @st.cache_data(ttl=3600)
# def get_location_prices():
#     return fetch_location_prices(LOCATIONS)


# @st.cache_data(ttl=86400)
# def get_specialty():
#     return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Sidebar ───────────────────────────────────────────────────────────────────

# def render_sidebar():
#     st.sidebar.title("🏭 Rogue Refinery Economics")
#     st.sidebar.markdown("---")

#     refresh = st.sidebar.button("🔄 Refresh All Data", use_container_width=True)
#     if refresh:
#         get_cme_strip.clear()
#         get_spot_prices.clear()
#         get_location_prices.clear()
#         get_specialty.clear()
#         st.rerun()

#     # Distribution margin
#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Distribution & Retail Margin**")
#     dist_margin = st.sidebar.number_input(
#         "Dist. margin ($/gal)",
#         min_value=0.00, max_value=1.00,
#         value=0.35, step=0.01, format="%.2f",
#         help="Stripped from retail before computing refiner margin. "
#              "Industry range $0.18–$0.55. Default $0.35.",
#     )

#     # Global product diffs (override per-location defaults)
#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Global Product Differentials**")
#     st.sidebar.caption(
#         "Applied on top of per-location diffs from config. "
#         "Set to 0 to use location defaults."
#     )
#     global_gas_diff = st.sidebar.number_input(
#         "Gasoline diff ($/gal)",
#         min_value=-1.00, max_value=1.00,
#         value=0.00, step=0.01, format="%.3f",
#         key="global_gas_diff",
#     )
#     global_diesel_diff = st.sidebar.number_input(
#         "Diesel diff ($/gal)",
#         min_value=-1.00, max_value=1.00,
#         value=0.00, step=0.01, format="%.3f",
#         key="global_diesel_diff",
#     )

#     # Full Yield configuration as percentages
#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Full Yield Configuration**")
#     st.sidebar.caption("Enter as percentages — must sum to ≤ 100%")

#     yield_pct = {}
#     LABELS = {
#         "gasoline":    "Gasoline (%)",
#         "ulsd":        "Diesel / ULSD (%)",
#         "jet":         "Jet Fuel (%)",
#         "bunker":      "Bunker Fuel (%)",
#         "asphalt":     "Asphalt (%)",
#         "refinery_use":"Refinery Use (%)",
#     }

#     for key, label in LABELS.items():
#         default_pct = round(YIELD_DEFAULTS.get(key, 0.0) * 100, 1)
#         val = st.sidebar.number_input(
#             label,
#             min_value=0.0, max_value=100.0,
#             value=default_pct,
#             step=0.5, format="%.1f",
#             key=f"yield_{key}",
#         )
#         yield_pct[key] = val

#     total_pct = sum(yield_pct.values())
#     color_icon = "🟢" if total_pct <= 100 else "🔴"
#     st.sidebar.caption(
#         f"{color_icon} Total: {total_pct:.1f}% "
#         f"({'OK' if total_pct <= 100 else 'EXCEEDS 100% — reduce values'})"
#     )

#     # Convert to decimal fractions for engine
#     yields = {k: round(v / 100, 6) for k, v in yield_pct.items()}

#     # Specialty product price overrides
#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Specialty Prices ($/gal)**")
#     st.sidebar.caption("Override live EIA prices if needed")

#     specialty_overrides = {}
#     for key, label in [
#         ("jet_gal",     "Jet Fuel"),
#         ("bunker_gal",  "Bunker / Residual"),
#         ("asphalt_gal", "Asphalt"),
#     ]:
#         val = st.sidebar.number_input(
#             label,
#             min_value=0.0, max_value=20.0,
#             value=float(SPECIALTY_DEFAULTS[key]),
#             step=0.01, format="%.3f",
#             key=f"specialty_{key}",
#         )
#         specialty_overrides[key] = val

#     # Forward curve product diffs
#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Forward Curve Product Diffs**")
#     st.sidebar.caption(
#         "Applied to CME settle prices when computing "
#         "forward crack spreads. $/gal for products, $/bbl for crude."
#     )
#     fwd_crude_diff = st.sidebar.number_input(
#         "Crude diff ($/bbl)",
#         min_value=-15.0, max_value=15.0,
#         value=0.0, step=0.25, format="%.2f",
#         key="fwd_crude_diff",
#     )
#     fwd_gas_diff = st.sidebar.number_input(
#         "Gasoline diff ($/gal)",
#         min_value=-1.0, max_value=1.0,
#         value=0.0, step=0.01, format="%.3f",
#         key="fwd_gas_diff",
#     )
#     fwd_diesel_diff = st.sidebar.number_input(
#         "Diesel diff ($/gal)",
#         min_value=-1.0, max_value=1.0,
#         value=0.0, step=0.01, format="%.3f",
#         key="fwd_diesel_diff",
#     )

#     return (
#         dist_margin, yields, specialty_overrides,
#         global_gas_diff, global_diesel_diff,
#         fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#     )


# # ── Panel 1: Current Margins ──────────────────────────────────────────────────

# def show_current_margins(margins, spot):
#     st.subheader("📊 Current Refinery Margins by Location")

#     wti  = spot.get("wti_bbl")
#     rbob = spot.get("rbob_gal")
#     ulsd = spot.get("ulsd_gal")

#     c1, c2, c3 = st.columns(3)
#     c1.metric("WTI Crude",     f"${wti:.2f}/bbl"  if wti  else "N/A")
#     c2.metric("RBOB Gasoline", f"${rbob:.3f}/gal" if rbob else "N/A")
#     c3.metric("ULSD",          f"${ulsd:.3f}/gal" if ulsd else "N/A")

#     st.markdown("---")

#     # ── Summary spread grid ───────────────────────────────────────────────────
#     st.markdown("**Crack Spread Summary ($/bbl)**")
#     summary_rows = []
#     for r in margins:
#         summary_rows.append({
#             "Location":       r["display"],
#             "Light Crude":    f"${r['crude_light']:.2f}"  if r.get("crude_light") else "—",
#             "Heavy Crude":    f"${r['crude_heavy']:.2f}"  if r.get("crude_heavy") else "—",
#             "Retail Gas":     f"${r['retail_gas']:.3f}"   if r.get("retail_gas")  else "—",
#             "Pre-tax Gas":    f"${r['pretax_gas']:.3f}"   if r.get("pretax_gas")  else "—",
#             "Wholesale Gas":  f"${r['wholesale_gas']:.3f}"if r.get("wholesale_gas") else "—",
#             "3-2-1":          r.get("spread_321"),
#             "2-1-1":          r.get("spread_211"),
#             "5-3-2":          r.get("spread_532"),
#             "Full Yield":     r.get("spread_full"),
#             "Source":         r.get("source", "—"),
#         })

#     df_summary = pd.DataFrame(summary_rows)
#     st.dataframe(df_summary, use_container_width=True, hide_index=True)

#     # ── Per-location detail expanders ─────────────────────────────────────────
#     st.markdown("---")
#     st.markdown("**Location Detail — Full Price Waterfall**")

#     for r in margins:
#         with st.expander(r["display"]):
#             st.caption(f"Price source: {r.get('source', '—')}")

#             # Price waterfall
#             st.markdown("**Price Waterfall (Gas)**")
#             wf1, wf2, wf3, wf4, wf5 = st.columns(5)
#             wf1.metric("Retail",
#                 f"${r['retail_gas']:.3f}/gal" if r.get("retail_gas") else "—")
#             wf2.metric("− Fed Tax",
#                 f"${r.get('federal_tax_gas', 0.184):.3f}/gal")
#             wf3.metric("− State Tax",
#                 f"${r.get('state_tax_gas', 0):.3f}/gal"
#                 if r.get("state_tax_gas") else "—")
#             wf4.metric("− Dist. Margin",
#                 f"${r.get('dist_margin', 0.35):.3f}/gal")
#             wf5.metric("= Wholesale",
#                 f"${r['wholesale_gas']:.3f}/gal"
#                 if r.get("wholesale_gas") else "—")

#             st.markdown("**Crude Prices ($/bbl)**")
#             cr1, cr2, cr3 = st.columns(3)
#             cr1.metric("Light Crude",
#                 f"${r['crude_light']:.2f}" if r.get("crude_light") else "—")
#             cr2.metric("Heavy Crude",
#                 f"${r['crude_heavy']:.2f}" if r.get("crude_heavy") else "—")
#             cr3.metric("Cat Feed",
#                 f"${r['crude_catfeed']:.2f}" if r.get("crude_catfeed") else "—")

#             st.markdown("**Crack Spreads ($/bbl)**")
#             s1, s2, s3, s4 = st.columns(4)
#             s1.metric("3-2-1",
#                 f"${r['spread_321']:.2f}" if r.get("spread_321") else "—")
#             s2.metric("2-1-1",
#                 f"${r['spread_211']:.2f}" if r.get("spread_211") else "—")
#             s3.metric("5-3-2",
#                 f"${r['spread_532']:.2f}" if r.get("spread_532") else "—")
#             s4.metric("Full Yield",
#                 f"${r['spread_full']:.2f}" if r.get("spread_full") else "—")

#     # Download
#     dl_rows = []
#     for r in margins:
#         dl_rows.append({
#             "Location":         r["display"],
#             "Retail Gas":       r.get("retail_gas"),
#             "Federal Tax":      r.get("federal_tax_gas"),
#             "State Tax":        r.get("state_tax_gas"),
#             "Pre-tax Gas":      r.get("pretax_gas"),
#             "Dist Margin":      r.get("dist_margin"),
#             "Wholesale Gas":    r.get("wholesale_gas"),
#             "Wholesale Diesel": r.get("wholesale_diesel"),
#             "Light Crude":      r.get("crude_light"),
#             "Heavy Crude":      r.get("crude_heavy"),
#             "Cat Feed":         r.get("crude_catfeed"),
#             "3-2-1 ($/bbl)":    r.get("spread_321"),
#             "2-1-1 ($/bbl)":    r.get("spread_211"),
#             "5-3-2 ($/bbl)":    r.get("spread_532"),
#             "Full Yield ($/bbl)":r.get("spread_full"),
#             "Source":           r.get("source"),
#             "As Of":            datetime.now().strftime("%Y-%m-%d %H:%M"),
#         })

#     st.markdown("---")
#     st.download_button(
#         "⬇️ Download Current Margins CSV",
#         data=pd.DataFrame(dl_rows).to_csv(index=False),
#         file_name="rogue_refinery_margins.csv",
#         mime="text/csv",
#     )


# # ── Panel 2: Forward Curve ────────────────────────────────────────────────────

# def show_forward_curve(
#     strip, yields, specialty_overrides,
#     fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
# ):
#     st.subheader("📈 Forward Crack Spread — CME Settle Prices")

#     if not any(strip.values()):
#         st.warning(
#             "CME forward curve unavailable. "
#             "Check connection to rogueng.duckdns.org."
#         )
#         return

#     # Show available months from strip
#     wti_months  = len(strip.get("wti",  []))
#     rbob_months = len(strip.get("rbob", []))
#     ulsd_months = len(strip.get("ulsd", []))

#     st.caption(
#         f"CME settle data: WTI {wti_months} months · "
#         f"RBOB {rbob_months} months · "
#         f"ULSD {ulsd_months} months · "
#         f"Source: rogueng.duckdns.org/cme_excel/output.xlsx"
#     )

#     # Apply diffs and compute forward cracks
#     jet_fwd     = specialty_overrides.get("jet_gal",     4.07)
#     bunker_fwd  = specialty_overrides.get("bunker_gal",  2.52)
#     asphalt_fwd = specialty_overrides.get("asphalt_gal", 2.16)

#     fwd_rows = compute_forward_crack(
#         strip        = strip,
#         crude_diff   = fwd_crude_diff,
#         gas_diff     = fwd_gas_diff,
#         diesel_diff  = fwd_diesel_diff,
#         jet_fwd      = jet_fwd,
#         bunker_fwd   = bunker_fwd,
#         asphalt_fwd  = asphalt_fwd,
#         yields       = yields,
#     )

#     if not fwd_rows:
#         st.warning("No forward rows computed — check strip data.")
#         return

#     df_fwd = pd.DataFrame(fwd_rows)

#     # ── Price strip chart ─────────────────────────────────────────────────────
#     fig_prices = go.Figure()

#     wti_rows  = strip.get("wti",  [])
#     rbob_rows = strip.get("rbob", [])
#     ulsd_rows = strip.get("ulsd", [])

#     if wti_rows:
#         fig_prices.add_trace(go.Scatter(
#             x=[r["month"] for r in wti_rows],
#             y=[r["price"] + fwd_crude_diff for r in wti_rows],
#             name="WTI ($/bbl)",
#             line=dict(color="#E8A020", width=2),
#         ))
#     if rbob_rows:
#         fig_prices.add_trace(go.Scatter(
#             x=[r["month"] for r in rbob_rows],
#             y=[round((r["price"] + fwd_gas_diff) * 42, 2) for r in rbob_rows],
#             name="RBOB ($/bbl equiv)",
#             line=dict(color="#5A9E3A", width=2),
#         ))
#     if ulsd_rows:
#         fig_prices.add_trace(go.Scatter(
#             x=[r["month"] for r in ulsd_rows],
#             y=[round((r["price"] + fwd_diesel_diff) * 42, 2) for r in ulsd_rows],
#             name="ULSD ($/bbl equiv)",
#             line=dict(color="#4A90D9", width=2),
#         ))

#     fig_prices.update_layout(
#         title="CME Forward Strip — WTI / RBOB / ULSD",
#         paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#         font_color="#E6EDF3",
#         yaxis_title="$/bbl",
#         legend=dict(bgcolor="#161B22", bordercolor="#30363D"),
#         margin=dict(l=0, r=0, t=40, b=0),
#         xaxis=dict(gridcolor="#21262D"),
#         yaxis=dict(gridcolor="#21262D"),
#     )
#     st.plotly_chart(fig_prices, use_container_width=True)

#     # ── Forward crack spread chart ────────────────────────────────────────────
#     crack_months = [r["month"]     for r in fwd_rows if r.get("crack_321")]
#     crack_321    = [r["crack_321"] for r in fwd_rows if r.get("crack_321")]
#     crack_full   = [r["crack_full"]for r in fwd_rows if r.get("crack_full")]

#     if crack_months:
#         fig_crack = go.Figure()
#         fig_crack.add_trace(go.Bar(
#             x=crack_months, y=crack_321,
#             name="3-2-1 Crack ($/bbl)",
#             marker_color="#E8A020",
#         ))
#         fig_crack.add_trace(go.Scatter(
#             x=crack_months, y=crack_full,
#             name="Full Yield ($/bbl)",
#             line=dict(color="#5A9E3A", width=2, dash="dot"),
#         ))
#         fig_crack.update_layout(
#             title="Forward Crack Spread — 3-2-1 vs Full Yield",
#             paper_bgcolor="#0D1117", plot_bgcolor="#161B22",
#             font_color="#E6EDF3",
#             yaxis_title="$/bbl",
#             legend=dict(bgcolor="#161B22"),
#             margin=dict(l=0, r=0, t=40, b=0),
#             xaxis=dict(gridcolor="#21262D"),
#             yaxis=dict(gridcolor="#21262D"),
#             barmode="group",
#         )
#         st.plotly_chart(fig_crack, use_container_width=True)

#     # ── Forward data table ────────────────────────────────────────────────────
#     with st.expander("📋 Forward Curve Data Table"):
#         display_cols = {
#             "month":      "Month",
#             "wti":        "WTI ($/bbl)",
#             "rbob":       "RBOB ($/gal)",
#             "ulsd":       "ULSD ($/gal)",
#             "crack_321":  "3-2-1 ($/bbl)",
#             "crack_211":  "2-1-1 ($/bbl)",
#             "crack_532":  "5-3-2 ($/bbl)",
#             "crack_full": "Full Yield ($/bbl)",
#         }
#         cols_available = [c for c in display_cols if c in df_fwd.columns]
#         st.dataframe(
#             df_fwd[cols_available].rename(columns=display_cols),
#             use_container_width=True,
#             hide_index=True,
#         )
#         st.download_button(
#             "⬇️ Download Forward Curve CSV",
#             data=df_fwd.to_csv(index=False),
#             file_name="rogue_forward_curve.csv",
#             mime="text/csv",
#         )


# # ── Panel 3: Stress Test ──────────────────────────────────────────────────────

# def show_stress_test(margins):
#     st.subheader("🧪 Stress Test — What-If Scenarios (3-2-1 $/bbl)")
#     st.caption(
#         "Green = margin improves vs base · Red = worsens. "
#         "All scenarios use 3-2-1 spread formula."
#     )

#     result = run_stress_test(margins)
#     if not result["base"]:
#         st.warning("No base case data available.")
#         return

#     locs = result["locations"]
#     rows = []
#     for scenario in result["scenarios"]:
#         row = {"Scenario": scenario}
#         for loc in locs:
#             val = result["grid"][scenario].get(loc)
#             row[loc] = round(val, 2) if val is not None else None
#         rows.append(row)

#     df = pd.DataFrame(rows)

#     base_row = {loc: result["base"].get(loc) for loc in locs}

#     def color_row(row):
#         colors = []
#         for col in df.columns:
#             if col == "Scenario" or row[col] is None:
#                 colors.append("")
#                 continue
#             base = base_row.get(col)
#             if base is None:
#                 colors.append("")
#             elif row[col] > base:
#                 colors.append("background-color:#1A3A1A;color:#5A9E3A")
#             elif row[col] < base:
#                 colors.append("background-color:#3A1A1A;color:#CC4444")
#             else:
#                 colors.append("")
#         return colors

#     styled = df.style.apply(color_row, axis=1)
#     st.dataframe(styled, use_container_width=True, hide_index=True)

#     # Custom scenario
#     st.markdown("---")
#     st.markdown("**Custom Scenario**")
#     cc1, cc2 = st.columns(2)
#     crude_chg = cc1.number_input(
#         "Crude price change (%)",
#         min_value=-50.0, max_value=50.0, value=0.0, step=1.0,
#     )
#     prod_chg = cc2.number_input(
#         "Product price change (%)",
#         min_value=-50.0, max_value=50.0, value=0.0, step=1.0,
#     )

#     if crude_chg != 0 or prod_chg != 0:
#         from engine.crack import crack_321 as c321
#         crude_mult = 1 + crude_chg / 100
#         prod_mult  = 1 + prod_chg  / 100
#         custom = {"Scenario":
#             f"Custom (crude {crude_chg:+.0f}%, products {prod_chg:+.0f}%)"}
#         for r in margins:
#             if r.get("spread_321") is None:
#                 custom[r["display"]] = None
#                 continue
#             custom[r["display"]] = round(c321(
#                 r["crude_light"]      * crude_mult,
#                 r["wholesale_gas"]    * prod_mult,
#                 r["wholesale_diesel"] * prod_mult,
#             ), 2)
#         st.dataframe(
#             pd.DataFrame([custom]),
#             use_container_width=True, hide_index=True,
#         )

#     st.download_button(
#         "⬇️ Download Stress Test CSV",
#         data=df.to_csv(index=False),
#         file_name="rogue_stress_test.csv",
#         mime="text/csv",
#     )


# # ── Main ──────────────────────────────────────────────────────────────────────

# def main():
#     check_password()

#     (
#         dist_margin, yields, specialty_overrides,
#         global_gas_diff, global_diesel_diff,
#         fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#     ) = render_sidebar()

#     st.title("🏭 Rogue Refinery Economics")
#     st.caption(
#         "Site-specific refinery margin model · "
#         "CME forward curve · Stress testing"
#     )

#     with st.spinner("Fetching CME forward curve and market prices..."):
#         strip      = get_cme_strip()
#         spot       = get_spot_prices()
#         specialty  = get_specialty()
#         loc_prices = get_location_prices()

#     # Merge specialty with sidebar overrides
#     merged_specialty = {
#         "jet_gal":     specialty_overrides.get("jet_gal")
#                        or specialty.get("jet_gal"),
#         "bunker_gal":  specialty_overrides.get("bunker_gal")
#                        or specialty.get("bunker_gal"),
#         "asphalt_gal": specialty_overrides.get("asphalt_gal")
#                        or specialty.get("asphalt_gal"),
#     }

#     # Use None to trigger per-location defaults when global diff is 0
#     gas_diff_override    = global_gas_diff    if global_gas_diff    != 0 else None
#     diesel_diff_override = global_diesel_diff if global_diesel_diff != 0 else None

#     margins = compute_location_margins(
#         locations             = LOCATIONS,
#         spot_prices           = spot,
#         location_prices       = loc_prices,
#         specialty             = merged_specialty,
#         yields                = yields,
#         dist_margin_gal       = dist_margin,
#         gas_diff_override     = gas_diff_override,
#         diesel_diff_override  = diesel_diff_override,
#     )

#     tab1, tab2, tab3 = st.tabs([
#         "📊 Current Margins",
#         "📈 Forward Curve",
#         "🧪 Stress Test",
#     ])

#     with tab1:
#         show_current_margins(margins, spot)

#     with tab2:
#         show_forward_curve(
#             strip, yields, specialty_overrides,
#             fwd_crude_diff, fwd_gas_diff, fwd_diesel_diff,
#         )

#     with tab3:
#         show_stress_test(margins)

#     st.markdown("---")
#     st.caption(
#         f"Data: AAA Fuel Gauge · EIA API · CME via rogueng.duckdns.org · "
#         f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC"
#     )


# if __name__ == "__main__":
#     main()








# # app.py — Rogue Refinery Economics
# import streamlit as st
# import pandas as pd
# from datetime import datetime

# from config import (
#     LOCATIONS, YIELD_DEFAULTS, SPECIALTY_DEFAULTS,
#     GALLONS_PER_BARREL
# )
# from fetchers.prices import (
#     fetch_spot_prices, fetch_forward_strip,
#     fetch_location_prices, fetch_specialty_prices
# )
# from engine.location_margins import compute_location_margins
# from engine.stress_test import run_stress_test, SCENARIOS

# import os
# from dotenv import load_dotenv
# load_dotenv()
# EIA_API_KEY  = os.getenv("EIA_API_KEY",  "")
# FRED_API_KEY = os.getenv("FRED_API_KEY", "")
# try:
#     EIA_API_KEY  = EIA_API_KEY  or st.secrets.get("EIA_API_KEY",  "")
#     FRED_API_KEY = FRED_API_KEY or st.secrets.get("FRED_API_KEY", "")
# except Exception:
#     pass

# st.set_page_config(
#     page_title="Rogue Refinery Economics",
#     page_icon="🏭",
#     layout="wide",
# )


# # ── Password gate ─────────────────────────────────────────────────────────────

# def check_password():
#     try:
#         correct = st.secrets.get("APP_PASSWORD")
#     except Exception:
#         return
#     if not correct:
#         return
#     if not st.session_state.get("authenticated"):
#         st.title("🏭 Rogue Refinery Economics")
#         st.markdown("---")
#         pwd = st.text_input("Password", type="password")
#         if st.button("Login"):
#             if pwd == correct:
#                 st.session_state["authenticated"] = True
#                 st.rerun()
#             else:
#                 st.error("Incorrect password")
#         st.stop()


# # ── Cached fetchers ───────────────────────────────────────────────────────────

# @st.cache_data(ttl=3600)
# def get_spot_prices():
#     return fetch_spot_prices()


# @st.cache_data(ttl=3600)
# def get_forward_strip():
#     return fetch_forward_strip(eia_api_key=EIA_API_KEY)


# @st.cache_data(ttl=3600)
# def get_location_prices():
#     return fetch_location_prices(LOCATIONS)


# @st.cache_data(ttl=86400)
# def get_specialty():
#     return fetch_specialty_prices(EIA_API_KEY, FRED_API_KEY)


# # ── Sidebar: controls ─────────────────────────────────────────────────────────

# def render_sidebar():
#     st.sidebar.title("🏭 Rogue Refinery Economics")
#     st.sidebar.markdown("---")

#     refresh = st.sidebar.button(
#         "🔄 Refresh All Data", use_container_width=True
#     )
#     if refresh:
#         get_spot_prices.clear()
#         get_forward_strip.clear()
#         get_location_prices.clear()
#         get_specialty.clear()
#         st.rerun()

#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Distribution & Retail Margin**")
#     dist_margin = st.sidebar.number_input(
#         "Dist. margin ($/gal)",
#         min_value=0.00, max_value=1.00,
#         value=0.35, step=0.01, format="%.2f",
#         help="Stripped from retail before computing refiner margin. Default $0.35/gal."
#     )

#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Full Yield Configuration**")
#     st.sidebar.caption("Gallons of product per barrel of crude")

#     yields = {}
#     total  = 0.0
#     for product, default in YIELD_DEFAULTS.items():
#         val = st.sidebar.number_input(
#             product.title(),
#             min_value=0.0, max_value=42.0,
#             value=float(default), step=0.5, format="%.1f",
#             key=f"yield_{product}"
#         )
#         yields[product] = val
#         total += val

#     color = "🟢" if total <= 42 else "🔴"
#     st.sidebar.caption(f"{color} Total yield: {total:.1f} / 42.0 gal/bbl")

#     st.sidebar.markdown("---")
#     st.sidebar.markdown("**Specialty Product Prices ($/gal)**")
#     st.sidebar.caption("Override live prices if needed")

#     specialty_overrides = {}
#     for key, label in [
#         ("jet_gal",     "Jet Fuel"),
#         ("bunker_gal",  "Bunker / Residual"),
#         ("asphalt_gal", "Asphalt"),
#     ]:
#         override = st.sidebar.number_input(
#             label,
#             min_value=0.0, max_value=20.0,
#             value=float(SPECIALTY_DEFAULTS[key]),
#             step=0.01, format="%.3f",
#             key=f"specialty_{key}"
#         )
#         specialty_overrides[key] = override

#     return dist_margin, yields, specialty_overrides


# # ── Panel 1: Current Margins ──────────────────────────────────────────────────

# def show_current_margins(margins: list, spot: dict):
#     st.subheader("📊 Current Refinery Margins by Location")

#     wti  = spot.get("wti_bbl")
#     rbob = spot.get("rbob_gal")
#     ulsd = spot.get("ulsd_gal")

#     mc1, mc2, mc3 = st.columns(3)
#     mc1.metric("WTI Crude",      f"${wti:.2f}/bbl"  if wti  else "N/A")
#     mc2.metric("RBOB Gasoline",  f"${rbob:.3f}/gal" if rbob else "N/A")
#     mc3.metric("ULSD",           f"${ulsd:.3f}/gal" if ulsd else "N/A")

#     st.markdown("---")

#     # Main margins table
#     rows = []
#     for r in margins:
#         rows.append({
#             "Location":          r["display"],
#             "Retail Gas":        f"${r['retail_gas']:.3f}"    if r.get("retail_gas")  else "—",
#             "Retail Diesel":     f"${r['retail_diesel']:.3f}" if r.get("retail_diesel") else "—",
#             "Light Crude":       f"${r['crude_light']:.2f}"   if r.get("crude_light") else "—",
#             "Heavy Crude":       f"${r['crude_heavy']:.2f}"   if r.get("crude_heavy") else "—",
#             "3-2-1 ($/bbl)":    r.get("spread_321"),
#             "2-1-1 ($/bbl)":    r.get("spread_211"),
#             "5-3-2 ($/bbl)":    r.get("spread_532"),
#             "Full Yield ($/bbl)":r.get("spread_full"),
#             "Source":            r.get("source", "—"),
#         })

#     df = pd.DataFrame(rows)
#     st.dataframe(df, use_container_width=True, hide_index=True)

#     # Location detail expanders
#     st.markdown("---")
#     st.markdown("**Location Detail**")
#     for r in margins:
#         with st.expander(r["display"]):
#             c1, c2, c3, c4 = st.columns(4)
#             c1.metric("Retail Gas",      f"${r['retail_gas']:.3f}/gal"    if r.get("retail_gas")  else "—")
#             c1.metric("Wholesale Gas",   f"${r['wholesale_gas']:.3f}/gal" if r.get("wholesale_gas") else "—")
#             c2.metric("Retail Diesel",   f"${r['retail_diesel']:.3f}/gal" if r.get("retail_diesel") else "—")
#             c2.metric("Wholesale Diesel",f"${r['wholesale_diesel']:.3f}/gal" if r.get("wholesale_diesel") else "—")
#             c3.metric("Light Crude",     f"${r['crude_light']:.2f}/bbl"   if r.get("crude_light") else "—")
#             c3.metric("Heavy Crude",     f"${r['crude_heavy']:.2f}/bbl"   if r.get("crude_heavy") else "—")
#             c4.metric("Cat Feed",        f"${r['crude_catfeed']:.2f}/bbl" if r.get("crude_catfeed") else "—")
#             c4.metric("Price Source",    r.get("source", "—"))

#             st.markdown("**Crack Spreads ($/bbl)**")
#             s1, s2, s3, s4 = st.columns(4)
#             s1.metric("3-2-1",      f"${r['spread_321']:.2f}"  if r.get("spread_321")  else "—")
#             s2.metric("2-1-1",      f"${r['spread_211']:.2f}"  if r.get("spread_211")  else "—")
#             s3.metric("5-3-2",      f"${r['spread_532']:.2f}"  if r.get("spread_532")  else "—")
#             s4.metric("Full Yield", f"${r['spread_full']:.2f}" if r.get("spread_full") else "—")

#     # Download
#     dl_df = pd.DataFrame([{
#         "Location":      r["display"],
#         "Retail Gas":    r.get("retail_gas"),
#         "Retail Diesel": r.get("retail_diesel"),
#         "Light Crude":   r.get("crude_light"),
#         "Heavy Crude":   r.get("crude_heavy"),
#         "Cat Feed":      r.get("crude_catfeed"),
#         "3-2-1":         r.get("spread_321"),
#         "2-1-1":         r.get("spread_211"),
#         "5-3-2":         r.get("spread_532"),
#         "Full Yield":    r.get("spread_full"),
#         "Source":        r.get("source"),
#         "As Of":         datetime.now().strftime("%Y-%m-%d %H:%M"),
#     } for r in margins])

#     st.download_button(
#         "⬇️ Download Current Margins CSV",
#         data=dl_df.to_csv(index=False),
#         file_name="rogue_refinery_margins.csv",
#         mime="text/csv",
#     )


# # ── Panel 2: Forward Curve ────────────────────────────────────────────────────

# def show_forward_curve(strip: dict, specialty_overrides: dict):
#     st.subheader("📈 Forward Curve")

#     if not any(strip.values()):
#         st.warning("Forward curve data unavailable — yfinance may be rate-limited. Try refreshing.")
#         return

#     # Build forward DataFrame
#     all_months = sorted(set(
#         e["date"] for product in strip.values() for e in product
#     ))

#     rows = []
#     wti_map  = {e["date"]: e["price"] for e in strip.get("wti",  [])}
#     rbob_map = {e["date"]: e["price"] for e in strip.get("rbob", [])}
#     ulsd_map = {e["date"]: e["price"] for e in strip.get("ulsd", [])}

#     for date in all_months:
#         wti  = wti_map.get(date)
#         rbob = rbob_map.get(date)
#         ulsd = ulsd_map.get(date)
#         dt   = datetime.strptime(date, "%Y-%m")

#         # Forward crack spread (3-2-1) using strip prices
#         spread = None
#         if wti and rbob and ulsd:
#             spread = round(
#                 (2 * rbob * 42 + 1 * ulsd * 42 - 3 * wti) / 3, 2
#             )

#         rows.append({
#             "Month":             dt.strftime("%b %Y"),
#             "WTI ($/bbl)":       wti,
#             "RBOB ($/gal)":      rbob,
#             "ULSD ($/gal)":      ulsd,
#             "Jet Fuel ($/gal)":  specialty_overrides.get("jet_gal"),
#             "Bunker ($/gal)":    specialty_overrides.get("bunker_gal"),
#             "Asphalt ($/gal)":   specialty_overrides.get("asphalt_gal"),
#             "Fwd 3-2-1 ($/bbl)": spread,
#         })

#     df = pd.DataFrame(rows)
#     st.dataframe(df, use_container_width=True, hide_index=True)

#     # Chart
#     import plotly.graph_objects as go
#     fig = go.Figure()

#     if strip.get("wti"):
#         wti_dates  = [e["month"] for e in strip["wti"]]
#         wti_prices = [e["price"] for e in strip["wti"]]
#         fig.add_trace(go.Scatter(
#             x=wti_dates, y=wti_prices,
#             name="WTI ($/bbl)", line=dict(color="#E8A020", width=2)
#         ))

#     if strip.get("rbob"):
#         rbob_dates  = [e["month"] for e in strip["rbob"]]
#         rbob_prices = [e["price"] * 42 for e in strip["rbob"]]  # convert to $/bbl
#         fig.add_trace(go.Scatter(
#             x=rbob_dates, y=rbob_prices,
#             name="RBOB ($/bbl)", line=dict(color="#5A9E3A", width=2)
#         ))

#     if strip.get("ulsd"):
#         ulsd_dates  = [e["month"] for e in strip["ulsd"]]
#         ulsd_prices = [e["price"] * 42 for e in strip["ulsd"]]
#         fig.add_trace(go.Scatter(
#             x=ulsd_dates, y=ulsd_prices,
#             name="ULSD ($/bbl)", line=dict(color="#4A90D9", width=2)
#         ))

#     fig.update_layout(
#         title="Forward Strip — WTI / RBOB / ULSD ($/bbl equivalent)",
#         paper_bgcolor="#0D1117", plot_bgcolor="#0D1117",
#         font_color="#E6EDF3",
#         legend=dict(bgcolor="#161B22"),
#         yaxis_title="$/bbl",
#         margin=dict(l=0, r=0, t=40, b=0),
#     )
#     st.plotly_chart(fig, use_container_width=True)

#     st.download_button(
#         "⬇️ Download Forward Curve CSV",
#         data=df.to_csv(index=False),
#         file_name="rogue_forward_curve.csv",
#         mime="text/csv",
#     )


# # ── Panel 3: Stress Test ──────────────────────────────────────────────────────

# def show_stress_test(margins: list):
#     st.subheader("🧪 Stress Test — What-If Scenarios")
#     st.caption(
#         "3-2-1 crack spread ($/bbl) under each scenario. "
#         "Green = improves vs base, Red = worsens."
#     )

#     result = run_stress_test(margins)
#     if not result["base"]:
#         st.warning("No base case data available.")
#         return

#     # Build grid DataFrame
#     locs = result["locations"]
#     rows = []
#     for scenario in result["scenarios"]:
#         row = {"Scenario": scenario}
#         for loc in locs:
#             val  = result["grid"][scenario].get(loc)
#             base = result["base"].get(loc)
#             row[loc] = round(val, 2) if val is not None else None
#         rows.append(row)

#     df = pd.DataFrame(rows)

#     # Color code: compare each cell to base case
#     def color_cell(val, col, base_row):
#         if col == "Scenario" or val is None:
#             return ""
#         base = base_row.get(col)
#         if base is None:
#             return ""
#         if val > base:
#             return "background-color: #1A3A1A; color: #5A9E3A"
#         elif val < base:
#             return "background-color: #3A1A1A; color: #CC4444"
#         return ""

#     base_row = {loc: result["base"].get(loc) for loc in locs}

#     styled = df.style.apply(
#         lambda row: [
#             color_cell(row[col], col, base_row)
#             for col in df.columns
#         ],
#         axis=1
#     )
#     st.dataframe(styled, use_container_width=True, hide_index=True)

#     # Custom scenario
#     st.markdown("---")
#     st.markdown("**Custom Scenario**")
#     cc1, cc2 = st.columns(2)
#     custom_crude = cc1.number_input(
#         "Crude price change (%)",
#         min_value=-50.0, max_value=50.0,
#         value=0.0, step=1.0
#     )
#     custom_prod = cc2.number_input(
#         "Product price change (%)",
#         min_value=-50.0, max_value=50.0,
#         value=0.0, step=1.0
#     )

#     if custom_crude != 0 or custom_prod != 0:
#         custom_row = {"Scenario": f"Custom (crude {custom_crude:+.0f}%, products {custom_prod:+.0f}%)"}
#         crude_mult = 1 + custom_crude / 100
#         prod_mult  = 1 + custom_prod  / 100
#         from engine.crack import crack_321
#         for r in margins:
#             if r.get("spread_321") is None:
#                 custom_row[r["display"]] = None
#                 continue
#             custom_row[r["display"]] = round(crack_321(
#                 r["crude_light"]      * crude_mult,
#                 r["wholesale_gas"]    * prod_mult,
#                 r["wholesale_diesel"] * prod_mult,
#             ), 2)
#         st.dataframe(pd.DataFrame([custom_row]), use_container_width=True, hide_index=True)

#     st.download_button(
#         "⬇️ Download Stress Test CSV",
#         data=df.to_csv(index=False),
#         file_name="rogue_stress_test.csv",
#         mime="text/csv",
#     )


# # ── Main ──────────────────────────────────────────────────────────────────────

# def main():
#     check_password()
#     dist_margin, yields, specialty_overrides = render_sidebar()

#     st.title("🏭 Rogue Refinery Economics")
#     st.caption(
#         "Site-specific refinery margin model · "
#         "Current margins · Forward curve · Stress testing"
#     )

#     with st.spinner("Fetching prices..."):
#         spot      = get_spot_prices()
#         specialty = get_specialty()
#         loc_prices= get_location_prices()

#     # Merge specialty with sidebar overrides
#     merged_specialty = {
#         "jet_gal":     specialty_overrides.get("jet_gal")
#                        or specialty.get("jet_gal"),
#         "bunker_gal":  specialty_overrides.get("bunker_gal")
#                        or specialty.get("bunker_gal"),
#         "asphalt_gal": specialty_overrides.get("asphalt_gal")
#                        or specialty.get("asphalt_gal"),
#     }

#     margins = compute_location_margins(
#         locations       = LOCATIONS,
#         spot_prices     = spot,
#         location_prices = loc_prices,
#         specialty       = merged_specialty,
#         yields          = yields,
#         dist_margin_gal = dist_margin,
#     )

#     # Three tabs
#     tab1, tab2, tab3 = st.tabs([
#         "📊 Current Margins",
#         "📈 Forward Curve",
#         "🧪 Stress Test",
#     ])

#     with tab1:
#         show_current_margins(margins, spot)

#     with tab2:
#         with st.spinner("Fetching forward strip..."):
#             strip = get_forward_strip()
#         show_forward_curve(strip, specialty_overrides)

#     with tab3:
#         show_stress_test(margins)

#     st.markdown("---")
#     st.caption(
#         f"Data: AAA Fuel Gauge · EIA API · NYMEX via yfinance · "
#         f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC"
#     )


# if __name__ == "__main__":
#     main()