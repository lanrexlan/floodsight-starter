// ---------------------------------------------------------------------------
// FloodSight Dashboard — MapLibre GL JS edition
// 3D interactive map with place search, 3D risk columns, pilot LGA focus
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

// Pilot grid actual bounds: lon 3.359–3.450, lat 6.439–6.620
// Center on the middle of the real grid coverage
const PILOT_CENTER  = [3.405, 6.530];
const PILOT_ZOOM    = 11.5;
const PILOT_PITCH   = 48;
const PILOT_BEARING = -8;

// ---------------------------------------------------------------------------
// Map init — OpenFreeMap dark style (free, no API key)
// ---------------------------------------------------------------------------
// CARTO dark-matter is a 100%-free MapLibre vector style, no API key needed.
// It includes building footprints we can extrude for 3D effect.
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
// Risk grid — loaded from API, rendered as 3D extrusion columns
// ---------------------------------------------------------------------------
let queryMarker = null;

map.on("load", () => {
  loadRiskGrid();
});

async function loadRiskGrid() {
  try {
    const res = await fetch(`${API_BASE_URL}/risk/grid`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();

    // Remove existing layers/source if reloading
    ["flood-risk-3d", "flood-risk-outline", "flood-risk-flat"].forEach(id => {
      if (map.getLayer(id)) map.removeLayer(id);
    });
    if (map.getSource("risk-grid")) map.removeSource("risk-grid");

    map.addSource("risk-grid", { type: "geojson", data: geojson });

    // 3D extrusion columns — height proportional to flood_score
    map.addLayer({
      id: "flood-risk-3d",
      type: "fill-extrusion",
      source: "risk-grid",
      paint: {
        "fill-extrusion-color": [
          "match", ["get", "risk_class"],
          "Low",       "#2E7D5B",
          "Moderate",  "#D9A441",
          "High",      "#D9622B",
          "Very High", "#C23B3B",
          "#555"
        ],
        // Max height ~180 m for Very High (score ≈ 1.0)
        "fill-extrusion-height": ["*", ["get", "flood_score"], 180],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": [
          "interpolate", ["linear"], ["zoom"],
          10, 0.85,
          15, 0.65
        ],
        "fill-extrusion-vertical-gradient": true,
      },
    });

    // Flat fallback for when zoomed out far (no 3D distraction)
    map.addLayer({
      id: "flood-risk-flat",
      type: "fill",
      source: "risk-grid",
      minzoom: 0,
      maxzoom: 10,
      paint: {
        "fill-color": [
          "match", ["get", "risk_class"],
          "Low",       "#2E7D5B",
          "Moderate",  "#D9A441",
          "High",      "#D9622B",
          "Very High", "#C23B3B",
          "#555"
        ],
        "fill-opacity": 0.55,
      },
    });

    showDataSourceBanner(geojson.data_source);
    setApiStatus(true);
    wireMapClick();
  } catch (err) {
    console.error("Failed to load risk grid:", err);
    setApiStatus(false);
  }
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

  // Also allow clicking the background map
  map.on("click", (e) => {
    // Only trigger if we didn't click a risk cell (those have their own handler)
    const features = map.queryRenderedFeatures(e.point, { layers: ["flood-risk-3d"] });
    if (features.length === 0) {
      queryPoint(e.lngLat.lat, e.lngLat.lng, null);
    }
  });
}

// ---------------------------------------------------------------------------
// Reverse geocode — turn lat/lon into a human-readable area name
// ---------------------------------------------------------------------------
async function reverseGeocode(lat, lon) {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=14&accept-language=en`;
    const res = await fetch(url, {
      headers: { "User-Agent": "FloodSight-Dashboard/1.0" },
    });
    const data = await res.json();
    const a = data.address || {};
    // Prefer the most specific named area available
    return (
      a.neighbourhood ||
      a.suburb ||
      a.city_district ||
      a.town ||
      a.village ||
      a.county ||
      data.display_name?.split(",")[0] ||
      null
    );
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Query point — risk + alert
// ---------------------------------------------------------------------------
async function queryPoint(lat, lon, locationName) {
  const rain24 = Number(document.getElementById("rain24").value);
  const rain72 = Number(document.getElementById("rain72").value);

  // Reverse-geocode if the name wasn't supplied (map click)
  if (!locationName) {
    locationName = await reverseGeocode(lat, lon);
  }

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

    // Update sidebar result panel
    const panel = document.getElementById("result-panel");
    panel.hidden = false;

    const locEl = document.getElementById("result-location");
    locEl.textContent = locationName || `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;

    document.getElementById("result-risk").textContent  = risk.risk_class;
    document.getElementById("result-risk").style.color  = RISK_COLORS[risk.risk_class] || "#fff";
    document.getElementById("result-alert").textContent = alert.alert_level;
    document.getElementById("result-alert").style.color = alertColor(alert.alert_level);
    document.getElementById("result-elev").textContent  = `${risk.elevation_m.toFixed(1)} m`;
    document.getElementById("result-score").textContent = risk.flood_score.toFixed(3);

    // Show a nudge if high-risk but no alert (rain below threshold)
    const nudge = document.getElementById("alert-nudge");
    const isHighRisk = ["High", "Very High"].includes(risk.risk_class);
    if (alert.alert_level === "No Alert" && isHighRisk) {
      nudge.hidden = false;
      nudge.textContent = `⚠ ${risk.risk_class} risk — slide 24h rainfall above 50 mm for Watch, 100 mm for Warning.`;
    } else {
      nudge.hidden = true;
    }

    setBeacon(alert.alert_level);

    // Place / update marker
    if (queryMarker) queryMarker.remove();
    const el = document.createElement("div");
    el.className = "query-dot";
    el.style.background = RISK_COLORS[risk.risk_class] || "#888";
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

function alertColor(level) {
  return level === "Warning" ? "#FF5A3C" : level === "Watch" ? "#D9A441" : "#2E7D5B";
}

// ---------------------------------------------------------------------------
// Place search — Nominatim (OpenStreetMap geocoder, no API key)
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
  if (!e.target.closest(".search-wrap") && !e.target.closest(".search-dropdown")) {
    hideDropdown();
  }
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
    const items = await res.json();
    renderDropdown(items);
  } catch (err) {
    console.error("Search failed:", err);
    hideDropdown();
  }
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
      const lat = parseFloat(li.dataset.lat);
      const lon = parseFloat(li.dataset.lon);
      const name = decodeURIComponent(li.dataset.name);
      selectPlace(lat, lon, name);
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

function hideDropdown() {
  searchResults.hidden = true;
  searchResults.innerHTML = "";
}

// ---------------------------------------------------------------------------
// LGA quick-jump buttons
// ---------------------------------------------------------------------------
document.querySelectorAll(".lga-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const lat  = parseFloat(btn.dataset.lat);
    const lon  = parseFloat(btn.dataset.lon);
    const zoom = parseFloat(btn.dataset.zoom);
    const name = btn.textContent.trim();
    map.flyTo({ center: [lon, lat], zoom, pitch: PILOT_PITCH, bearing: PILOT_BEARING, duration: 1200, essential: true });
    queryPoint(lat, lon, name);
  });
});

// ---------------------------------------------------------------------------
// Rainfall sliders
// ---------------------------------------------------------------------------
const rain24Input = document.getElementById("rain24");
const rain72Input = document.getElementById("rain72");
rain24Input.addEventListener("input", () => {
  document.getElementById("rain24-val").textContent = `${rain24Input.value} mm`;
});
rain72Input.addEventListener("input", () => {
  document.getElementById("rain72-val").textContent = `${rain72Input.value} mm`;
});

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------
function showDataSourceBanner(source) {
  const banner = document.getElementById("data-source-banner");
  if (source === "synthetic_demo") {
    banner.hidden = false;
    banner.textContent =
      "Showing SYNTHETIC demo grid — run scripts/02-04 to serve real Lagos data.";
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
