"""
MDSI Maritime Dashboard
Real-time maritime and weather alerts — Greenlandic & Faroe Islands waters
"""
import datetime
import io
import re

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MDSI Maritime Dashboard",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────
_HEADERS = {"User-Agent": "MDSI-maritime-dashboard/1.0 pb@mdsi.dk"}

GLOBE_COLORS = {
    "red":    [192, 57,  43,  230],
    "orange": [230, 126, 34,  230],
    "ice":    [93,  173, 226, 230],
    "gold":   [243, 156, 18,  230],
}

DATA_SOURCES = [
    ("MET Norway MetAlerts 2.0",
     "https://api.met.no/weatherapi/metalerts/2.0/current.json",
     "Real-time meteorological alerts for Greenland, Faroe Islands, Davis Strait, Baffin Bay, Greenland Sea"),
    ("Navigation Greenland",
     "https://eng.navigation.gl/",
     "Navigational warnings and notices to mariners for Greenlandic waters"),
    ("UK Met Office Shipping Forecast",
     "https://weather.metoffice.gov.uk/specialist-forecasts/coast-and-sea/shipping-forecast",
     "Shipping forecasts and gale warnings for Faeroes, Bailey, SE Iceland, Viking sea areas"),
    ("Environment Canada / Canadian Ice Service",
     "https://weather.gc.ca/marine/marine_bulletins_e.html",
     "Marine bulletins and ice advisories for Davis Strait, Baffin Bay, Hudson Strait"),
    ("ESRI World Ocean Base",
     "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer",
     "Ocean basemap for georeferenced event mapping"),
]

# ── Sea area polygons (approximate geographic boundaries) ─────────────────────
# Coords are (lat, lon) pairs; drawn as transparent filled overlays on the map.
SEA_AREA_POLYGONS = [
    # Canadian / Arctic waters — blue
    {
        "name": "Baffin Bay",
        "category": "Canadian Waters",
        "color": "#2471A3",
        "coords": [(70,-80),(80,-80),(80,-55),(70,-55)],
    },
    {
        "name": "Davis Strait",
        "category": "Canadian Waters",
        "color": "#2471A3",
        "coords": [(62,-70),(70,-70),(70,-50),(62,-50)],
    },
    {
        "name": "Labrador Sea",
        "category": "Canadian Waters",
        "color": "#2471A3",
        "coords": [(52,-65),(62,-65),(62,-42),(52,-42)],
    },
    {
        "name": "Nares Strait",
        "category": "Arctic Waters",
        "color": "#1A5276",
        "coords": [(76,-75),(83,-75),(83,-60),(76,-60)],
    },
    {
        "name": "Lincoln Sea",
        "category": "Arctic Waters",
        "color": "#1A5276",
        "coords": [(83,-70),(86,-70),(86,-30),(83,-30)],
    },
    # Nordic / Greenlandic waters — teal
    {
        "name": "Greenland Sea",
        "category": "Nordic Waters",
        "color": "#148F77",
        "coords": [(72,-20),(82,-20),(82,5),(72,5)],
    },
    {
        "name": "Wandel Sea",
        "category": "Arctic Waters",
        "color": "#148F77",
        "coords": [(82,-20),(85,-20),(85,10),(82,10)],
    },
    {
        "name": "Denmark Strait",
        "category": "Nordic Waters",
        "color": "#148F77",
        "coords": [(65,-35),(68,-35),(68,-10),(65,-10)],
    },
    {
        "name": "Irminger Sea",
        "category": "Nordic Waters",
        "color": "#148F77",
        "coords": [(57,-45),(65,-45),(65,-20),(57,-20)],
    },
    # UK Shipping Forecast areas — amber
    {
        "name": "Faeroes",
        "category": "UK Shipping Forecast",
        "color": "#B7770D",
        "coords": [(59,-15),(63,-15),(63,0),(59,0)],
    },
    {
        "name": "SE Iceland",
        "category": "UK Shipping Forecast",
        "color": "#B7770D",
        "coords": [(60,-27),(65,-27),(65,-8),(60,-8)],
    },
]

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Hide default Streamlit header/footer */
  #MainMenu, footer, header { visibility: hidden; }

  /* Global font */
  html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }

  /* Top banner */
  .mdsi-banner {
    background: linear-gradient(135deg, #0A2342 0%, #1A3A5C 100%);
    border-radius: 8px;
    padding: 18px 28px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 20px;
  }
  .mdsi-banner h1 {
    color: #ffffff;
    font-size: 1.55rem;
    font-weight: 700;
    margin: 0;
    line-height: 1.2;
  }
  .mdsi-banner p {
    color: #BDD9EF;
    font-size: 0.85rem;
    margin: 4px 0 0 0;
  }

  /* Status pills */
  .status-bar {
    display: flex;
    gap: 10px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .pill {
    border-radius: 20px;
    padding: 6px 16px;
    font-size: 0.8rem;
    font-weight: 600;
    color: #fff;
  }
  .pill-red    { background: #C0392B; }
  .pill-orange { background: #E67E22; }
  .pill-blue   { background: #2980B9; }
  .pill-grey   { background: #7F8C8D; }
  .pill-navy   { background: #0A2342; }

  /* Table row colours */
  .row-red    { background-color: #FADBD8 !important; }
  .row-orange { background-color: #FDEBD0 !important; }
  .row-ice    { background-color: #D6EAF8 !important; }

  /* Section header */
  .section-hdr {
    font-size: 1rem;
    font-weight: 700;
    color: #0A2342;
    border-left: 4px solid #2E86AB;
    padding-left: 10px;
    margin: 18px 0 10px 0;
  }

  /* Source reference list */
  .src-list li { font-size: 0.82rem; margin-bottom: 6px; color: #2C3E50; }
  .src-list a  { color: #2E86AB; }

  /* Confidentiality footer */
  .confid {
    text-align: center;
    font-size: 0.72rem;
    color: #95A5A6;
    border-top: 1px solid #BDC3C7;
    padding-top: 8px;
    margin-top: 30px;
  }
</style>
""", unsafe_allow_html=True)

# ── Auto-refresh every 30 minutes ─────────────────────────────────────────────
_refresh_count = st_autorefresh(interval=30 * 60 * 1000, key="maritime_autorefresh")

# ── Helper functions ──────────────────────────────────────────────────────────
def _clean_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def _centroid_from_geometry(geometry):
    if not geometry:
        return None, None
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    try:
        if gtype == "Point":
            return float(coords[1]), float(coords[0])
        if gtype == "Polygon" and coords:
            ring = coords[0]
            lons, lats = [p[0] for p in ring], [p[1] for p in ring]
            return sum(lats) / len(lats), sum(lons) / len(lons)
        if gtype == "MultiPolygon" and coords:
            all_lons, all_lats = [], []
            for poly in coords:
                for p in poly[0]:
                    all_lons.append(p[0])
                    all_lats.append(p[1])
            if all_lons:
                return sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)
    except (IndexError, TypeError, ZeroDivisionError):
        pass
    return None, None


def _sev_to_color(severity):
    return "red" if (severity or "").lower() in ("extreme", "severe") else "orange"


# ── Data fetchers ─────────────────────────────────────────────────────────────
def _fetch_metno():
    points = [
        ("GL",  70.0, -45.0),   # Greenland
        ("FO",  62.0,  -7.0),   # Faroe Islands
        ("DS",  67.0, -57.0),   # Davis Strait
        ("BB",  73.0, -67.0),   # Baffin Bay
        ("GS",  74.0, -10.0),   # Greenland Sea
        ("NS",  80.0, -68.0),   # Nares Strait
        ("LC",  84.0, -50.0),   # Lincoln Sea
        ("WS",  84.0,  -5.0),   # Wandel Sea
        ("DK",  66.0, -22.0),   # Denmark Strait
        ("IS",  61.0, -33.0),   # Irminger Sea
        ("LS",  57.0, -53.0),   # Labrador Sea
    ]
    events, seen = [], set()
    for code, lat, lon in points:
        try:
            url = (f"https://api.met.no/weatherapi/metalerts/2.0/current.json"
                   f"?lat={lat}&lon={lon}")
            r = requests.get(url, headers=_HEADERS, timeout=20)
            r.raise_for_status()
            for feat in r.json().get("features", []):
                props = feat.get("properties", {})
                alert_id = props.get("id", "")
                if alert_id and alert_id in seen:
                    continue
                if alert_id:
                    seen.add(alert_id)
                geom = feat.get("geometry")
                lat_c, lon_c = _centroid_from_geometry(geom)
                if lat_c is None:
                    lat_c, lon_c = lat, lon
                ev = props.get("event", {})
                name = (ev.get("en") or ev.get("no") or "Weather Alert") if isinstance(ev, dict) else str(ev)
                sev = props.get("severity", "Moderate")
                desc_d = props.get("description", {})
                desc = (desc_d.get("en") or desc_d.get("no") or "") if isinstance(desc_d, dict) else str(desc_d or "")
                area_d = props.get("area", f"{code} Waters")
                area = (area_d.get("en") or area_d.get("no") or f"{code} Waters") if isinstance(area_d, dict) else str(area_d or f"{code} Waters")
                vfrom = (props.get("effective") or "")[:10]
                vto   = (props.get("expires") or "")[:10]
                full  = desc or f"{name} alert for {area}. Severity: {sev}."
                if vfrom:
                    full += f" Valid: {vfrom} – {vto}."
                events.append({
                    "event_id": f"MET-{code}-{str(alert_id)[:8]}",
                    "type": f"Met Advisory – {name.title()}",
                    "area": area,
                    "lat": float(lat_c), "lon": float(lon_c),
                    "status": "ACTIVE", "severity": sev,
                    "description": full,
                    "source": "MET Norway MetAlerts 2.0",
                    "color": _sev_to_color(sev),
                })
        except Exception:
            pass
    return events


def _fetch_navgl():
    events = []
    try:
        r = requests.get("https://eng.navigation.gl/", headers=_HEADERS, timeout=20)
        r.raise_for_status()
        clean = _clean_html(r.text)
        matches = re.findall(
            r"((?:NAVAREA|NtM|Notice to Mariners?)\s*[\w\s/]*?\d{1,3}/\d{2})",
            clean, re.I)
        seen = set()
        for wid in matches[:5]:
            key = wid.strip().upper()
            if key in seen:
                continue
            seen.add(key)
            pos = clean.lower().find(wid.lower())
            snippet = clean[pos: pos + 300].strip() if pos >= 0 else wid
            events.append({
                "event_id": f"NAVGL-{wid.strip()[:15]}",
                "type": "Navigational Warning",
                "area": "Greenland Waters",
                "lat": 68.0, "lon": -45.0,
                "status": "ACTIVE", "severity": "Moderate",
                "description": snippet,
                "source": "Navigation Greenland",
                "color": "red",
            })
    except Exception:
        pass
    return events


def _fetch_ukmo():
    sea_areas = {
        "faeroes":           ("Faeroes",    62.0,  -7.0),
        "southeast iceland": ("SE Iceland", 64.5, -15.0),
    }
    events = []
    try:
        r = requests.get(
            "https://weather.metoffice.gov.uk/specialist-forecasts/"
            "coast-and-sea/shipping-forecast",
            headers=_HEADERS, timeout=30)
        r.raise_for_status()
        clean = _clean_html(r.text)
        for key, (area_name, lat, lon) in sea_areas.items():
            idx = clean.lower().find(key)
            if idx < 0:
                continue
            snippet = clean[idx: idx + 400].strip()
            has_gale = bool(re.search(
                r"gale\s+\d|storm\s+force|gale\s+warning|severe\s+gale",
                snippet, re.I))
            color  = "red" if has_gale else "orange"
            status = "GALE WARNING" if has_gale else "ADVISORY"
            etype  = ("Gale Warning (Shipping Forecast)"
                      if has_gale else "Sea State Advisory (Shipping Forecast)")
            events.append({
                "event_id": f"UKMO-{area_name}",
                "type": etype,
                "area": area_name,
                "lat": float(lat), "lon": float(lon),
                "status": status,
                "severity": "Severe" if has_gale else "Moderate",
                "description": snippet,
                "source": "UK Met Office Shipping Forecast",
                "color": color,
            })
    except Exception:
        pass
    return events


def _fetch_eccc():
    areas = {
        "davis":   ("Davis Strait",  67.0, -57.0),
        "baffin":  ("Baffin Bay",    73.0, -67.0),
        "labrador":("Labrador Sea",  57.0, -53.0),
        "nares":   ("Nares Strait",  80.0, -68.0),
        "lincoln": ("Lincoln Sea",   84.0, -50.0),
    }
    events = []
    try:
        r = requests.get(
            "https://weather.gc.ca/marine/marine_bulletins_e.html",
            headers=_HEADERS, timeout=25)
        r.raise_for_status()
        clean = _clean_html(r.text)
        for key, (area_name, lat, lon) in areas.items():
            idx = clean.lower().find(key)
            if idx < 0:
                continue
            snippet = clean[max(0, idx - 20): idx + 300].strip()
            has_ice  = bool(re.search(r"ice|iceberg|growler", snippet, re.I))
            has_gale = bool(re.search(r"gale|storm\s+force|warning|strong\s+wind", snippet, re.I))
            if has_ice:
                color, etype, status = "ice", f"Ice Advisory ({area_name})", "ICE ADVISORY"
            elif has_gale:
                color, etype, status = "red", f"Marine Warning ({area_name})", "WARNING"
            else:
                color, etype, status = "orange", f"Marine Advisory ({area_name})", "ADVISORY"
            events.append({
                "event_id": f"ECCC-{area_name[:12]}",
                "type": etype,
                "area": area_name,
                "lat": float(lat), "lon": float(lon),
                "status": status,
                "severity": "Severe" if has_gale and not has_ice else "Moderate",
                "description": snippet,
                "source": "Environment Canada / Canadian Ice Service",
                "color": color,
            })
    except Exception:
        pass
    return events


def _snap_to_area(lat, lon, fallback="Other"):
    """Map a coordinate to the first matching sea area polygon (bounding-box test)."""
    for area in SEA_AREA_POLYGONS:
        lats = [c[0] for c in area["coords"]]
        lons = [c[1] for c in area["coords"]]
        if min(lats) <= lat <= max(lats) and min(lons) <= lon <= max(lons):
            return area["name"]
    return fallback


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_all_events():
    """Fetch all live maritime events; cached for 30 minutes."""
    events = []
    events += _fetch_metno()
    events += _fetch_navgl()
    events += _fetch_ukmo()
    events += _fetch_eccc()

    if not events:
        events = [
            {"event_id": "NAVAREA XIX 72/26", "type": "Navigational Warning – Offshore Rigs",
             "area": "Norwegian Sea", "lat": 67.5, "lon": 14.0, "status": "ACTIVE",
             "severity": "Moderate",
             "description": "Seven active offshore drilling rigs with 500 m mandatory safety zones (Transocean Enabler, COSL Prospector, Scarabeo 8, Floatel Endurance, Transocean Norge, Transocean Encourage, Island Innovator). Cancels NAVAREA XIX 57/26.",
             "source": "Cached / fallback", "color": "red"},
            {"event_id": "NAVAREA XIX 45/26", "type": "Navigational Warning – Port Restriction",
             "area": "Norwegian Ports", "lat": 70.5, "lon": 23.0, "status": "ACTIVE",
             "severity": "Moderate",
             "description": "Russian-flagged fishing vessels restricted to Baatsfjord, Kirkenes and Tromsø only. All other Norwegian ports closed. In force since 15 Mar 2026.",
             "source": "Cached / fallback", "color": "orange"},
            {"event_id": "SEA-FAE", "type": "Sea State Advisory",
             "area": "Faroe Islands", "lat": 62.0, "lon": -7.0, "status": "CURRENT",
             "severity": "Moderate",
             "description": "Wave heights forecast peaking at 2.4 m. Water temperature 10.8 °C. No gale warning in force. Monitor conditions before departure.",
             "source": "Cached / fallback", "color": "orange"},
            {"event_id": "ICE-GL", "type": "Ice Advisory – Davis Strait / E Greenland",
             "area": "Davis Strait / East Greenland", "lat": 67.5, "lon": -48.0,
             "status": "SEASONAL ADVISORY", "severity": "Moderate",
             "description": "Seasonal ice advisory for Davis Strait and East Greenland coastal waters. June conditions typically include first-year and remnant multi-year ice. Consult current DMI ice charts before transiting.",
             "source": "Cached / fallback", "color": "ice"},
        ]

    # Snap each event's area to the canonical polygon name
    for i, ev in enumerate(events):
        ev["area"] = _snap_to_area(ev.get("lat", 0), ev.get("lon", 0), fallback=ev.get("area", "Other"))
        ev["#"] = i + 1
    return events, datetime.datetime.utcnow().strftime("%H:%M UTC")


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_mdsi_logo():
    try:
        r = requests.get(
            "https://cdn.prod.website-files.com/674319335c5ccf956071f20f/"
            "674364a8b39a3123f58491a8_1.png",
            headers=_HEADERS, timeout=10)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


# ── Map builder ───────────────────────────────────────────────────────────────
def _hex_rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return [int(h[i:i+2], 16) for i in (0, 2, 4)] + [alpha]


def build_globe(events):
    # ── ESRI World Ocean basemap tile layer
    tile_layer = pdk.Layer(
        "TileLayer",
        data="https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
        min_zoom=0,
        max_zoom=13,
        tile_size=256,
        opacity=1.0,
    )

    # ── Sea area polygons (transparent filled)
    poly_data = []
    for area in SEA_AREA_POLYGONS:
        ring = [[c[1], c[0]] for c in area["coords"]]
        ring.append(ring[0])  # close polygon
        poly_data.append({
            "name": area["name"],
            "coordinates": [ring],
            "fill_color": _hex_rgba(area["color"], 35),
            "line_color": _hex_rgba(area["color"], 170),
        })

    polygon_layer = pdk.Layer(
        "PolygonLayer",
        data=poly_data,
        get_polygon="coordinates",
        get_fill_color="fill_color",
        get_line_color="line_color",
        stroked=True,
        filled=True,
        line_width_min_pixels=1,
        pickable=False,
    )

    # ── Sea area name labels
    label_data = [
        {
            "name": area["name"],
            "position": [
                sum(c[1] for c in area["coords"]) / len(area["coords"]),
                sum(c[0] for c in area["coords"]) / len(area["coords"]),
            ],
            "color": _hex_rgba(area["color"], 255),
        }
        for area in SEA_AREA_POLYGONS
    ]

    text_layer = pdk.Layer(
        "TextLayer",
        data=label_data,
        get_position="position",
        get_text="name",
        get_color="color",
        get_size=13,
        get_weight=700,
        font_family="'Segoe UI', Arial, sans-serif",
        pickable=False,
    )

    # ── Event markers
    ev_data = [
        {
            "lon": ev["lon"],
            "lat": ev["lat"],
            "num": ev["#"],
            "event_id": ev["event_id"],
            "type": ev["type"],
            "area": ev["area"],
            "status": ev["status"],
            "description": ev["description"][:220] + ("…" if len(ev["description"]) > 220 else ""),
            "color": GLOBE_COLORS.get(ev.get("color", "orange"), [230, 126, 34, 230]),
        }
        for ev in events
        if ev.get("lat") is not None and ev.get("lon") is not None
    ]

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=ev_data,
        get_position=["lon", "lat"],
        get_radius=110000,
        get_fill_color="color",
        get_line_color=[255, 255, 255, 200],
        line_width_min_pixels=2,
        stroked=True,
        filled=True,
        pickable=True,
    )

    return pdk.Deck(
        layers=[tile_layer, polygon_layer, text_layer, scatter_layer],
        views=[pdk.View(type="GlobeView", controller=True)],
        initial_view_state=pdk.ViewState(latitude=72.0, longitude=-25.0, zoom=2),
        map_provider=None,
        parameters={"cull": True},
        tooltip={
            "html": (
                "<div style='font-family:Segoe UI,sans-serif;max-width:300px;padding:4px'>"
                "<b style='color:#BDD9EF;font-size:13px'>#{num} {event_id}</b><br/>"
                "<span style='color:#aaa;font-size:11px'>{type}</span>"
                "<hr style='border-color:#1A3A5C;margin:4px 0'/>"
                "<b>Area:</b> {area}<br/>"
                "<b>Status:</b> {status}<br/><br/>"
                "<span style='font-size:11px'>{description}</span>"
                "</div>"
            ),
            "style": {"backgroundColor": "#0A2342", "color": "white", "borderRadius": "6px"},
        },
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
def render_sidebar(events, last_updated):
    with st.sidebar:
        logo_bytes = fetch_mdsi_logo()
        if logo_bytes:
            st.image(logo_bytes, width=220)

        st.markdown("### Maritime Dashboard")
        st.caption("GL & FO Waters — Real-time")
        st.divider()

        st.markdown(f"**Last data refresh:** {last_updated}")
        st.caption("Auto-refreshes every 30 minutes")

        if st.button("🔄 Refresh Now", use_container_width=False):
            fetch_all_events.clear()
            fetch_mdsi_logo.clear()
            st.rerun()

        st.divider()
        st.markdown("#### Filter alerts")

        all_types = sorted({ev["type"].split("–")[0].strip().split("(")[0].strip() for ev in events})
        sel_types = st.multiselect("Alert type", all_types, default=all_types)

        all_areas = [a["name"] for a in SEA_AREA_POLYGONS] + ["Other"]
        sel_areas = st.multiselect("Sea area", all_areas, default=all_areas)

        sev_opts = ["All", "Severe / Extreme only", "Moderate"]
        sel_sev = st.radio("Severity", sev_opts, index=0)

        st.divider()
        st.markdown(
            "<small>FOR OFFICIAL USE — MARITIME SAFETY INFORMATION<br>"
            "© MDSI " + str(datetime.date.today().year) + "</small>",
            unsafe_allow_html=True)

    return sel_types, sel_areas, sel_sev


def apply_filters(events, sel_types, sel_areas, sel_sev):
    filtered = [
        ev for ev in events
        if (ev["type"].split("–")[0].strip().split("(")[0].strip() in sel_types
            and ev["area"] in sel_areas)
    ]
    if sel_sev == "Severe / Extreme only":
        filtered = [ev for ev in filtered if ev["severity"].lower() in ("severe", "extreme")]
    elif sel_sev == "Moderate":
        filtered = [ev for ev in filtered if ev["severity"].lower() not in ("severe", "extreme")]
    return filtered


# ── Main layout ───────────────────────────────────────────────────────────────
def main():
    # ── Fetch data
    with st.spinner("Loading maritime alert data…"):
        try:
            events, last_updated = fetch_all_events()
        except Exception as exc:
            st.error(f"Failed to load alert data: {exc}")
            return

    # ── Sidebar
    sel_types, sel_areas, sel_sev = render_sidebar(events, last_updated)
    filtered = apply_filters(events, sel_types, sel_areas, sel_sev)

    # ── Banner
    logo_bytes = fetch_mdsi_logo()
    logo_b64 = ""
    if logo_bytes:
        import base64
        logo_b64 = base64.b64encode(logo_bytes).decode()

    logo_tag = (
        f'<img src="data:image/png;base64,{logo_b64}" '
        f'style="height:54px;object-fit:contain;background:#fff;'
        f'border-radius:6px;padding:4px 8px;">'
        if logo_b64 else
        '<span style="font-size:2rem">🌊</span>'
    )

    today_label = datetime.date.today().strftime("%d %B %Y")
    st.markdown(f"""
    <div class="mdsi-banner">
      {logo_tag}
      <div>
        <h1>MDSI Maritime Dashboard</h1>
        <p>Greenlandic &amp; Faroe Islands Waters &nbsp;·&nbsp; Davis Strait · Baffin Bay · Greenland Sea &nbsp;·&nbsp; {today_label} &nbsp;·&nbsp; {last_updated}</p>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Status pills
    n_warn = sum(1 for ev in filtered if ev["color"] == "red")
    n_adv  = sum(1 for ev in filtered if ev["color"] == "orange")
    n_ice  = sum(1 for ev in filtered if ev["color"] == "ice")
    n_tot  = len(filtered)
    st.markdown(f"""
    <div class="status-bar">
      <span class="pill pill-navy">{n_tot} total events</span>
      <span class="pill pill-red">🔴 {n_warn} warning{'s' if n_warn != 1 else ''}</span>
      <span class="pill pill-orange">🟠 {n_adv} advisor{'ies' if n_adv != 1 else 'y'}</span>
      <span class="pill pill-blue">🔵 {n_ice} ice advisor{'ies' if n_ice != 1 else 'y'}</span>
      <span class="pill pill-grey" style="margin-left:auto">Updated {last_updated}</span>
    </div>""", unsafe_allow_html=True)

    if not filtered:
        st.info("No events match the current filters.")
        return

    # ── Map
    st.markdown('<div class="section-hdr">Georeferenced Event Map</div>', unsafe_allow_html=True)
    globe = build_globe(filtered)
    st.pydeck_chart(globe, use_container_width=True, height=600)

    # ── Alert table
    st.markdown('<div class="section-hdr">Active Alerts &amp; Events</div>', unsafe_allow_html=True)

    rows = []
    for ev in filtered:
        badge_color = {"red": "#C0392B", "orange": "#E67E22",
                       "ice": "#2980B9", "gold": "#F39C12"}.get(ev["color"], "#7F8C8D")
        rows.append({
            "#": ev["#"],
            "Event ID": ev["event_id"],
            "Type": ev["type"],
            "Area": ev["area"],
            "Status": ev["status"],
            "Severity": ev["severity"],
            "Description": ev["description"],
            "Source": ev["source"],
            "_color": badge_color,
        })

    df = pd.DataFrame(rows)

    # Show as a nicely configured dataframe
    st.dataframe(
        df.drop(columns=["_color"]),
        width="stretch",
        hide_index=True,
        height=400,
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Event ID": st.column_config.TextColumn(width="medium"),
            "Type": st.column_config.TextColumn(width="medium"),
            "Area": st.column_config.TextColumn(width="medium"),
            "Status": st.column_config.TextColumn(width="small"),
            "Severity": st.column_config.TextColumn(width="small"),
            "Description": st.column_config.TextColumn(width="large"),
            "Source": st.column_config.TextColumn(width="medium"),
        },
    )

    # Download button
    csv = df.drop(columns=["_color"]).to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇ Download alerts as CSV",
        data=csv,
        file_name=f"maritime-alerts-{datetime.date.today()}.csv",
        mime="text/csv",
    )

    # ── Data Source References
    st.markdown('<div class="section-hdr">Data Source References</div>', unsafe_allow_html=True)
    src_items = "".join(
        f'<li><a href="{url}" target="_blank">{name}</a> — {desc}</li>'
        for name, url, desc in DATA_SOURCES
    )
    st.markdown(f'<ul class="src-list">{src_items}</ul>', unsafe_allow_html=True)

    # ── Footer
    st.markdown(
        f'<div class="confid">FOR OFFICIAL USE — MARITIME SAFETY INFORMATION &nbsp;|&nbsp; '
        f'MDSI {datetime.date.today().year} &nbsp;|&nbsp; '
        f'Data refreshed automatically every 30 minutes</div>',
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()
