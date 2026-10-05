// Real headless browser, local pages and mocked API/map renderer. Not device/load or live-provider acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base='http://127.0.0.1:8765';
const fc={rain_24h_mm:0,rain_72h_mm:0,fetched_at:new Date().toISOString()};
const fakeMap=`class M{constructor(){this.sources={}}on(name,...args){if(name==='load')setTimeout(args.at(-1),30);return this}
addControl(){}getZoom(){return 10}getCanvas(){return {style:{}}}getLayer(){return null}removeLayer(){}removeSource(){}
addSource(id,data){this.sources[id]={setData(){}}}getSource(id){return this.sources[id]}addLayer(){}flyTo(){}setLayoutProperty(){}}
class P{setLngLat(){return this}setHTML(){return this}addTo(){return this}}
class K{setLngLat(){return this}setPopup(p){this.p=p;return this}getPopup(){return this.p}addTo(){return this}remove(){}}
window.maplibregl={Map:M,NavigationControl:class{},ScaleControl:class{},Popup:P,Marker:K};`;
async function main(){
  const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE || undefined});
  const checks=[], errors=[];
  try {
    const context=await browser.newContext({viewport:{width:1280,height:900},reducedMotion:'reduce'});
    let confirms=0, subscriptions=0;
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url()), p=url.pathname;
      if(url.hostname==='unpkg.com' && p.endsWith('maplibre-gl.js')) return route.fulfill({contentType:'application/javascript',body:fakeMap});
      if(url.origin!==base) return route.abort();
      let data;
      if(p==='/product-status') data={alert_thresholds:{},risk_breaks:{Low:[0,0.5]},experimental_depth_enabled:false};
      else if(p==='/forecast/alerts') data={alert_levels:['No Alert'],alert_counts:{'No Alert':1},forecast:fc};
      else if(p==='/forecast/rainfall') data=fc;
      else if(p==='/risk/grid') data={type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'Polygon',coordinates:[[[3.37,6.52],[3.38,6.52],[3.38,6.53],[3.37,6.52]]]},properties:{cell_id:'test',risk_class:'High',hazard_score:0.7}}]};
      else if(p==='/risk/point') data={risk_class:'High',hazard_score:0.7,elevation_m:2};
      else if(p==='/alerts/current') data={alert_level:'Watch'};
      else if(p==='/places/search') data=[{display_name:'Kosofe, Lagos',lat:6.52,lon:3.37}];
      else if(p==='/subscribe' && route.request().method()==='POST') {subscriptions++; data={status:'pending_confirmation',phone:'+2348012345678'};}
      else if(p==='/subscribe/confirm') {confirms++; data=confirms===1?{detail:'Wrong code.'}:{status:'subscribed',area_name:'Kosofe'};
        return route.fulfill({status:confirms===1?401:200,json:data});}
      else if(p==='/forecast/summary') data={forecast:fc,alert_counts:{},highest_alert:'No Alert'};
      else if(p==='/subscribe/count') data={count:0};
      else if(p==='/risk/streets' || p==='/risk/swmm') data={type:'FeatureCollection',features:[]};
      else if(p.startsWith('/health/')) data={lgas:[],computed_at:fc.fetched_at};
      else return route.continue();
      return route.fulfill({json:data});
    });
    const page=await context.newPage(); page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/dashboard/'); await page.waitForFunction(()=>!document.getElementById('rain24').disabled);
    await page.locator('#rain24').evaluate(el=>{el.value='90';el.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.locator('#refresh-forecast').click();
    await page.waitForFunction(()=>!document.getElementById('refresh-forecast').disabled);
    assert.match(await page.locator('#map-mode').textContent(),/SCENARIO/);
    await page.locator('#reset-forecast').click(); assert.match(await page.locator('#map-mode').textContent(),/Live forecast/);
    checks.push('Scenario refresh and deliberate return to live');
    await page.locator('#search-input').fill('Kos'); await page.locator('#search-option-0').waitFor();
    await page.locator('#search-input').press('ArrowDown'); await page.locator('#search-input').press('Enter');
    await page.waitForFunction(()=>document.getElementById('result-location').textContent.includes('Kosofe'));
    checks.push('Keyboard LGA selection and location result');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    checks.push('Dashboard 390px viewport has no horizontal overflow');
    await page.goto(base+'/floodsight.html#subscribe');
    await page.locator('#sub-phone').fill('08012345678'); await page.locator('#sub-area').fill('Kos');
    await page.locator('#sub-places button').waitFor();
    assert.equal(await page.locator('#sub-submit').isDisabled(),true);
    await page.locator('#sub-places button').click();
    await page.waitForFunction(()=>document.getElementById('sub-risk-preview').textContent.includes('Selected:'));
    await page.locator('#sub-consent').check(); await page.locator('#sub-submit').click();
    await page.locator('#sub-code').waitFor({state:'visible'}); await page.locator('#sub-code').fill('123456');
    await page.locator('#sub-code').press('Enter');
    await page.waitForFunction(()=>document.getElementById('sub-status').textContent.includes('Wrong code'));
    assert.equal(subscriptions,1);
    await page.locator('#sub-code').press('Enter');
    await page.waitForFunction(()=>document.getElementById('sub-status').textContent.includes('Subscribed for'));
    assert.equal(subscriptions,1); assert.equal(confirms,2);
    assert.equal(await page.locator('#sub-phone').inputValue(),'');
    checks.push('Explicit location, inline OTP, wrong-code retry without another SMS request');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    checks.push('Signup 390px viewport has no horizontal overflow');
    await page.goto(base+'/dashboard/health/');
    await page.locator('#operator-access summary').click(); await page.locator('#operator-token').fill('test-only');
    await page.locator('#operator-form button[type=submit]').click();
    assert.equal(await page.locator('#operator-token').inputValue(),'');
    await page.locator('#operator-signout').click();
    assert.match(await page.locator('#operator-status').textContent(),/cleared/);
    checks.push('Inline operator access and token clearing');
    await context.unroute('**/*');
    await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    await page.goto(base+'/dashboard/');
    await page.waitForFunction(()=>document.getElementById('api-status').textContent.includes('Map unavailable'));
    assert.equal(await page.locator('#rain24').isDisabled(),true);
    checks.push('Unavailable map dependency explicitly disables unsupported controls');
    assert.deepEqual(errors,[]);
    const report={date:'2026-10-05',status:'passed',browser:'Headless Chromium-compatible browser',
      scope:'Local pages; API, SMS, database and map renderer mocked; external requests blocked',
      checks,limitations:['Not actual map rendering or target-device acceptance','Not load, live SMS, backup restoration or scientific approval']};
    fs.writeFileSync(path.join(__dirname,'../reports/ux_browser_verification.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
