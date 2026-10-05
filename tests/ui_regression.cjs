// Hermetic UI behavior tests: fake DOM/map and mocked HTTP, never real SMS or production APIs.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(id='') { this.id=id; this.value=''; this.checked=false; this.hidden=false; this.disabled=false;
    this.style={}; this.dataset={}; this.attrs={}; this.listeners={}; this.children=[]; this.textContent='';
    this.classList={toggle(){}, add(){}, remove(){}}; this.parentElement={hidden:false}; }
  addEventListener(event, fn) { (this.listeners[event] ||= []).push(fn); }
  emit(event, data={}) { for (const fn of this.listeners[event] || []) fn(data); }
  click() { this.emit('click'); }
  setAttribute(k,v) { this.attrs[k]=v; }
  removeAttribute(k) { delete this.attrs[k]; }
  focus() { this.focused=true; }
  scrollIntoView() {}
  append(el) { this.children.push(el); }
  replaceChildren() { this.children=[]; }
  querySelectorAll() { return this.children; }
  querySelector() { return null; }
  set innerHTML(value) {
    this.html=value; this.children=[];
    for (const match of value.matchAll(/<li id="([^"]+)"[^>]*data-lat="([^"]+)" data-lon="([^"]+)" data-name="([^"]+)"/g)) {
      const el=new Element(match[1]); el.dataset={lat:match[2], lon:match[3], name:match[4]}; this.children.push(el);
    }
  }
  get innerHTML() { return this.html || ''; }
}
function harness(file) {
  const elements=new Map(); const el=id => { if (!elements.has(id)) elements.set(id,new Element(id)); return elements.get(id); };
  const timers=[]; const context={console:{log(){}, warn(){}, error(){}}, API:'',
    window:{location:{protocol:'http:',hostname:'localhost'}, matchMedia:()=>({matches:true})},
    location:{protocol:'http:',hostname:'localhost'}, navigator:{},
    document:{getElementById:el, querySelector:el, querySelectorAll:()=>[], addEventListener(){}, createElement:()=>new Element()},
    setTimeout:fn=>(timers.push(fn),timers.length), clearTimeout(){}, setInterval:()=>1, clearInterval(){},
    fetch:async()=>{ throw Error('Unexpected network call'); }};
  class MapStub { constructor(){this.sources={};} on(){} addControl(){} getSource(id){return this.sources[id];}
    addSource(id, data){this.sources[id]={data:data.data,setData(value){this.data=value;}};} getLayer(){return false;}
    addLayer(){} flyTo(){} getCanvas(){return {style:{}};} }
  class Popup { setHTML(){return this;} setLngLat(){return this;} addTo(){return this;} }
  class Marker { setLngLat(){return this;} setPopup(p){this.popup=p; return this;} addTo(){return this;} getPopup(){return this.popup;} remove(){} }
  context.maplibregl={Map:MapStub,NavigationControl:class{},ScaleControl:class{},Popup,Marker};
  vm.createContext(context);
  let source=fs.readFileSync(path.join(__dirname,'..',file),'utf8');
  if (file.includes('health_app')) source=source.split('// Boot')[0];
  vm.runInContext(source,context,{filename:file});
  return {c:context,el,run:code=>vm.runInContext(code,context),timers};
}
const response=(data, status=200)=>({ok:status<400,status,json:async()=>data});
function ready(h) {
  h.el('sub-phone').value='08012345678'; h.el('sub-consent').checked=true;
  h.run('_subLat=6.52; _subLon=3.37'); h.c.subCheckReady();
}

test('OTP is inline, locks its context, retries confirmation without resending', async()=>{
  const h=harness('dashboard/subscription.js'); ready(h);
  const calls=[];
  h.c.fetch=async(url, options)=>{ calls.push({url,body:JSON.parse(options.body)});
    return url.endsWith('/confirm') ? response({detail:'Wrong code.'},401) : response({status:'pending_confirmation',phone:'+2348012345678'}); };
  await h.c.submitSubscription();
  assert.equal(h.el('sub-otp-panel').hidden,false); assert.equal(h.el('sub-phone').disabled,true);
  h.el('sub-code').value='123'; await h.c.subConfirmCode(); assert.equal(calls.length,1);
  h.el('sub-code').value='123456'; await h.c.subConfirmCode();
  assert.equal(calls.length,2); assert.equal(calls[1].url,'/subscribe/confirm');
  assert.equal(calls[1].body.phone,'+2348012345678'); assert.match(h.el('sub-status').textContent,/Wrong code/);
  assert.equal(h.el('sub-otp-panel').hidden,false);
  h.c.subCancelConfirmation(); assert.equal(h.el('sub-phone').disabled,false);
});
test('double submission is prevented and only subscribed response shows success',async()=>{
  const h=harness('dashboard/subscription.js'); ready(h);
  let resolve, calls=0; h.c.fetch=()=>{ calls++; return new Promise(r=>resolve=r); };
  const first=h.c.submitSubscription(); await h.c.submitSubscription(); assert.equal(calls,1);
  resolve(response({status:'unexpected'})); await first;
  assert.equal(h.el('sub-status').className,'sub-status error'); assert.equal(h.el('sub-submit').disabled,false);
});
test('successful OTP clears pending code and personal form inputs',async()=>{
  const h=harness('dashboard/subscription.js'); ready(h);
  h.c.fetch=async()=>response({status:'pending_confirmation',phone:'+2348012345678'});
  await h.c.submitSubscription(); h.el('sub-code').value='123456';
  h.c.fetch=async()=>response({status:'subscribed',area_name:'Kosofe'}); await h.c.subConfirmCode();
  assert.equal(h.el('sub-otp-panel').hidden,true); assert.equal(h.el('sub-code').value,'');
  assert.equal(h.el('sub-phone').value,''); assert.equal(h.el('sub-submit').disabled,true);
});
test('uncovered location cannot enable signup',async()=>{
  const h=harness('dashboard/subscription.js'); ready(h); h.c.fetch=async()=>response({},404);
  await h.c.subSetLocation(0,0,'Outside');
  assert.equal(h.run('_subLat'),null); assert.equal(h.el('sub-submit').disabled,true);
});
test('latest location wins when coverage responses arrive out of order',async()=>{
  const h=harness('dashboard/subscription.js'); ready(h);
  let resolve; h.c.fetch=()=>new Promise(r=>resolve=r);
  const old=h.c.subSetLocation(6.5,3.3,'Old');
  h.c.fetch=async()=>response({risk_class:'High'}); await h.c.subSetLocation(6.6,3.4,'New');
  resolve(response({risk_class:'Low'})); await old;
  assert.equal(h.run('_subLat'),6.6); assert.match(h.el('sub-risk-preview').textContent,/New/);
});
test('changing location requires fresh confirmation of consent',async()=>{
  const h=harness('dashboard/subscription.js'); ready(h);
  h.c.fetch=async()=>response({risk_class:'Low'}); await h.c.subSetLocation(6.5,3.3,'New');
  assert.equal(h.el('sub-consent').checked,false); assert.equal(h.el('sub-submit').disabled,true);
});
test('typed locations require an explicit selection',async()=>{
  const h=harness('dashboard/subscription.js'); ready(h);
  h.c.fetch=async()=>response([{display_name:'Kosofe, Lagos',lat:6.52,lon:3.37}]);
  h.c.subGeocode('Kos'); await h.timers.at(-1)();
  assert.equal(h.run('_subLat'),null); assert.equal(h.el('sub-submit').disabled,true);
  assert.equal(h.el('sub-places').children.length,1);
});
function dashboard() {
  const h=harness('dashboard/app.js'); h.run(`_cachedGeojson={features:[{properties:{risk_class:'High'}}]}; _configReady=true`);
  h.el('rain24').value='90'; h.el('rain72').value='120';
  return h;
}
function live() { return {alert_levels:['No Alert'], alert_counts:{},forecast:{rain_24h_mm:0,rain_72h_mm:0,fetched_at:new Date().toISOString()}}; }

test('missing forecast timestamp cannot leave the map labelled live',()=>{
  const h=dashboard(); h.c.applyLiveAlerts(live()); h.c.setApiStatus(true);
  assert.match(h.el('map-mode').textContent,/STALE/);
  assert.match(h.el('api-status').textContent,/timestamp unavailable/);
});
test('old forecast timestamp cannot leave the map labelled live',()=>{
  const h=dashboard(); h.c.applyLiveAlerts(live()); h.c.setApiStatus(true,'2020-01-01T00:00:00Z');
  assert.match(h.el('map-mode').textContent,/STALE/);
});
test('future forecast timestamp cannot leave the map labelled live',()=>{
  const h=dashboard(); h.c.applyLiveAlerts(live()); h.c.setApiStatus(true,new Date(Date.now()+3600000).toISOString());
  assert.match(h.el('map-mode').textContent,/STALE/);
});
test('live refresh preserves scenario map and sliders; reset deliberately restores live',async()=>{
  const h=dashboard(); h.c.markManual(); h.c.applySliderAlerts();
  h.c.fetch=async()=>response(live()); await h.c.refreshAlerts();
  assert.equal(h.el('rain24').value,'90'); assert.equal(h.run('_cachedGeojson.features[0].properties.alert_level'),'Warning');
  assert.match(h.el('city-alert').textContent,/Scenario only/);
  h.el('reset-forecast').click();
  assert.equal(h.run('_scenarioMode'),false); assert.equal(h.run('_cachedGeojson.features[0].properties.alert_level'),'No Alert');
});
test('mismatched arrays do not partially recolour the map',()=>{
  const h=dashboard(); assert.throws(()=>h.c.applyLiveAlerts({...live(),alert_levels:[]}),/do not match/);
  assert.equal(h.run('_liveAlerts'),null);
});
test('invalid rainfall payload cannot appear as a live forecast',()=>{
  const h=dashboard(); assert.throws(()=>h.c.applyLiveAlerts({...live(),forecast:{rain_24h_mm:-1}}),/rainfall unavailable/);
  assert.equal(h.run('_liveAlerts'),null);
});
test('reset without live data removes hypothetical alert colours',()=>{
  const h=dashboard(); h.c.markManual(); h.c.applySliderAlerts(); h.el('reset-forecast').click();
  assert.equal(h.run('_cachedGeojson.features[0].properties.alert_level'),undefined);
  assert.match(h.el('map-mode').textContent,/STATIC/);
});
test('refresh failure stays visible and stale state survives scenario reset',async()=>{
  const h=dashboard(); h.c.applyLiveAlerts(live()); await h.c.refreshAlerts();
  assert.match(h.el('api-status').textContent,/Refresh failed/);
  h.c.markManual(); h.el('reset-forecast').click(); assert.match(h.el('map-mode').textContent,/STALE/);
});
test('search supports keyboard selection and escape without losing focus',()=>{
  const h=dashboard(); h.c.renderDropdown([{display_name:'Kosofe, Lagos',lat:6.5,lon:3.4}]);
  h.el('search-input').emit('keydown',{key:'ArrowDown',preventDefault(){}});
  assert.equal(h.el('search-input').attrs['aria-activedescendant'],'search-option-0');
  let selected=false; h.c.selectPlace=()=>{selected=true;};
  h.el('search-input').emit('keydown',{key:'Enter',preventDefault(){}}); assert.equal(selected,true);
  h.el('search-input').emit('keydown',{key:'Escape'}); assert.equal(h.el('search-input').attrs['aria-expanded'],'false');
});
test('older search response cannot replace a newer typed query',async()=>{
  const h=dashboard(); let resolve; h.el('search-input').value='Old'; h.c.fetch=()=>new Promise(r=>resolve=r);
  const first=h.c.doSearch('Old'); h.el('search-input').value='New';
  h.c.fetch=async()=>response([{display_name:'New, Lagos',lat:6.5,lon:3.3}]); await h.c.doSearch('New');
  resolve(response([{display_name:'Old, Lagos',lat:6.6,lon:3.4}])); await first;
  assert.match(h.el('search-results').innerHTML,/New/); assert.doesNotMatch(h.el('search-results').innerHTML,/Old/);
});
test('external search text is escaped before insertion',()=>{
  const h=dashboard(); h.c.renderDropdown([{display_name:'<img src=x onerror=alert(1)>',lat:6.5,lon:3.3}]);
  assert.doesNotMatch(h.el('search-results').innerHTML,/<img/);
  assert.match(h.el('search-results').innerHTML,/&lt;img/);
});
test('point scenario does not alter city beacon and stale point responses are discarded',async()=>{
  const h=dashboard(); h.el('beacon').dataset.level='Watch'; let resolves=[];
  h.c.fetch=()=>new Promise(r=>resolves.push(r)); const first=h.c.queryPoint(6.5,3.3,'Old');
  h.c.fetch=async url=>response(url.includes('risk/point')?{risk_class:'Low',elevation_m:1,hazard_score:0.2}:{alert_level:'No Alert'});
  await h.c.queryPoint(6.6,3.4,'New');
  resolves[0](response({risk_class:'High',elevation_m:2,hazard_score:0.7})); resolves[1](response({alert_level:'Warning'})); await first;
  assert.equal(h.el('result-location').textContent,'New'); assert.equal(h.el('beacon').dataset.level,'Watch');
});
test('clearing operator access discards in-flight private responses',async()=>{
  const h=harness('dashboard/health/health_app.js'); h.run("operatorToken='test-only'");
  let resolve; h.c.fetch=()=>new Promise(r=>resolve=r);
  const result=h.c.supabaseFetch('chew_responses'); h.run("operatorToken=''");
  resolve(response([{private:'test'}])); await assert.rejects(result,/stale report discarded/);
});
