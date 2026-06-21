// Local development (opening dashboard/index.html directly via file://,
// or via http://localhost) points at the local uvicorn dev server.
// Once deployed (e.g. served by the same FastAPI app at /dashboard/ on
// Render), an empty base URL means fetch() uses relative paths, which
// resolve against the deployed domain automatically — no manual edit
// needed after deploying.
const isLocalDev =
  window.location.protocol === "file:" ||
  ["localhost", "127.0.0.1"].includes(window.location.hostname);
const API_BASE_URL = isLocalDev ? "http://localhost:8000" : "";

const RISK_COLORS = {
  "Low": "#2E7D5B",
  "Moderate": "#D9A441",
  "High": "#D9622B",
  "Very High": "#C23B3B",
};

const map = L.map("map", { zoomControl: true }).setView([6.45, 3.42], 12);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
  maxZoom: 19,
}).addTo(map);

let riskLayer = null;
let queryMarker = null;

function styleByRiskClass(feature) {
  const cls = feature.properties.risk_class;
  return {
    fillColor: RISK_COLORS[cls] || "#555",
    weight: 0,
    fillOpacity: 0.55,
  };
}

async function loadRiskGrid() {
  try {
    const res = await fetch(`${API_BASE_URL}/risk/grid`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const geojson = await res.json();

    if (riskLayer) map.removeLayer(riskLayer);
    riskLayer = L.geoJSON(geojson, {
      style: styleByRiskClass,
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        layer.bindPopup(
          `<strong>${p.risk_class}</strong><br/>flood_score: ${Number(p.flood_score).toFixed(3)}`
        );
      },
    }).addTo(map);

    if (geojson.features && geojson.features.length) {
      map.fitBounds(riskLayer.getBounds(), { padding: [20, 20] });
    }

    showDataSourceBanner(geojson.data_source);
    setApiStatus(true);
  } catch (err) {
    console.error("Failed to load risk grid:", err);
    setApiStatus(false);
  }
}

function showDataSourceBanner(source) {
  const banner = document.getElementById("data-source-banner");
  if (source === "synthetic_demo") {
    banner.hidden = false;
    banner.textContent =
      "Showing a SYNTHETIC demo grid — no processed pipeline output found yet. " +
      "Run scripts/02-04 to serve real data.";
  } else {
    banner.hidden = true;
  }
}

function setApiStatus(ok) {
  const el = document.getElementById("api-status");
  el.classList.toggle("ok", ok);
  el.classList.toggle("err", !ok);
  el.textContent = ok ? `connected · ${API_BASE_URL}` : `cannot reach API at ${API_BASE_URL}`;
}

function setBeacon(level) {
  document.getElementById("beacon").dataset.level = level;
}

async function queryPoint(lat, lon) {
  const rain24 = Number(document.getElementById("rain24").value);
  const rain72 = Number(document.getElementById("rain72").value);

  try {
    const riskRes = await fetch(`${API_BASE_URL}/risk/point?lat=${lat}&lon=${lon}`);
    if (!riskRes.ok) throw new Error(`HTTP ${riskRes.status}`);
    const risk = await riskRes.json();

    const alertRes = await fetch(`${API_BASE_URL}/alerts/current`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon, rain_24h_mm: rain24, rain_72h_mm: rain72 }),
    });
    if (!alertRes.ok) throw new Error(`HTTP ${alertRes.status}`);
    const alert = await alertRes.json();

    document.getElementById("result-panel").hidden = false;
    document.getElementById("result-risk").textContent = risk.risk_class;
    document.getElementById("result-alert").textContent = alert.alert_level;
    document.getElementById("result-elev").textContent = `${risk.elevation_m.toFixed(1)} m`;
    document.getElementById("result-score").textContent = risk.flood_score.toFixed(3);

    setBeacon(alert.alert_level);

    if (queryMarker) map.removeLayer(queryMarker);
    queryMarker = L.circleMarker([lat, lon], {
      radius: 8,
      color: "#fff",
      weight: 2,
      fillColor: RISK_COLORS[risk.risk_class] || "#888",
      fillOpacity: 0.9,
    }).addTo(map);

    setApiStatus(true);
  } catch (err) {
    console.error("Query failed:", err);
    setApiStatus(false);
  }
}

map.on("click", (e) => {
  const { lat, lng } = e.latlng;
  document.getElementById("lat-input").value = lat.toFixed(4);
  document.getElementById("lon-input").value = lng.toFixed(4);
  queryPoint(lat, lng);
});

document.getElementById("query-btn").addEventListener("click", () => {
  const lat = Number(document.getElementById("lat-input").value);
  const lon = Number(document.getElementById("lon-input").value);
  queryPoint(lat, lon);
});

const rain24Input = document.getElementById("rain24");
const rain72Input = document.getElementById("rain72");
rain24Input.addEventListener("input", () => {
  document.getElementById("rain24-val").textContent = `${rain24Input.value} mm`;
});
rain72Input.addEventListener("input", () => {
  document.getElementById("rain72-val").textContent = `${rain72Input.value} mm`;
});

loadRiskGrid();
