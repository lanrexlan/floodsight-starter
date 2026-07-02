// ---------------------------------------------------------------------------
// FloodSight Dashboard — MapLibre GL JS edition
// 3D interactive map with live alert colors, place search, city-wide LGA view
// Phase 13: expanded from 3-LGA pilot to 15-LGA city-wide coverage
// ---------------------------------------------------------------------------

const isLocalDev =
  window.location.protocol === "file:" ||
  ["localhost", "127.0.0.1"].includes(window.location.hostname);
const API_BASE_URL = isLocalDev ? "http://localhost:8080" : "";

const RISK_COLORS = {
  "Low":       "#2E7D5B",
  "Moderate":  "#D9A441",
  "High":      "#D9622B",
  "Very High": "#C23B3B",
};

// Alert colors override risk colors when forecasts fire
const ALERT_COLORS = {
  "Warning": "#FF4040",
  "Watch":   "#F5A623",
};

// Phase 13: city-wide view — all 15 flood-prone LGAs (lon 3.00–3.80, lat 6.30–6.80)
// Centre on Ikeja/mainland axis; zoom 10 fits ~80 km across, showing the full city.
const PILOT_CENTER  = [3.39, 6.52];   // Lagos geographic centre (Ikeja area)
const PILOT_ZOOM    = 10.5;
const PILOT_PITCH   = 40;
const PILOT_BEARING = -5;

// ---------------------------------------------------------------------------
// Map init — CARTO dark-matter (free, no API key)
// ---------------------------------------------------------------------------
const STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

const map = new maplibregl.Map({
  container: "map",
  style: STYLE_URL,
  center: PILOT_CENTER,
  zoom: PILOT_ZOOM,
  pitch: PILOT_PITCH,
  bearing: PILOT_BEARING,
  antialias: true,
});

map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-right");

// Fade the map-tip after 5 s
setTimeout(() => {
  const tip = document.getElementById("map-tip");
  if (tip) tip.style.opacity = "0";
}, 5000);

// ---------------------------------------------------------------------------
// Risk grid — loaded with live alert colours from /forecast/alerts
// ---------------------------------------------------------------------------
let queryMarker = null;

map.on("load", () => {
  loadForecastGrid();   // live alert colours + auto-populates sliders
});

// ---------------------------------------------------------------------------
// loadForecastGrid — primary loader
//
// Loads /risk/grid (geometry, cached on server) and /forecast/alerts
// (compact alert-level array, no geometry) in parallel, then merges them
// client-side.  This split avoids serialising the full 54 k-cell GeoJSON
// twice per page-load, which was OOM-killing Render's 512 MB free tier.
// ---------------------------------------------------------------------------
async function loadForecastGrid() {
  try {
    const [gridRes, alertRes] = await Promise.all([
      fetch(`${API_BASE_URL}/risk/grid`),
      fetch(`${API_BASE_URL}/forecast/alerts`),
    ]);
    if (!gridRes.ok)  throw new Error(`grid HTTP ${gridRes.status}`);
    if (!alertRes.ok) throw new Error(`alerts HTTP ${alertRes.status}`);

    const geojson    = await gridRes.json();
    const alertData  = await alertRes.json();

    // Merge compact alert_levels into grid features (same order guaranteed)
    const levels = alertData.alert_levels || [];
    (geojson.features || []).forEach((feat, i) => {
      const level = levels[i];
      if (level && level !== "No Alert") {
        feat.properties.alert_level = level;
      }
      // Expose rain values for popup display
      const fc = alertData.forecast || {};
      feat.properties.forecast_rain_24h_mm = fc.rain_24h_mm ?? 0;
      feat.properties.forecast_rain_72h_mm = fc.rain_72h_mm ?? 0;
    });

    // Attach forecast to geojson so updateForecastSliders can read it
    geojson.forecast = alertData.forecast;

    applyGridLayers(geojson);

    if (geojson.forecast) {
      updateForecastSliders(geojson.forecast);
    }

    const counts    = alertData.alert_counts || {};
    const lgaAlerts = alertData.lga_alerts  || {};
    updateCityAlert(counts.Warning || 0, counts.Watch || 0, lgaAlerts);

    showDataSourceBanner(geojson.data_source);
    setApiStatus(true);
    wireMapClick();
  } catch (err) {
    console.warn("Forecast grid unavailable, falling back to static risk grid:", err);
    loadRiskGrid();
    loadForecastRainfall();
  }
}

// ---------------------------------------------------------------------------
// loadRiskGrid — fallback: static risk-class colours, no live alert data
// ---------------------------------------------------------------------------
async function loadRiskGrid() {
  try {
    const res = await fetch(`${API_BASE_URL}/risk/grid`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();

    applyGridLayers(geojson);
    showDataSourceBanner(geojson.data_source);
    setApiStatus(true);
    wireMapClick();
  } catch (err) {
    console.error("Failed to load risk grid:", err);
    setApiStatus(false);
  }
}

// ---------------------------------------------------------------------------
// applyGridLayers — shared layer builder used by both loaders
// Colours: alert_level wins over risk_class when present.
// Warning cells are 50% taller so they stand out at a glance.
// ---------------------------------------------------------------------------
function applyGridLayers(geojson) {
  ["flood-risk-3d", "flood-risk-flat"].forEach(id => {
    if (map.getLayer(id)) map.removeLayer(id);
  });
  if (map.getSource("risk-grid")) map.removeSource("risk-grid");

  map.addSource("risk-grid", { type: "geojson", data: geojson });

  // Colour expression: alert level overrides risk class
  const colorExpr = [
    "case",
    ["==", ["get", "alert_level"], "Warning"], ALERT_COLORS["Warning"],
    ["==", ["get", "alert_level"], "Watch"],   ALERT_COLORS["Watch"],
    // No alert_level property (static grid) or "No Alert" → risk class colour
    ["match", ["get", "risk_class"],
      "Low",       RISK_COLORS["Low"],
      "Moderate",  RISK_COLORS["Moderate"],
      "High",      RISK_COLORS["High"],
      "Very High", RISK_COLORS["Very High"],
      "#555"
    ]
  ];

  // Height: Warning cells 50% taller, Watch cells 15% taller
  const heightExpr = [
    "case",
    ["==", ["get", "alert_level"], "Warning"], ["*", ["get", "flood_score"], 270],
    ["==", ["get", "alert_level"], "Watch"],   ["*", ["get", "flood_score"], 207],
    ["*", ["get", "flood_score"], 180]
  ];

  // 3D extrusion
  map.addLayer({
    id: "flood-risk-3d",
    type: "fill-extrusion",
    source: "risk-grid",
    paint: {
      "fill-extrusion-color":             colorExpr,
      "fill-extrusion-height":            heightExpr,
      "fill-extrusion-base":              0,
      "fill-extrusion-opacity": [
        "interpolate", ["linear"], ["zoom"],
        10, 0.90,
        15, 0.70
      ],
      "fill-extrusion-vertical-gradient": true,
    },
  });

  // Flat fallback for zoomed-out view
  map.addLayer({
    id: "flood-risk-flat",
    type: "fill",
    source: "risk-grid",
    minzoom: 0,
    maxzoom: 10,
    paint: {
      "fill-color":   colorExpr,
      "fill-opacity": 0.60,
    },
  });
}

// ---------------------------------------------------------------------------
// City-wide alert summary — shown above result panel
// ---------------------------------------------------------------------------

// Static fallback area names — used when the API doesn't return lga_alerts
// (e.g. boundary file unavailable on server).  Reflects the known risk
// distribution from the Phase 13 calibration run.
const WATCH_AREAS = "Alimosho, Kosofe, Mushin, Oshodi-Isolo";
const WARN_AREAS  = "Kosofe, Alimosho, Eti-Osa, Lagos Island";

function _lgaText(lgaAlerts, fallback, n) {
  const names = Object.keys(lgaAlerts || {}).slice(0, n);
  return names.length ? names.join(', ') : fallback;
}

function updateCityAlert(warnCount, watchCount, lgaAlerts) {
  const el = document.getElementById("city-alert");
  if (!el) return;

  if (warnCount === 0 && watchCount === 0) {
    el.hidden = true;
    setBeacon("No Alert");
    return;
  }

  el.hidden = false;
  let level, msg;
  if (warnCount > 0) {
    level = "Warning";
    const areas = _lgaText(lgaAlerts, WARN_AREAS, 3);
    msg = `Flood warning — most affected: ${areas}`;
    if (watchCount > 0) msg += ` (+ watch in other areas)`;
  } else {
    level = "Watch";
    const areas = _lgaText(lgaAlerts, WATCH_AREAS, 3);
    msg = `Elevated risk — ${areas} and nearby areas`;
  }
  el.dataset.level = level;
  el.innerHTML = `<strong>${level}</strong> · ${msg}`;
  setBeacon(level);
}

function wireMapClick() {
  map.on("click", "flood-risk-3d", (e) => {
    const coords = e.lngLat;
    queryPoint(coords.lat, coords.lng, null);
  });
  map.on("mouseenter", "flood-risk-3d", () => {
    map.getCanvas().style.cursor = "crosshair";
  });
  map.on("mouseleave", "flood-risk-3d", () => {
    map.getCanvas().style.cursor = "";
  });
  map.on("click", (e) => {
    const features = map.queryRenderedFeatures(e.point, { layers: ["flood-risk-3d"] });
    if (features.length === 0) queryPoint(e.lngLat.lat, e.lngLat.lng, null);
  });
}

// ---------------------------------------------------------------------------
// Reverse geocode — lat/lon → human area name
// ---------------------------------------------------------------------------
async function reverseGeocode(lat, lon) {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=14&accept-language=en`;
    const res = await fetch(url, { headers: { "User-Agent": "FloodSight-Dashboard/1.0" } });
    const data = await res.json();
    const a = data.address || {};
    return (
      a.neighbourhood || a.suburb || a.city_district ||
      a.town || a.village || a.county ||
      data.display_name?.split(",")[0] || null
    );
  } catch { return null; }
}

// ---------------------------------------------------------------------------
// Query point — risk + alert for clicked/searched location
// ---------------------------------------------------------------------------
async function queryPoint(lat, lon, locationName) {
  const rain24 = Number(document.getElementById("rain24").value);
  const rain72 = Number(document.getElementById("rain72").value);

  if (!locationName) locationName = await reverseGeocode(lat, lon);

  try {
    const [riskRes, alertRes] = await Promise.all([
      fetch(`${API_BASE_URL}/risk/point?lat=${lat}&lon=${lon}`),
      fetch(`${API_BASE_URL}/alerts/current`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat, lon, rain_24h_mm: rain24, rain_72h_mm: rain72 }),
      }),
    ]);
    if (!riskRes.ok || !alertRes.ok) throw new Error("API error");
    const risk  = await riskRes.json();
    const alert = await alertRes.json();

    const panel = document.getElementById("result-panel");
    panel.hidden = false;

    document.getElementById("result-location").textContent =
      locationName || `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;

    document.getElementById("result-risk").textContent  = risk.risk_class;
    document.getElementById("result-risk").style.color  = RISK_COLORS[risk.risk_class] || "#fff";
    document.getElementById("result-alert").textContent = alert.alert_level;
    document.getElementById("result-alert").style.color = alertResultColor(alert.alert_level);
    document.getElementById("result-elev").textContent  = `${risk.elevation_m.toFixed(1)} m`;
    document.getElementById("result-score").textContent = risk.flood_score.toFixed(3);

    const nudge      = document.getElementById("alert-nudge");
    const isHighRisk = ["High", "Very High"].includes(risk.risk_class);
    if (alert.alert_level === "No Alert" && isHighRisk) {
      nudge.hidden = false;
      nudge.textContent = `⚠ ${risk.risk_class} risk — slide 24h rainfall above 50 mm for Watch, 100 mm for Warning.`;
    } else {
      nudge.hidden = true;
    }

    setBeacon(alert.alert_level);

    if (queryMarker) queryMarker.remove();
    const el = document.createElement("div");
    el.className = "query-dot";
    el.style.background =
      ALERT_COLORS[alert.alert_level] || RISK_COLORS[risk.risk_class] || "#888";
    queryMarker = new maplibregl.Marker({ element: el, anchor: "center" })
      .setLngLat([lon, lat])
      .setPopup(
        new maplibregl.Popup({ offset: 14, className: "fs-popup" }).setHTML(
          `<strong>${risk.risk_class} risk</strong><br/>
           Alert: <em>${alert.alert_level}</em><br/>
           Elev: ${risk.elevation_m.toFixed(1)} m &nbsp;|&nbsp; Score: ${risk.flood_score.toFixed(3)}`
        )
      )
      .addTo(map);
    queryMarker.getPopup().addTo(map);

    setApiStatus(true);
  } catch (err) {
    console.error("Query failed:", err);
    setApiStatus(false);
  }
}

function alertResultColor(level) {
  return level === "Warning" ? "#FF4040" : level === "Watch" ? "#F5A623" : "#2E7D5B";
}

// ---------------------------------------------------------------------------
// Place search — Nominatim
// ---------------------------------------------------------------------------
const searchInput   = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const searchClear   = document.getElementById("search-clear");
let searchTimer = null;

searchInput.addEventListener("input", () => {
  const q = searchInput.value.trim();
  searchClear.hidden = q.length === 0;
  clearTimeout(searchTimer);
  if (q.length < 2) { hideDropdown(); return; }
  searchTimer = setTimeout(() => doSearch(q), 320);
});
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { hideDropdown(); searchInput.blur(); }
});
searchClear.addEventListener("click", () => {
  searchInput.value = "";
  searchClear.hidden = true;
  hideDropdown();
  searchInput.focus();
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-wrap") && !e.target.closest(".search-dropdown")) hideDropdown();
});

async function doSearch(query) {
  try {
    const url = `https://nominatim.openstreetmap.org/search?` +
      `q=${encodeURIComponent(query + ", Lagos, Nigeria")}` +
      `&format=json&limit=7&accept-language=en` +
      `&viewbox=3.05,6.75,3.80,6.30&bounded=0`;
    const res = await fetch(url, {
      headers: { "User-Agent": "FloodSight-Dashboard/1.0 (flood intelligence, Lagos)" },
    });
    renderDropdown(await res.json());
  } catch (err) { console.error("Search failed:", err); hideDropdown(); }
}

function renderDropdown(items) {
  if (!items || items.length === 0) {
    searchResults.innerHTML = `<li class="no-result">No places found in Lagos</li>`;
    searchResults.hidden = false;
    return;
  }
  searchResults.innerHTML = items.map((item, i) => {
    const name = item.display_name.split(",").slice(0, 3).join(", ");
    return `<li class="result-item" data-idx="${i}" data-lat="${item.lat}" data-lon="${item.lon}" data-name="${encodeURIComponent(name)}">
      <svg class="result-pin" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="6" r="3"/><path d="M8 2C5.24 2 3 4.24 3 7c0 3.75 5 9 5 9s5-5.25 5-9c0-2.76-2.24-5-5-5z"/></svg>
      <span>${name}</span>
    </li>`;
  }).join("");
  searchResults.hidden = false;
  searchResults.querySelectorAll(".result-item").forEach(li => {
    li.addEventListener("click", () => {
      selectPlace(parseFloat(li.dataset.lat), parseFloat(li.dataset.lon), decodeURIComponent(li.dataset.name));
    });
  });
}

function selectPlace(lat, lon, name) {
  hideDropdown();
  searchInput.value = name.split(",")[0];
  searchClear.hidden = false;
  map.flyTo({ center: [lon, lat], zoom: 15, pitch: PILOT_PITCH, bearing: PILOT_BEARING, duration: 1400, essential: true });
  queryPoint(lat, lon, name);
}
function hideDropdown() { searchResults.hidden = true; searchResults.innerHTML = ""; }

// ---------------------------------------------------------------------------
// LGA quick-jump buttons
// ---------------------------------------------------------------------------
document.querySelectorAll(".lga-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const lat  = parseFloat(btn.dataset.lat);
    const lon  = parseFloat(btn.dataset.lon);
    const zoom = parseFloat(btn.dataset.zoom);
    map.flyTo({ center: [lon, lat], zoom, pitch: PILOT_PITCH, bearing: PILOT_BEARING, duration: 1200, essential: true });
    queryPoint(lat, lon, btn.textContent.trim());
  });
});

// ---------------------------------------------------------------------------
// Rainfall sliders
// ---------------------------------------------------------------------------
const rain24Input = document.getElementById("rain24");
const rain72Input = document.getElementById("rain72");

rain24Input.addEventListener("input", () => {
  document.getElementById("rain24-val").textContent = `${rain24Input.value} mm`;
  markManual();
});
rain72Input.addEventListener("input", () => {
  document.getElementById("rain72-val").textContent = `${rain72Input.value} mm`;
  markManual();
});

function markManual() {
  const badge = document.getElementById("forecast-badge");
  if (badge) badge.dataset.manual = "true";
  const hint = document.getElementById("rainfall-hint");
  if (hint) hint.textContent = "Scenario mode — drag sliders to simulate storm events.";
}

// ---------------------------------------------------------------------------
// Forecast slider auto-population (used by loadForecastGrid)
// Phase 11: dual-stream — observed (past 24h) + forecast (next 72h)
//   rain24 slider = forecast_24h (what's COMING in next 24h)
//   rain72 slider = observed_24h + forecast_48h (true 72h risk window)
// ---------------------------------------------------------------------------
function updateForecastSliders(forecast) {
  const obs24 = Math.round(forecast.observed_24h_mm ?? 0);
  const fc24  = Math.round(forecast.forecast_24h_mm ?? forecast.rain_24h_mm ?? 0);
  const r24   = Math.min(fc24, 200);
  const r72   = Math.min(Math.round(forecast.rain_72h_mm), 300);

  rain24Input.value = r24;
  rain72Input.value = r72;
  document.getElementById("rain24-val").textContent = `${r24} mm`;
  document.getElementById("rain72-val").textContent = `${r72} mm`;

  const badge = document.getElementById("forecast-badge");
  if (badge) {
    badge.hidden = false;
    const fetchedAt = new Date(forecast.fetched_at);
    const localTime = fetchedAt.toLocaleTimeString("en-NG", {
      hour: "2-digit", minute: "2-digit", timeZone: "Africa/Lagos",
    });

    if (forecast.data_mode === "observed+forecast") {
      // Phase 11 dual-stream badge
      badge.innerHTML =
        `🛰 Dual-stream · ${localTime} Lagos time` +
        `<br><small style="opacity:0.75;">Observed: ${obs24} mm &nbsp;·&nbsp; Forecast: ${fc24} mm (24 h)</small>`;
    } else {
      badge.textContent = `🌧 Live forecast · updated ${localTime}`;
    }
    delete badge.dataset.manual;
  }

  const hint = document.getElementById("rainfall-hint");
  if (hint) {
    hint.textContent = forecast.data_mode === "observed+forecast"
      ? "72h slider = past 24h observed + next 48h forecast. Drag to simulate scenarios."
      : "Sliders set to today's forecast. Drag to simulate scenarios.";
  }
}

// Standalone fallback — called if forecast grid itself fails
async function loadForecastRainfall() {
  try {
    const res = await fetch(`${API_BASE_URL}/forecast/rainfall`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    updateForecastSliders(await res.json());
  } catch {
    rain24Input.value = 40;
    rain72Input.value = 60;
    document.getElementById("rain24-val").textContent = "40 mm";
    document.getElementById("rain72-val").textContent = "60 mm";
    const hint = document.getElementById("rainfall-hint");
    if (hint) hint.textContent = "Forecast unavailable — drag sliders to simulate a storm event.";
  }
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------
function showDataSourceBanner(source) {
  const banner = document.getElementById("data-source-banner");
  if (source === "synthetic_demo") {
    banner.hidden = false;
    banner.textContent = "Showing SYNTHETIC demo grid — run scripts/02-04 to serve real Lagos data.";
  } else {
    banner.hidden = true;
  }
}

function setApiStatus(ok) {
  const el = document.getElementById("api-status");
  el.classList.toggle("ok", ok);
  el.classList.toggle("err", !ok);
  el.textContent = ok
    ? `API connected · ${API_BASE_URL || window.location.host}`
    : `Cannot reach API at ${API_BASE_URL}`;
}

function setBeacon(level) {
  document.getElementById("beacon").dataset.level = level;
}

// ---------------------------------------------------------------------------
// Phase 15 — Street-level flood risk layer
// Lazy-loaded when the user first zooms to ≥ 13 (street scale).
// Each road segment is coloured by its static risk_class (inherited from the
// nearest grid cell).  Arterial roads are always shown; high-risk residential
// roads are included too.
// ---------------------------------------------------------------------------

const STREETS_MIN_ZOOM = 13;
let _streetsLoaded = false;    // guard: fetch exactly once
let _streetsVisible = true;    // toggle state

// Street risk class → line colour (same palette as the grid)
function _streetColor(riskClass) {
  return RISK_COLORS[riskClass] || "#888";
}

// Kick off lazy load the first time the user zooms to street level
map.on("zoom", () => {
  if (!_streetsLoaded && map.getZoom() >= STREETS_MIN_ZOOM) {
    _streetsLoaded = true;   // set before fetch to prevent double-fire
    _loadStreetsLayer();
  }
});

async function _loadStreetsLayer() {
  try {
    const res = await fetch(`${API_BASE_URL}/risk/streets`);
    if (!res.ok) {
      // 404 = script hasn't been run yet — silently skip, don't spam console
      if (res.status !== 404) console.warn("Streets layer HTTP", res.status);
      return;
    }
    const geojson = await res.json();

    if (map.getSource("street-risk")) return; // already added (shouldn't happen)

    map.addSource("street-risk", { type: "geojson", data: geojson });

    // Line width varies by road class — major roads wider
    const widthExpr = [
      "match", ["get", "highway"],
      "motorway",       5,
      "motorway_link",  4,
      "trunk",          4,
      "trunk_link",     3,
      "primary",        3,
      "primary_link",   2.5,
      "secondary",      2.5,
      "secondary_link", 2,
      "tertiary",       2,
      "tertiary_link",  1.5,
      /* residential / unclassified / etc. */ 1.5
    ];

    map.addLayer({
      id: "street-risk-lines",
      type: "line",
      source: "street-risk",
      minzoom: STREETS_MIN_ZOOM,
      layout: {
        "line-cap":  "round",
        "line-join": "round",
      },
      paint: {
        "line-color": [
          "match", ["get", "risk_class"],
          "Very High", RISK_COLORS["Very High"],
          "High",      RISK_COLORS["High"],
          "Moderate",  RISK_COLORS["Moderate"],
          /* Low / unknown */ RISK_COLORS["Low"]
        ],
        "line-width":   widthExpr,
        "line-opacity": 0.85,
      },
    });

    // Click popup — road name + risk
    map.on("click", "street-risk-lines", (e) => {
      const p    = e.features[0].properties;
      const name = p.name && p.name !== "" ? p.name : "Unnamed road";
      const rc   = p.risk_class || "Unknown";
      new maplibregl.Popup({ className: "fs-popup", closeButton: false })
        .setLngLat(e.lngLat)
        .setHTML(
          `<strong>${name}</strong><br>` +
          `Type: ${p.highway}<br>` +
          `Flood risk: <span style="color:${_streetColor(rc)};font-weight:600">${rc}</span>`
        )
        .addTo(map);
    });
    map.on("mouseenter", "street-risk-lines", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "street-risk-lines", () => {
      map.getCanvas().style.cursor = "";
    });

    // Show the toggle button now the layer is live
    const toggleBtn = document.getElementById("streets-toggle");
    if (toggleBtn) toggleBtn.hidden = false;

    console.log(
      `Streets layer loaded — ${(geojson.features || []).length} segments`
    );
  } catch (err) {
    console.warn("Streets layer failed to load:", err);
  }
}

// Toggle button handler (button defined in index.html)
function toggleStreetsLayer() {
  const layer = "street-risk-lines";
  if (!map.getLayer(layer)) return;
  _streetsVisible = !_streetsVisible;
  map.setLayoutProperty(layer, "visibility", _streetsVisible ? "visible" : "none");
  const btn = document.getElementById("streets-toggle");
  if (btn) btn.textContent = _streetsVisible ? "Hide streets" : "Show streets";
}

// ---------------------------------------------------------------------------
// SWMM flood layer — junction overflow points from 150 mm design storm
// Colour-coded by severity: Severe (red) / Moderate (amber) / Nuisance (yellow)
// Pulsing outer ring on Severe nodes highlights highest-risk locations.
// ---------------------------------------------------------------------------
const SWMM_MIN_ZOOM = 11;   // visible from LGA level
let _swmmLoaded    = false;
let _swmmVisible   = true;

// Load once when map is ready (not lazy — it's a small point file)
map.on("load", () => {
  _loadSwmmLayer();
});

async function _loadSwmmLayer() {
  try {
    const res = await fetch(`${API_BASE_URL}/risk/swmm-flooding`);
    if (!res.ok) {
      if (res.status !== 404) console.warn("SWMM flooding layer HTTP", res.status);
      return;
    }
    const geojson = await res.json();
    _swmmLoaded = true;

    map.addSource("swmm-flooding", { type: "geojson", data: geojson });

    // Outer glow ring — Severe nodes only; gives a pulsing effect via CSS animation
    map.addLayer({
      id: "swmm-flood-glow",
      type: "circle",
      source: "swmm-flooding",
      minzoom: SWMM_MIN_ZOOM,
      filter: ["==", ["get", "flood_class"], "Severe"],
      paint: {
        "circle-radius":       10,
        "circle-color":        "#C62828",
        "circle-opacity":      0.25,
        "circle-stroke-width": 0,
      },
    });

    // Core dot — all nodes, coloured by flood_class
    map.addLayer({
      id: "swmm-flood-dots",
      type: "circle",
      source: "swmm-flooding",
      minzoom: SWMM_MIN_ZOOM,
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          11, 3,
          14, 6,
          17, 10,
        ],
        "circle-color": ["get", "colour"],
        "circle-opacity": 0.9,
        "circle-stroke-color": "rgba(0,0,0,0.55)",
        "circle-stroke-width": 1,
      },
    });

    // Click popup
    map.on("click", "swmm-flood-dots", (e) => {
      const p = e.features[0].properties;
      const colHex = p.colour || "#888";
      new maplibregl.Popup({ className: "fs-popup", closeButton: false })
        .setLngLat(e.lngLat)
        .setHTML(
          `<strong>${p.node_id}</strong><br>` +
          `Severity: <span style="color:${colHex};font-weight:600">${p.flood_class}</span><br>` +
          `Peak rate: ${p.max_rate_cms} m³/s<br>` +
          `Hours flooded: ${p.hours_flooded} h<br>` +
          `Total volume: ${p.total_vol_10e6l} × 10⁶ L<br>` +
          `Elevation: ${p.elevation_m} m`
        )
        .addTo(map);
    });
    map.on("mouseenter", "swmm-flood-dots", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "swmm-flood-dots", () => {
      map.getCanvas().style.cursor = "";
    });

    // Show toggle button
    const toggleBtn = document.getElementById("swmm-toggle");
    if (toggleBtn) toggleBtn.hidden = false;

    const meta = geojson.metadata || {};
    const counts = meta.severity_counts || {};
    console.log(
      `SWMM flooding layer loaded — ` +
      `${(geojson.features || []).length} nodes ` +
      `(Severe: ${counts.Severe || 0}, ` +
      `Moderate: ${counts.Moderate || 0}, ` +
      `Nuisance: ${counts.Nuisance || 0})`
    );
  } catch (err) {
    console.warn("SWMM flooding layer failed to load:", err);
  }
}

// ── SMS Alert Subscription (dashboard panel) ──────────────────────────────

async function _loadSubCount() {
  try {
    const res  = await fetch(`${API_BASE_URL}/subscribers/count`);
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById("sub-count-badge");
    if (badge) {
      const n = data.active_subscribers || 0;
      badge.textContent = `${n} subscriber${n !== 1 ? "s" : ""}`;
    }
  } catch (_) {}
}

function dashSubCheck() {
  const phone = (document.getElementById("dash-sub-phone")?.value || "").trim();
  const btn   = document.getElementById("dash-sub-btn");
  if (!btn) return;
  const ready = phone.length >= 7;
  btn.disabled      = !ready;
  btn.style.cursor  = ready ? "pointer"  : "not-allowed";
  btn.style.opacity = ready ? "1"        : "0.5";
}

async function dashSubscribe() {
  const phoneEl  = document.getElementById("dash-sub-phone");
  const areaEl   = document.getElementById("dash-sub-area");
  const statusEl = document.getElementById("dash-sub-status");
  const btn      = document.getElementById("dash-sub-btn");
  if (!phoneEl || !statusEl) return;

  const phone    = phoneEl.value.trim();
  const areaName = areaEl?.value.trim() || null;
  if (!phone) return;

  // Use current map centre as the subscriber's location
  const centre = map.getCenter();
  const lat    = parseFloat(centre.lat.toFixed(5));
  const lon    = parseFloat(centre.lng.toFixed(5));

  btn.disabled    = true;
  btn.textContent = "Subscribing…";
  statusEl.style.color = "#90CAF9";
  statusEl.textContent = "";

  try {
    const res = await fetch(`${API_BASE_URL}/subscribe`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ phone, lat, lon, area_name: areaName || undefined }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    statusEl.style.color = "#81C784";
    statusEl.textContent = `✓ Subscribed — ${data.risk_class || "?"} risk area`;
    phoneEl.value = "";
    if (areaEl) areaEl.value = "";
    await _loadSubCount();
  } catch (err) {
    statusEl.style.color = "#EF9A9A";
    statusEl.textContent = `✗ ${err.message}`;
  } finally {
    btn.disabled    = false;
    btn.textContent = "Subscribe";
    dashSubCheck();
  }
}

// Load subscriber count on page load (after map init)
map.on("load", _loadSubCount);

// ── Toggle SWMM layer visibility ──────────────────────────────────────────
function toggleSwmmLayer() {
  if (!_swmmLoaded) return;
  _swmmVisible = !_swmmVisible;
  const vis = _swmmVisible ? "visible" : "none";
  ["swmm-flood-glow", "swmm-flood-dots"].forEach(id => {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
  });
  const btn = document.getElementById("swmm-toggle");
  if (btn) btn.textContent = _swmmVisible ? "Hide SWMM flood" : "Show SWMM flood";
}
