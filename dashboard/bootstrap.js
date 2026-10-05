// Show an honest unavailable state if the map dependency or WebGL cannot start.
function showMapStartupFailure() {
  document.getElementById('api-status').textContent = 'Map unavailable — required resources or graphics support could not load. No live alerts displayed.';
  document.getElementById('map-mode').textContent = 'Map unavailable. Check your connection and reload, or use the SMS signup link.';
  document.getElementById('rainfall-hint').textContent = 'Scenario controls unavailable.';
  for (const selector of ['#rain24', '#rain72', '#search-input', '.lga-btn']) {
    document.querySelectorAll(selector).forEach(el => {el.disabled = true;});
  }
}
window.addEventListener('error', event => {
  if (!window.floodsightMapReady && event.filename?.includes('/app.js')) showMapStartupFailure();
});
if (!window.maplibregl) showMapStartupFailure();
else {
  const script = document.createElement('script');
  script.src = 'app.js';
  script.onerror = showMapStartupFailure;
  document.body.append(script);
}
