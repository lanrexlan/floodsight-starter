// ---------------------------------------------------------------------------
// FloodSight Dashboard — MapLibre GL JS edition
// 3D interactive map with live alert colors, place search, city-wide LGA view
// Phase 13: expanded from 3-LGA pilot to 15-LGA city-wide coverage
// ---------------------------------------------------------------------------

const isLocalDev =
  window.location.protocol === "file:" ||
  ["localhost", "127.0.0.1"].includes(window.location.hostname);
const API_BASE_URL = window.location.protocol === "file:" ? "http://localhost:8000" : "";

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
}

const RISK_COLORS = {
  "Low":       "#2E7D5B",
  "Moderate":  "#D9A441",
  "High":      "#D9622B",
  "Very High": "#C23B3B",
};

// ---------------------------------------------------------------------------
// Client-side alert engine — mirrors floodsight/alerts/engine.py exactly.
// Used to re-color the map in real time when the user drags the sliders
// without a round-trip to the server.
// ---------------------------------------------------------------------------
const ALERT_THRESHOLDS = {
  WARNING_24H:   80,   // RAIN_WARNING_24H_MM
  WARNING_72H:  100,   // RAIN_WARNING_72H_MM
  WATCH_HIGH_24H: 20,  // RAIN_WATCH_HIGH_24H_MM
  WATCH_HIGH_72H: 30,  // RAIN_WATCH_HIGH_72H_MM
  WATCH_MOD_24H:  70,  // RAIN_WATCH_MODERATE_24H_MM
  WATCH_MOD_72H: 100,  // RAIN_WATCH_MODERATE_72H_MM
};

function computeAlertLevel(riskClass, rain24, rain72) {
  const high = riskClass === "High" || riskClass === "Very High";
  if (high && (rain24 >= ALERT_THRESHOLDS.WARNING_24H || rain72 >= ALERT_THRESHOLDS.WARNING_72H))
    return "Warning";
  if (high && (rain24 >= ALERT_THRESHOLDS.WATCH_HIGH_24H || rain72 >= ALERT_THRESHOLDS.WATCH_HIGH_72H))
    return "Watch";
  if (riskClass === "Moderate" && (rain24 >= ALERT_THRESHOLDS.WATCH_MOD_24H || rain72 >= ALERT_THRESHOLDS.WATCH_MOD_72H))
    return "Watch";
  return "No Alert";
}

function applySliderAlerts() {
  if (!_cachedGeojson) return;
  const rain24 = Number(document.getElementById("rain24").value);
  const rain72 = Number(document.getElementById("rain72").value);
  let warn = 0, watch = 0;
  _cachedGeojson.features.forEach(feat => {
    const level = computeAlertLevel(feat.properties.risk_class, rain24, rain72);
    feat.properties.forecast_rain_24h_mm = rain24;
    feat.properties.forecast_rain_72h_mm = rain72;
    if (level !== "No Alert") { feat.properties.alert_level = level; }
    else { delete feat.properties.alert_level; }
    if (level === "Warning") warn++;
    else if (level === "Watch") watch++;
  });
  map.getSource("risk-grid")?.setData(_cachedGeojson);
  updateCityAlert(warn, watch, {});
  const banner = document.getElementById("city-alert");
  banner.hidden = false;
  banner.textContent = `Scenario only · ${warn} Warning cells · ${watch} Watch cells. Not a live warning.`;
}

// ---------------------------------------------------------------------------
// Auto-refresh — re-fetch /forecast/alerts every 30 min without reloading
// the page or re-fetching the heavy /risk/grid geometry.
// ---------------------------------------------------------------------------
const REFRESH_INTERVAL_MS = 30 * 60 * 1000;
let _nextRefreshAt  = null;
let _countdownTimer = null;
let _cachedGeojson  = null;   // geometry cached after first load
let _liveAlerts = null;
let _scenarioMode = false;
let _refreshing = false;
let _configReady = false;
let _forecastStale = false;

function showMapMode() {
  document.getElementById("map-mode").textContent = _scenarioMode
    ? "SCENARIO map — hypothetical rainfall, not a live warning."
    : _liveAlerts ? (_forecastStale ? "STALE forecast map — freshness not confirmed. Check the status below." : "Live forecast alert map — check the update time below.")
    : "STATIC susceptibility map — no live alert information.";
  document.getElementById("reset-forecast").hidden = !_scenarioMode;
}

function applyLiveAlerts(data) {
  if (!_cachedGeojson || !Array.isArray(data.alert_levels) ||
      data.alert_levels.length !== _cachedGeojson.features.length ||
      data.alert_levels.some(level => !["No Alert", "Watch", "Warning"].includes(level))) {
    throw new Error("Grid/alert data do not match; refusing partial map update");
  }
  if (!data.forecast || !['rain_24h_mm', 'rain_72h_mm'].every(key =>
      Number.isFinite(data.forecast[key]) && data.forecast[key] >= 0)) {
    throw new Error('Forecast rainfall unavailable; refusing live alert display');
  }
  _liveAlerts = data;
  if (_scenarioMode) { applySliderAlerts(); showMapMode(); return; }
  _cachedGeojson.features.forEach((feat, i) => {
    feat.properties.alert_level = data.alert_levels[i];
    feat.properties.forecast_rain_24h_mm = data.forecast?.rain_24h_mm;
    feat.properties.forecast_rain_72h_mm = data.forecast?.rain_72h_mm;
  });
  map.getSource("risk-grid")?.setData(_cachedGeojson);
  if (data.forecast) updateForecastSliders(data.forecast);
  updateCityAlert(data.alert_levels.filter(level => level === 'Warning').length,
    data.alert_levels.filter(level => level === 'Watch').length, data.lga_alerts || {});
  showMapMode();
}

document.getElementById("reset-forecast").addEventListener("click", () => {
  _scenarioMode = false;
  if (_liveAlerts) applyLiveAlerts(_liveAlerts);
  else {
    _cachedGeojson?.features.forEach(feat => delete feat.properties.alert_level);
    if (_cachedGeojson) map.getSource('risk-grid')?.setData(_cachedGeojson);
    document.getElementById('city-alert').textContent = 'Live alerts unavailable — static susceptibility only.';
    setBeacon('Unavailable'); showMapMode();
  }
  invalidatePointResult();
});

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
  window.floodsightMapReady = true;
  document.getElementById("refresh-forecast").disabled = false;
  loadForecastGrid();   // live alert colours + auto-populates sliders

  // Re-fetch alerts every 30 min without touching the heavy grid geometry
  setInterval(refreshAlerts, REFRESH_INTERVAL_MS);

  // Click the status bar to refresh immediately
  document.getElementById("refresh-forecast").addEventListener("click", refreshAlerts);
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
    await syncProductConfig();
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
    if (levels.length !== geojson.features.length) throw new Error("Grid/alert mismatch");
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

    _cachedGeojson = geojson;   // cache for lightweight alert refreshes
    applyGridLayers(geojson);
    applyLiveAlerts(alertData);

    _forecastStale = false;
    showMapMode();
    showDataSourceBanner(geojson.data_source);
    setApiStatus(true, alertData.forecast?.fetched_at);
    wireMapClick();
  } catch (err) {
    console.warn("Forecast grid unavailable, falling back to static risk grid:", err);
    await loadRiskGrid();
    if (!_scenarioMode) await loadForecastRainfall();
  }
}

async function syncProductConfig() {
  const response = await fetch(`${API_BASE_URL}/product-status`);
  if (!response.ok) throw new Error("Product configuration unavailable");
  const config = await response.json();
  if (!config.alert_thresholds || !config.risk_breaks) throw new Error('Incomplete product configuration');
  Object.assign(ALERT_THRESHOLDS, config.alert_thresholds);
  document.querySelectorAll('.legend li').forEach(li => {
    const label = li.querySelector('strong')?.textContent;
    const range = config.risk_breaks[label];
    if (range) li.querySelector('.legend-hint').textContent = `${range[0]} – ${Math.min(1, range[1])} susceptibility score`;
  });
  const depthButton = document.getElementById('ml-depth-toggle');
  if (depthButton) depthButton.hidden = !config.experimental_depth_enabled;
  document.getElementById('depth-description').parentElement.hidden = !config.experimental_depth_enabled;
  _configReady = true;
  document.getElementById('rain24').disabled = false;
  document.getElementById('rain72').disabled = false;
}

// ---------------------------------------------------------------------------
// loadRiskGrid — fallback: static risk-class colours, no live alert data
// ---------------------------------------------------------------------------
async function loadRiskGrid() {
  try {
    const res = await fetch(`${API_BASE_URL}/risk/grid`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();

    _cachedGeojson = geojson;   // cache so sliders work on fallback path too
    applyGridLayers(geojson);
    _liveAlerts = null;
    showMapMode();
    const banner = document.getElementById("city-alert");
    banner.hidden = false;
    banner.textContent = "Live alerts unavailable — showing static susceptibility, not a current flood warning.";
    setBeacon("Unavailable");
    showDataSourceBanner(geojson.data_source);
    setApiStatus(true);
    wireMapClick();
  } catch (err) {
    console.error("Failed to load risk grid:", err);
    setApiStatus(false);
  }
}

// ---------------------------------------------------------------------------
// refreshAlerts — lightweight re-fetch of /forecast/alerts only.
// Re-colors the existing map geometry without re-downloading the 54 k-cell
// grid GeoJSON.  Called on 30-min timer and on manual status-bar click.
// ---------------------------------------------------------------------------
async function refreshAlerts() {
  if (_refreshing) return;
  _refreshing = true;
  document.getElementById("refresh-forecast").disabled = true;
  const statusEl = document.getElementById("api-status");
  clearInterval(_countdownTimer);
  statusEl.textContent = "Refreshing…";
  try {
    const alertRes = await fetch(`${API_BASE_URL}/forecast/alerts`);
    if (!alertRes.ok) throw new Error(`HTTP ${alertRes.status}`);
    const alertData = await alertRes.json();

    if (!_configReady) await syncProductConfig();
    if (!_cachedGeojson) { await loadForecastGrid(); return; }
    applyLiveAlerts(alertData);
    _forecastStale = false;
    showMapMode();

    setApiStatus(true, alertData.forecast?.fetched_at);
  } catch (err) {
    console.warn("Alert refresh failed:", err);
    statusEl.classList.remove("ok");
    _forecastStale = true;
    statusEl.classList.add("err");
    statusEl.textContent = "Refresh failed — displayed forecast may be stale. Use Refresh forecast to retry.";
    if (!_scenarioMode) document.getElementById("map-mode").textContent = "STALE forecast map — not confirmed current. Refresh failed.";
  } finally {
    _refreshing = false;
    document.getElementById("refresh-forecast").disabled = false;
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
    ["==", ["get", "alert_level"], "Warning"], ["*", ["coalesce", ["get", "hazard_score"], ["get", "flood_score"]], 270],
    ["==", ["get", "alert_level"], "Watch"],   ["*", ["coalesce", ["get", "hazard_score"], ["get", "flood_score"]], 207],
    ["*", ["coalesce", ["get", "hazard_score"], ["get", "flood_score"]], 180]
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
const WATCH_AREAS = "mapped areas (area breakdown unavailable)";
const WARN_AREAS  = "mapped areas (area breakdown unavailable)";

function _lgaText(lgaAlerts, fallback, n) {
  const names = Object.keys(lgaAlerts || {}).slice(0, n);
  return names.length ? names.join(', ') : fallback;
}

function updateCityAlert(warnCount, watchCount, lgaAlerts) {
  const el = document.getElementById("city-alert");
  if (!el) return;

  if (warnCount === 0 && watchCount === 0) {
    el.hidden = false;
    el.textContent = 'No current rule alert — flooding is still possible. This is not an all-clear.';
    el.dataset.level = 'No Alert';
    setBeacon("No Alert");
    return;
  }

  el.hidden = false;
  let level, msg;
  if (warnCount > 0) {
    level = "Warning";
    const areas = _lgaText(lgaAlerts, WARN_AREAS, 3);
    msg = `Forecast rule warning — ${areas}`;
    if (watchCount > 0) msg += ` (+ watch in other areas)`;
  } else {
    level = "Watch";
    const areas = _lgaText(lgaAlerts, WATCH_AREAS, 3);
    msg = `Elevated risk — ${areas} and nearby areas`;
  }
  el.dataset.level = level;
  el.textContent = `${level} · ${msg}`;
  setBeacon(level);
}

let mapClickWired = false;
function wireMapClick() {
  if (mapClickWired) return;
  mapClickWired = true;
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
    const url = `${API_BASE_URL}/places/reverse?lat=${lat}&lon=${lon}`;
    const res = await fetch(url);
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
let _pointRequest = 0;
function invalidatePointResult() {
  _pointRequest++;
  document.getElementById("result-panel").hidden = true;
  document.getElementById("result-panel").setAttribute("aria-busy", "false");
  document.getElementById("alert-nudge").hidden = true;
  if (queryMarker) queryMarker.remove();
}

async function queryPoint(lat, lon, locationName) {
  const request = ++_pointRequest;
  const panel = document.getElementById("result-panel");
  panel.hidden = false;
  panel.setAttribute("aria-busy", "true");
  document.getElementById("result-location").textContent = "Checking selected location…";
  document.getElementById("alert-nudge").hidden = true;
  for (const id of ["result-risk", "result-alert", "result-elev", "result-score"]) document.getElementById(id).textContent = "—";
  if (queryMarker) queryMarker.remove();
  const rain24 = Number(document.getElementById("rain24").value);
  const rain72 = Number(document.getElementById("rain72").value);

  if (!locationName) locationName = await reverseGeocode(lat, lon);
  if (request !== _pointRequest) return;

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
    if (request !== _pointRequest) return;

    const panel = document.getElementById("result-panel");
    panel.hidden = false;

    document.getElementById("result-location").textContent =
      locationName || `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;

    document.getElementById("result-risk").textContent  = risk.risk_class;
    document.getElementById("result-risk").style.color  = RISK_COLORS[risk.risk_class] || "#fff";
    document.getElementById("result-alert").textContent = alert.alert_level;
    document.getElementById("result-alert").style.color = alertResultColor(alert.alert_level);
    document.getElementById("result-elev").textContent  = `${risk.elevation_m.toFixed(1)} m`;
    const susceptibility = risk.hazard_score ?? risk.flood_score;
    document.getElementById("result-score").textContent = susceptibility.toFixed(3);

    const nudge      = document.getElementById("alert-nudge");
    const isHighRisk = ["High", "Very High"].includes(risk.risk_class);
    if (alert.alert_level === "No Alert" && isHighRisk) {
      nudge.hidden = false;
      nudge.textContent = `⚠ ${risk.risk_class} susceptibility. Sliders explore rainfall scenarios; they do not change the live forecast.`;
    } else {
      nudge.hidden = true;
    }

    // A point scenario must not overwrite the city-wide forecast beacon.

    if (queryMarker) queryMarker.remove();
    const el = document.createElement("div");
    el.className = "query-dot";
    el.style.background =
      ALERT_COLORS[alert.alert_level] || RISK_COLORS[risk.risk_class] || "#888";
    queryMarker = new maplibregl.Marker({ element: el, anchor: "center" })
      .setLngLat([lon, lat])
      .setPopup(
        new maplibregl.Popup({ offset: 14, className: "fs-popup" }).setHTML(
          `<strong>${escapeHTML(risk.risk_class)} risk</strong><br/>
           Rainfall scenario: <em>${escapeHTML(alert.alert_level)}</em><br/>
           Elev: ${risk.elevation_m.toFixed(1)} m &nbsp;|&nbsp; Susceptibility: ${susceptibility.toFixed(3)}`
        )
      )
      .addTo(map);
    queryMarker.getPopup().addTo(map);
    // Point lookups do not establish that the live forecast is fresh.
  } catch (err) {
    if (request !== _pointRequest) return;
    console.error("Query failed:", err);
    const panel = document.getElementById("result-panel");
    panel.hidden = false;
    document.getElementById("result-location").textContent = "No result: location may be outside mapped coverage or data unavailable.";
    for (const id of ["result-risk", "result-alert", "result-elev", "result-score"]) document.getElementById(id).textContent = "—";
    if (queryMarker) queryMarker.remove();
  } finally {
    if (request === _pointRequest) panel.setAttribute("aria-busy", "false");
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
let _searchRequest = 0;
let _searchActive = -1;

searchInput.addEventListener("input", () => {
  _searchRequest++;
  hideDropdown();
  const q = searchInput.value.trim();
  searchClear.hidden = q.length === 0;
  clearTimeout(searchTimer);
  if (q.length < 2) { hideDropdown(); return; }
  searchTimer = setTimeout(() => doSearch(q), 320);
});
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { _searchRequest++; hideDropdown(); }
  const options = Array.from(searchResults.querySelectorAll(".result-item"));
  if (!searchResults.hidden && options.length && ["ArrowDown", "ArrowUp"].includes(e.key)) {
    e.preventDefault();
    _searchActive = (_searchActive + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    options.forEach((option, i) => option.setAttribute("aria-selected", String(i === _searchActive)));
    searchInput.setAttribute("aria-activedescendant", options[_searchActive].id);
    options[_searchActive].scrollIntoView({block: "nearest"});
  } else if (e.key === "Enter" && _searchActive >= 0 && !searchResults.hidden) {
    e.preventDefault(); options[_searchActive]?.click();
  }
});
searchClear.addEventListener("click", () => {
  _searchRequest++;
  clearTimeout(searchTimer);
  searchInput.value = "";
  searchClear.hidden = true;
  hideDropdown();
  searchInput.focus();
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-wrap") && !e.target.closest(".search-dropdown")) hideDropdown();
});

async function doSearch(query) {
  const request = ++_searchRequest;
  document.getElementById("search-status").textContent = "Searching LGAs…";
  try {
    const url = `${API_BASE_URL}/places/search?q=${encodeURIComponent(query)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Search unavailable");
    const results = await res.json();
    if (request !== _searchRequest || searchInput.value.trim() !== query) return;
    document.getElementById("search-status").textContent = results.length ? "Use arrow keys and Enter to choose an LGA centre." : "No matching LGAs.";
    renderDropdown(results);
  } catch (err) {
    if (request !== _searchRequest) return;
    hideDropdown(); document.getElementById("search-status").textContent = "Search unavailable. Try again or use an LGA button.";
  }
}

function renderDropdown(items) {
  if (!items || items.length === 0) {
    searchResults.innerHTML = `<li class="no-result">No places found in Lagos</li>`;
    searchResults.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
    return;
  }
  searchResults.innerHTML = items.map((item, i) => {
    const name = String(item.display_name || "Unnamed LGA").split(",").slice(0, 3).join(", ");
    return `<li id="search-option-${i}" role="option" aria-selected="false" class="result-item" data-idx="${i}" data-lat="${Number(item.lat)}" data-lon="${Number(item.lon)}" data-name="${escapeHTML(encodeURIComponent(name))}">
      <svg class="result-pin" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="6" r="3"/><path d="M8 2C5.24 2 3 4.24 3 7c0 3.75 5 9 5 9s5-5.25 5-9c0-2.76-2.24-5-5-5z"/></svg>
      <span>${escapeHTML(name)}</span>
    </li>`;
  }).join("");
  searchResults.hidden = false;
  searchInput.setAttribute("aria-expanded", "true");
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
  if (isFinite(lat) && isFinite(lon)) map.flyTo({ center: [lon, lat], zoom: 15, pitch: PILOT_PITCH, bearing: PILOT_BEARING, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 1400 });
  queryPoint(lat, lon, name);
}
function hideDropdown() {
  _searchActive = -1;
  searchResults.hidden = true; searchResults.innerHTML = "";
  searchInput.setAttribute("aria-expanded", "false");
  searchInput.removeAttribute("aria-activedescendant");
}

// ---------------------------------------------------------------------------
// LGA quick-jump buttons
// ---------------------------------------------------------------------------
document.querySelectorAll(".lga-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const lat  = parseFloat(btn.dataset.lat);
    const lon  = parseFloat(btn.dataset.lon);
    const zoom = parseFloat(btn.dataset.zoom);
    if (isFinite(lat) && isFinite(lon)) {
      map.flyTo({ center: [lon, lat], zoom, pitch: PILOT_PITCH, bearing: PILOT_BEARING, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 1200 });
      queryPoint(lat, lon, btn.textContent.trim());
    }
  });
});

// ---------------------------------------------------------------------------
// Rainfall sliders
// ---------------------------------------------------------------------------
const rain24Input = document.getElementById("rain24");
const rain72Input = document.getElementById("rain72");
rain24Input.disabled = true;
rain72Input.disabled = true;

rain24Input.addEventListener("input", () => {
  document.getElementById("rain24-val").textContent = `${rain24Input.value} mm`;
  markManual();
  applySliderAlerts();   // re-color map in real time
});
rain72Input.addEventListener("input", () => {
  document.getElementById("rain72-val").textContent = `${rain72Input.value} mm`;
  markManual();
  applySliderAlerts();   // re-color map in real time
});

function markManual() {
  _scenarioMode = true;
  invalidatePointResult();
  showMapMode();
  const badge = document.getElementById("forecast-badge");
  if (badge) { badge.dataset.manual = "true"; badge.hidden = false; badge.textContent = "Scenario only — not a live forecast"; }
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

function setApiStatus(ok, fetchedAt) {
  const el = document.getElementById("api-status");
  el.classList.toggle("ok", ok);
  el.classList.toggle("err", !ok);
  el.title = "Use Refresh forecast to update";

  if (!ok) {
    el.textContent = `Cannot reach API · use Refresh forecast to retry`;
    clearInterval(_countdownTimer);
    return;
  }

  // Record when the next scheduled refresh will fire
  if (!fetchedAt) {
    el.classList.remove("ok");
    if (_liveAlerts) {
      el.classList.add('err');
      _forecastStale = true;
      el.textContent = 'Forecast timestamp unavailable — freshness cannot be confirmed.';
      showMapMode();
    } else el.textContent = "Static risk map · live forecast unavailable";
    clearInterval(_countdownTimer);
    return;
  }
  const forecastAge = Date.now() - Date.parse(fetchedAt);
  if (!Number.isFinite(forecastAge) || forecastAge > 2 * REFRESH_INTERVAL_MS || forecastAge < -5 * 60 * 1000) {
    el.classList.remove('ok');
    el.classList.add('err');
    el.textContent = 'Forecast timestamp missing, old or in the future — freshness cannot be confirmed.';
    _forecastStale = true;
    showMapMode();
    return;
  }
  _nextRefreshAt = Date.now() + REFRESH_INTERVAL_MS;

  const updatedStr = fetchedAt
    ? new Date(fetchedAt).toLocaleTimeString("en-NG", { hour: "2-digit", minute: "2-digit", timeZone: "Africa/Lagos" })
    : new Date().toLocaleTimeString("en-NG", { hour: "2-digit", minute: "2-digit", timeZone: "Africa/Lagos" });

  clearInterval(_countdownTimer);
  el.textContent = `Forecast updated ${updatedStr} Lagos time · auto-refresh every 30 min`;
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
let _streetRequest = 0;

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
map.on("moveend", () => {
  if (_streetsLoaded && map.getZoom() >= STREETS_MIN_ZOOM) _loadStreetsLayer();
});

async function _loadStreetsLayer() {
  const requestId = ++_streetRequest;
  try {
    const bounds = map.getBounds();
    const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(',');
    const res = await fetch(`${API_BASE_URL}/risk/streets?bbox=${encodeURIComponent(bbox)}`);
    if (!res.ok) {
      // 404 = script hasn't been run yet — silently skip, don't spam console
      if (res.status !== 404) console.warn("Streets layer HTTP", res.status);
      return;
    }
    const geojson = await res.json();
    if (requestId !== _streetRequest) return;

    if (map.getSource("street-risk")) {
      map.getSource("street-risk").setData(geojson);
      return;
    }

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
          `<strong>${escapeHTML(name)}</strong><br>` +
          `Type: ${escapeHTML(p.highway)}<br>` +
          `Area susceptibility: <span style="color:${_streetColor(rc)};font-weight:600">${escapeHTML(rc)}</span>`
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
          `<strong>${escapeHTML(p.node_id)}</strong><br>` +
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

// Signup uses the location-confirming inline OTP flow on the landing page.

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


// ---------------------------------------------------------------------------
// Phase 21 — ML Flood Depth Layer (GradientBoostingRegressor, 150 mm storm)
// 24,933 centroid points coloured by predicted depth class.
// Loaded lazily on first toggle to avoid 6.8 MB fetch on page load.
// ---------------------------------------------------------------------------
let _mlDepthLoaded  = false;
let _mlDepthLoading = false;
let _mlDepthVisible = false;   // off by default — user toggles on

const ML_DEPTH_COLORS = {
  "None":    "#FFFFFF",
  "Low":     "#FFF176",
  "Medium":  "#FF9800",
  "High":    "#F44336",
  "Extreme": "#B71C1C",
};

async function _loadMlDepthLayer() {
  if (_mlDepthLoaded || _mlDepthLoading) return;
  _mlDepthLoading = true;

  const btn = document.getElementById("ml-depth-toggle");
  if (btn) btn.textContent = "Loading ML depth…";

  try {
    const res = await fetch(`${API_BASE_URL}/depth/ml-grid`);
    if (!res.ok) {
      if (res.status === 503) {
        console.info("ML depth grid not yet generated — run 09_train_flood_depth.py");
      } else {
        console.warn("ML depth layer HTTP", res.status);
      }
      if (btn) { btn.textContent = "ML depth (unavailable)"; btn.disabled = true; }
      return;
    }

    const geojson = await res.json();
    _mlDepthLoaded = true;

    map.addSource("ml-depth", { type: "geojson", data: geojson });

    // Outer glow for High + Extreme cells
    map.addLayer({
      id: "ml-depth-glow",
      type: "circle",
      source: "ml-depth",
      filter: ["in", ["get", "depth_class"], ["literal", ["High", "Extreme"]]],
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          10, 6,
          14, 12,
        ],
        "circle-color":   "#F44336",
        "circle-opacity": 0.18,
        "circle-blur":    1,
      },
    });

    // Core dots — all cells, colour by depth_class
    map.addLayer({
      id: "ml-depth-dots",
      type: "circle",
      source: "ml-depth",
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          10, 2.5,
          13, 5,
          16, 9,
        ],
        "circle-color":        ["get", "depth_colour"],
        "circle-opacity":      0.82,
        "circle-stroke-color": "rgba(0,0,0,0.45)",
        "circle-stroke-width": 0.6,
      },
    });

    // Click popup
    map.on("click", "ml-depth-dots", (e) => {
      const p   = e.features[0].properties;
      const col = /^#[0-9a-f]{6}$/i.test(p.depth_colour || '') ? p.depth_colour : "#888";
      new maplibregl.Popup({ className: "fs-popup", closeButton: false })
        .setLngLat(e.lngLat)
        .setHTML(
          `<strong>Grid cell ${escapeHTML(p.cell_id)}</strong><br>` +
          `<span style="font-size:11px;color:#aaa">Experimental depth · 150 mm rainfall scenario; not validated observations</span><br>` +
          `Modeled depth: <span style="color:${col};font-weight:600">${escapeHTML(p.predicted_depth_m)} m</span><br>` +
          `Class: <span style="color:${col}">${escapeHTML(p.depth_class)}</span><br>` +
          `Elevation: ${p.elevation_m != null ? Number(p.elevation_m).toFixed(1) : "—"} m<br>` +
          `Risk class: ${escapeHTML(p.risk_class || "—")}`
        )
        .addTo(map);
    });
    map.on("mouseenter", "ml-depth-dots", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "ml-depth-dots", () => { map.getCanvas().style.cursor = ""; });

    // Start hidden unless the user already clicked toggle before load finished
    const vis = _mlDepthVisible ? "visible" : "none";
    ["ml-depth-glow", "ml-depth-dots"].forEach(id => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
    });

    if (btn) btn.textContent = _mlDepthVisible ? "Hide ML depth" : "Show ML depth";

    const meta = geojson.metadata || {};
    console.log(
      `ML depth layer loaded — ${(geojson.features || []).length} cells ` +
      `(design storm ${meta.design_rain_24h_mm || 150} mm/24h)`
    );
  } catch (err) {
    console.warn("ML depth layer failed to load:", err);
    if (btn) { btn.textContent = "ML depth (error)"; btn.disabled = true; }
  } finally {
    _mlDepthLoading = false;
  }
}

// ── Toggle ML depth layer visibility ────────────────────────────────────────────
function toggleMlDepthLayer() {
  _mlDepthVisible = !_mlDepthVisible;
  const btn = document.getElementById("ml-depth-toggle");

  if (!_mlDepthLoaded) {
    // Lazy-load on first toggle
    _loadMlDepthLayer();
    if (btn) btn.textContent = "Loading ML depth…";
    return;
  }

  const vis = _mlDepthVisible ? "visible" : "none";
  ["ml-depth-glow", "ml-depth-dots"].forEach(id => {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
  });
  if (btn) btn.textContent = _mlDepthVisible ? "Hide ML depth" : "Show ML depth";
}
