"""Regression checks for externally observable launch failures. No live services."""
import json
from datetime import date

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box


@pytest.fixture
def client(monkeypatch):
    # The local .env belongs to the user: no test may use its credentials.
    from api.main import app
    from api import data_provider as data
    from api.assets import encoded_map
    from api.routers import subscribe
    monkeypatch.setenv("FLOODSIGHT_ENV", "development")
    monkeypatch.setenv("DISPATCH_SECRET", "test-only")
    monkeypatch.setenv("VERIFY_SECRET", "test-only")
    monkeypatch.setenv("AT_WEBHOOK_TOKEN", "test-webhook")
    monkeypatch.setenv("REQUIRE_OTP", "false")
    grid = gpd.GeoDataFrame([{"cell_id":"cell-1", "elevation_m":2., "flood_score":.8,
        "risk_class":"Very High", "lga_name":"Kosofe", "geometry":box(3.36,6.51,3.38,6.53)}], crs="EPSG:4326").to_crs("EPSG:32631")
    monkeypatch.setattr(data, "_cached_grid", grid)
    monkeypatch.setattr(data, "_cached_source", "processed_pipeline")
    monkeypatch.setattr(data, "_cached_grid_geojson", None)
    monkeypatch.setattr("api.assets.prepared_asset", lambda name: None)
    encoded_map.cache_clear()
    subscribe._phone_windows.clear()
    subscribe._ip_windows.clear()
    yield TestClient(app)
    encoded_map.cache_clear()


@pytest.mark.parametrize("lat,lon", [(999,999), (51.5,-.1), (6.32,3.02), (float('nan'),3.37)])
def test_point_rejects_invalid_or_unmapped_locations(client, lat, lon):
    assert client.get('/risk/point', params={"lat":lat,"lon":lon}).status_code == 422


def test_risk_lookup_and_compact_map_preserve_order(client):
    assert client.get('/risk/point?lat=6.52&lon=3.37').json()['cell_id'] == 'cell-1'
    result = client.get('/risk/grid')
    assert result.status_code == 200
    assert result.json()['features'][0]['properties']['cell_id'] == 'cell-1'
    assert 'flow_accum' not in result.json()['features'][0]['properties']
    assert client.get('/risk/grid', headers={'If-None-Match': result.headers['etag']}).status_code == 304


@pytest.mark.parametrize("body", [
    {"lat":6.52,"lon":3.37,"rain_24h_mm":-1,"rain_72h_mm":0},
    {"lat":51.5,"lon":-.1,"rain_24h_mm":0,"rain_72h_mm":0},
])
def test_alert_inputs_rejected(client, body):
    assert client.post('/alerts/current', json=body).status_code == 422


@pytest.mark.parametrize('consent', [None, False])
def test_missing_consent_cannot_subscribe(client, consent):
    body = {"phone":"08012345678","lat":6.52,"lon":3.37}
    if consent is not None:
        body['consent'] = consent
    assert client.post('/subscribe', json=body).status_code == 422


def test_cors_rejects_untrusted_origin_and_limits_body(client):
    result = client.options('/subscribe', headers={'Origin':'https://attacker.example','Access-Control-Request-Method':'POST'})
    assert result.status_code == 400
    assert 'access-control-allow-origin' not in result.headers
    assert client.post('/subscribe', content='x'*70000).status_code == 413


def test_private_logs_and_webhooks_require_auth(client):
    assert client.get('/depth/predictions_log').status_code == 401
    assert client.get('/health/activity').status_code == 401
    assert client.post('/health/chew-response', json={'from':'+2348012345678','text':'CONFIRM'}).status_code == 401
    assert 'HTTPBearer' in client.get('/openapi.json').json()['components']['securitySchemes']


def test_verification_storage_failure_does_not_acknowledge_success(client, monkeypatch, tmp_path):
    monkeypatch.setenv('FLOODSIGHT_ENV','production')
    def unavailable(*args, **kwargs):
        raise RuntimeError('offline')
    monkeypatch.setattr('floodsight.db.supabase_client.add_verification', unavailable)
    monkeypatch.setattr('api.routers.verify.LOGS_DIR', tmp_path)
    result = client.post('/verify', json={"lat":6.52,"lon":3.37,"event_date":date.today().isoformat(),"observed_flooded":True}, headers={'Authorization':'Bearer test-only'})
    assert result.status_code == 503
    assert not list(tmp_path.iterdir())


def test_forecast_rejects_outside_before_any_network(client):
    assert client.get('/forecast/rainfall?lat=51.5&lon=-.1').status_code == 422


def test_local_search_and_privacy_page(client):
    assert client.get('/places/search?q=Kosofe').json()[0]['display_name'].startswith('Kosofe')
    assert client.get('/dashboard/privacy.html').status_code == 200


def test_event_identity_and_provenance_not_guessed():
    import pandas as pd
    from floodsight.ml.provenance import normalize_dataset
    result = normalize_dataset(pd.DataFrame({'event':['lekki_a','lekki_b'], 'event_name':['',None]}))
    assert result.event_name.tolist() == ['lekki_a','lekki_b']
    assert set(result.label_source) == {'unknown'}
    with pytest.raises(ValueError):
        normalize_dataset(pd.DataFrame({'event':['a'],'event_name':['b']}))


def test_production_startup_fails_closed(monkeypatch):
    from api.release import startup_errors
    monkeypatch.setenv('FLOODSIGHT_ENV','production')
    monkeypatch.setenv('CORS_ORIGINS','*')
    monkeypatch.setenv('REQUIRE_OTP','false')
    monkeypatch.setenv('DATA_PROVIDER_LICENSES_CONFIRMED','false')
    errors = startup_errors()
    assert any('wildcard' in err for err in errors)
    assert any('OTP' in err for err in errors)
    assert any('agreements' in err for err in errors)


def test_dispatch_dry_run_uses_shared_forecast_without_messages(client, monkeypatch):
    expected = {'alert_levels':['Warning'], 'alert_counts':{'Warning':1}, 'highest_alert':'Warning'}
    monkeypatch.setattr('api.routers.forecast.get_grid_alerts', lambda *args: expected)
    def forbidden(*args, **kwargs):
        raise AssertionError('Dry-run must not contact subscribers or send messages')
    monkeypatch.setattr('floodsight.db.supabase_client.get_active_subscribers', forbidden)
    monkeypatch.setattr('floodsight.notifications.sms.send_sms', forbidden)
    result = client.post('/alerts/dispatch?dry_run=true', headers={'Authorization':'Bearer test-only'})
    assert result.status_code == 200
    assert result.json()['alert_counts'] == expected['alert_counts']
    assert result.json()['sent'] == 0


def test_bulk_testing_cannot_bypass_production_approval(client, monkeypatch):
    monkeypatch.setenv('FLOODSIGHT_ENV','production')
    assert client.post('/alerts/dispatch/force', headers={'Authorization':'Bearer test-only'}).status_code == 403
    assert client.post('/alerts/test-sms?phone=08012345678', headers={'Authorization':'Bearer test-only'}).status_code == 403


def test_packaged_lga_mapping_works_without_raw_downloads(monkeypatch, tmp_path):
    from api import data_provider as data
    from floodsight import config
    import hashlib
    grid_file = tmp_path/'grid.gpkg'
    grid_file.write_bytes(b'test-grid-identity')
    (tmp_path/'lga_index.json').write_text(json.dumps({
        'source_sha256':hashlib.sha256(grid_file.read_bytes()).hexdigest(),
        'cells':{'a':'Kosofe', 'b':None}}))
    monkeypatch.setattr(config,'RAW_DIR',tmp_path/'missing-raw')
    monkeypatch.setattr(data,'PROCESSED_DIR',tmp_path)
    monkeypatch.setattr(data,'SCORED_GRID_PATH',grid_file)
    grid = gpd.GeoDataFrame({'cell_id':['a','b']}, geometry=[box(0,0,1,1),box(1,1,2,2)],crs='EPSG:4326')
    result = data._tag_lga_names(grid)
    assert result.lga_name.iloc[0] == 'Kosofe'
    assert result.lga_name.isna().iloc[1]
    grid_file.write_bytes(b'changed-grid')
    with pytest.raises(RuntimeError, match='does not match'):
        data._tag_lga_names(grid)


def test_boundary_split_cell_ids_remain_distinct_and_stable():
    from api.data_provider import _ensure_unique_cell_ids
    grid = gpd.GeoDataFrame({'cell_id':['a','a','b']}, geometry=[box(0,0,1,1)]*3, crs='EPSG:4326')
    result = _ensure_unique_cell_ids(grid)
    assert result.cell_id.tolist() == ['a@row=0','a@row=1','b']
    assert _ensure_unique_cell_ids(grid).cell_id.tolist() == result.cell_id.tolist()
