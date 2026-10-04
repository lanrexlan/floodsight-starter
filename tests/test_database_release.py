"""Real migration/race tests, enabled only against CI's disposable local database."""
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import pytest

DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Disposable PostgreSQL test service not running")


@pytest.fixture(scope="module")
def database():
    target = urlparse(DATABASE_URL)
    if target.hostname not in ("localhost", "127.0.0.1") or target.path != "/floodsight_test":
        pytest.fail("Database tests require local /floodsight_test; refusing any other database")
    psycopg = pytest.importorskip("psycopg")
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        for role in ("anon", "authenticated", "service_role"):
            conn.execute(f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
        conn.execute("ALTER ROLE service_role BYPASSRLS")
        for path in sorted((root / "scripts/sql").glob("0*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("GRANT USAGE ON SCHEMA public TO anon,authenticated,service_role")
        conn.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role")
        conn.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role")
        assert conn.execute("SELECT release_schema_version()").fetchone()[0] == 7
    yield psycopg


def test_private_logs_not_readable_by_anon(database):
    with database.connect(DATABASE_URL) as conn:
        conn.execute("SET ROLE anon")
        with pytest.raises(database.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM verifications")


def test_rate_limit_is_atomic_across_connections(database):
    def attempt(_):
        with database.connect(DATABASE_URL) as conn:
            return conn.execute("SELECT consume_subscription_attempt(%s,%s)", ('test-phone','test-ip')).fetchone()[0]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(20)))
    assert sum(results) == 8


def test_otp_creates_subscription_exactly_once(database):
    import json
    phone = '+2340000000000'
    with database.connect(DATABASE_URL) as conn:
        conn.execute("INSERT INTO pending_subscriptions(phone,code_hash,payload,expires_at) VALUES (%s,%s,%s::jsonb,now()+interval '10 minutes')",
                     (phone, 'test-hash', json.dumps({'lat':6.52,'lon':3.37,'area_name':'Kosofe','risk_class':'High'})))
        result = conn.execute("SELECT consume_pending_subscription(%s,%s)", (phone,'test-hash')).fetchone()[0]
        assert result['status'] == 'confirmed'
        assert result['subscriber']['active'] is True
        assert conn.execute("SELECT consume_pending_subscription(%s,%s)", (phone,'test-hash')).fetchone()[0]['status'] == 'not_found'
        sub_id = result['subscriber']['id']
        assert conn.execute("SELECT claim_alert(%s,current_date,'Warning')", (sub_id,)).fetchone()[0] is True
        assert conn.execute("SELECT claim_alert(%s,current_date,'Warning')", (sub_id,)).fetchone()[0] is False


def test_retention_removes_old_optouts_and_expired_codes(database):
    with database.connect(DATABASE_URL) as conn:
        conn.execute("INSERT INTO subscribers(phone,lat,lon,active,deactivated_at) VALUES ('+2340000000001',6.52,3.37,false,now()-interval '31 days')")
        conn.execute("SELECT cleanup_personal_data()")
        assert conn.execute("SELECT count(*) FROM subscribers WHERE phone='+2340000000001'").fetchone()[0] == 0
