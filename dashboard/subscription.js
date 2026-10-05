// Same-origin subscription UI. No phone numbers, coordinates or OTPs persist in browser storage.
let _subLat = null, _subLon = null, _subGeoTimer = null;
let _subLocationRequest = 0, _subBusy = false, _subPending = null;
const RISK_COLORS_SUB = {'Very High':'#f87171', High:'#fb923c', Moderate:'#fbbf24', Low:'#34d399'};
const subElement = id => document.getElementById(id);

function subMessage(message, error = false) {
  const el = subElement('sub-status');
  el.textContent = message;
  el.className = error ? 'sub-status error' : 'sub-status';
  el.style.display = 'block';
}
function subError(data, fallback) {
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map(item => String(item.msg || 'Invalid input')).join('; ');
  return fallback;
}
function subCheckReady() {
  const phone = subElement('sub-phone').value.trim();
  const ready = phone.length >= 7 && _subLat !== null && subElement('sub-consent').checked;
  subElement('sub-submit').disabled = !ready || _subBusy || !!_subPending;
  for (const id of ['sub-phone', 'sub-name', 'sub-area', 'sub-consent']) subElement(id).disabled = _subBusy || !!_subPending;
  document.querySelector('.btn-locate').disabled = _subBusy || !!_subPending;
  subElement('sub-confirm').disabled = _subBusy;
  subElement('sub-cancel').disabled = _subBusy;
}
async function subSetLocation(lat, lon, areaLabel) {
  const request = ++_subLocationRequest;
  _subLat = null; _subLon = null;
  subElement('sub-consent').checked = false;
  subElement('sub-places').hidden = true;
  subElement('sub-area').value = areaLabel;
  subElement('sub-risk-preview').textContent = 'Checking mapped coverage…';
  subCheckReady();
  try {
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error('Invalid location. Choose again.');
    const res = await fetch(`${API}/risk/point?lat=${lat}&lon=${lon}`);
    if (!res.ok) throw new Error(res.status === 404 ? 'This location is outside mapped coverage. Choose another location.' : 'Coverage check unavailable. Please try again.');
    const data = await res.json();
    if (request !== _subLocationRequest) return;
    if (!Object.hasOwn(RISK_COLORS_SUB, data.risk_class)) throw new Error('Location risk data unavailable. Choose again.');
    _subLat = lat; _subLon = lon;
    subElement('sub-risk-preview').textContent = `Selected: ${areaLabel}. Baseline susceptibility: ${data.risk_class}. Confirm this location below.`;
    subMessage('Location checked. Confirm your consent to continue.');
  } catch (error) {
    if (request !== _subLocationRequest) return;
    subElement('sub-risk-preview').textContent = '';
    subMessage(error.message, true);
  } finally { if (request === _subLocationRequest) subCheckReady(); }
}
function subGeocode(query) {
  const request = ++_subLocationRequest;
  _subLat = null; _subLon = null;
  subElement('sub-consent').checked = false;
  const places = subElement('sub-places');
  places.hidden = true; places.replaceChildren();
  subElement('sub-risk-preview').textContent = '';
  subCheckReady(); clearTimeout(_subGeoTimer);
  if (query.trim().length < 2) return;
  _subGeoTimer = setTimeout(async () => {
    try {
      const res = await fetch(`${API}/places/search?q=${encodeURIComponent(query.trim())}`);
      if (!res.ok) throw new Error('Location search unavailable. Try again or use GPS.');
      const results = await res.json();
      if (request !== _subLocationRequest) return;
      if (!Array.isArray(results)) throw new Error('Location search unavailable.');
      for (const item of results) {
        const li = document.createElement('li'), button = document.createElement('button');
        const label = String(item.display_name || 'LGA').split(',').slice(0, 2).join(', ');
        button.type = 'button'; button.textContent = `${label} — area centre`;
        button.addEventListener('click', () => subSetLocation(Number(item.lat), Number(item.lon), label));
        li.append(button); places.append(li);
      }
      places.hidden = results.length === 0;
      subMessage(results.length ? 'Choose an LGA centre below, or use GPS for your current location.' : 'No matching LGAs. Try another name.');
    } catch (error) { if (request === _subLocationRequest) subMessage(error.message, true); }
  }, 400);
}
function subUseMyLocation() {
  if (_subBusy || _subPending) return;
  const request = ++_subLocationRequest;
  clearTimeout(_subGeoTimer);
  _subLat = null; _subLon = null; subCheckReady();
  subElement('sub-consent').checked = false;
  subElement('sub-places').hidden = true;
  if (!navigator.geolocation) { subMessage('GPS is unavailable. Choose an LGA instead.', true); return; }
  subMessage('Getting your location…');
  navigator.geolocation.getCurrentPosition(async pos => {
    const lat = pos.coords.latitude, lon = pos.coords.longitude;
    let label = `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;
    try {
      const res = await fetch(`${API}/places/reverse?lat=${lat}&lon=${lon}`);
      if (res.ok) { const data = await res.json(); label = data.display_name?.split(',')[0] || label; }
    } catch { /* Coverage check still required when reverse lookup is unavailable. */ }
    if (request === _subLocationRequest) await subSetLocation(lat, lon, label);
  }, () => {
    if (request === _subLocationRequest) subMessage('Could not get GPS location. Choose an LGA instead.', true);
  }, {timeout:10000});
}
function subCancelConfirmation() {
  if (_subBusy) return;
  _subPending = null;
  subElement('sub-code').value = '';
  subElement('sub-otp-panel').hidden = true;
  subMessage('Confirmation cancelled. No new subscription was activated by this action.');
  subCheckReady(); subElement('sub-phone').focus();
}
function subSuccess(data, areaName) {
  if (data.status !== 'subscribed') throw new Error('Subscription could not be confirmed. Please try again.');
  _subPending = null; _subLat = null; _subLon = null;
  subElement('sub-otp-panel').hidden = true;
  for (const id of ['sub-phone', 'sub-name', 'sub-area', 'sub-code']) subElement(id).value = '';
  subElement('sub-consent').checked = false;
  subElement('sub-risk-preview').textContent = '';
  subMessage(`Subscribed for ${data.area_name || areaName || 'your selected location'}. SMS delivery remains subject to service availability.`);
  subElement('sub-status').className = 'sub-status success';
}
async function submitSubscription() {
  if (_subBusy || _subPending || subElement('sub-submit').disabled) return;
  const body = {phone:subElement('sub-phone').value.trim(), name:subElement('sub-name').value.trim() || null,
    lat:_subLat, lon:_subLon, area_name:subElement('sub-area').value.trim() || null, consent:subElement('sub-consent').checked};
  if (body.lat === null || !body.consent) return;
  _subBusy = true; subCheckReady();
  subElement('sub-submit').textContent = 'Requesting subscription…';
  try {
    const res = await fetch(`${API}/subscribe`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await res.json();
    if (!res.ok) throw new Error(subError(data, `Subscription unavailable (HTTP ${res.status}).`));
    if (data.status === 'pending_confirmation') {
      if (!data.phone) throw new Error('Confirmation details unavailable. Try again.');
      _subPending = {phone:data.phone, area:body.area_name};
      subElement('sub-otp-panel').hidden = false;
      subMessage('Code requested by SMS. Your subscription is not active until the phone number is confirmed.');
      subElement('sub-code').focus();
    } else subSuccess(data, body.area_name);
  } catch (error) { subMessage(error.message || 'Could not subscribe. Please try again.', true); }
  finally { _subBusy = false; subElement('sub-submit').textContent = 'Subscribe to flood alerts'; subCheckReady(); }
}
async function subConfirmCode() {
  if (_subBusy || !_subPending) return;
  const code = subElement('sub-code').value.trim();
  if (!/^[0-9]{6}$/.test(code)) { subMessage('Enter the six-digit SMS code.', true); subElement('sub-code').focus(); return; }
  _subBusy = true; subCheckReady();
  try {
    const res = await fetch(`${API}/subscribe/confirm`, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({phone:_subPending.phone, code})});
    const data = await res.json();
    if (!res.ok) throw new Error(subError(data, 'Confirmation failed. Retry the code or cancel to request another.'));
    subSuccess(data, _subPending.area);
  } catch (error) { subMessage(error.message || 'Confirmation unavailable. Please try again.', true); }
  finally { _subBusy = false; subCheckReady(); }
}
subElement('sub-code').addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); subConfirmCode(); }
});
