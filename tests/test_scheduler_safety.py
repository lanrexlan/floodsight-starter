from types import SimpleNamespace

import pytest

from scripts import send_health_alerts, send_morning_briefing


def test_disabled_health_dispatch_never_fetches(monkeypatch):
    import requests
    monkeypatch.delenv('HEALTH_DISPATCH_ENABLED', raising=False)
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('Disabled dispatch fetched data'))
    assert send_health_alerts.main() == 1


def test_misaligned_health_grid_refuses_partial_scoring(monkeypatch):
    import requests
    payloads = iter([{'alert_levels':['Warning']}, {'features':[]}])
    monkeypatch.setattr(requests, 'get', lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: next(payloads)))
    assert send_health_alerts.main(dry_run=True) == 1


def briefing_environment(monkeypatch):
    monkeypatch.setattr('sys.argv', ['briefing'])
    monkeypatch.setenv('BRIEFING_DISPATCH_ENABLED', 'true')
    monkeypatch.setenv('SUPABASE_URL', 'https://invalid.test')
    monkeypatch.setenv('SUPABASE_KEY', 'local-test-only')
    monkeypatch.setenv('AT_RECIPIENTS', '+2348000000000')
    import floodsight.db.supabase_client as db
    monkeypatch.setattr(db, 'briefing_sent_today', lambda: False)
    monkeypatch.setattr(send_morning_briefing, 'fetch_summary', lambda *a: pytest.fail('Unsafe recipient path fetched forecast'))
    return db


def test_empty_store_never_falls_back_to_recipient_list(monkeypatch):
    db = briefing_environment(monkeypatch)
    monkeypatch.setattr(db, 'get_active_subscribers', lambda: [])
    send_morning_briefing.main()


def test_failed_store_never_falls_back_to_recipient_list(monkeypatch):
    db = briefing_environment(monkeypatch)
    def unavailable():
        raise RuntimeError('unavailable')
    monkeypatch.setattr(db, 'get_active_subscribers', unavailable)
    with pytest.raises(SystemExit) as error:
        send_morning_briefing.main()
    assert error.value.code == 1


def test_briefing_no_alert_is_not_an_all_clear():
    message = send_morning_briefing.format_message({'forecast':{'rain_24h_mm':0,'rain_72h_mm':0},
                                                  'alert_counts':{},'highest_alert':'No Alert'})
    assert 'All Clear' not in message
    assert 'flooding is still possible' in message


def test_briefing_does_not_invent_affected_places():
    message = send_morning_briefing.format_message({'forecast':{'rain_24h_mm':90,'rain_72h_mm':120},
                                                  'alert_counts':{'Warning':10000},'highest_alert':'Warning'})
    assert 'Areas:' not in message
    assert 'Alert areas:' not in message


def test_briefing_ledger_failure_refuses_send(monkeypatch):
    db = briefing_environment(monkeypatch)
    def unavailable():
        raise RuntimeError('unavailable')
    monkeypatch.setattr(db, 'briefing_sent_today', unavailable)
    monkeypatch.setattr(db, 'get_active_subscribers', lambda: pytest.fail('Must not proceed past failed ledger'))
    with pytest.raises(SystemExit) as error:
        send_morning_briefing.main()
    assert error.value.code == 1


def test_briefing_claims_use_separate_namespace_and_skip_retries(monkeypatch):
    import floodsight.db.supabase_client as db
    claims = set()
    def claim(identifier, event_date, level):
        assert level == 'Briefing'
        key = (identifier, event_date, level)
        if key in claims:
            return False
        claims.add(key)
        return True
    monkeypatch.setattr(db, 'claim_alert', claim)
    monkeypatch.setattr(db, 'today_lagos', lambda: '2026-10-05')
    subscribers = [{'id':'first','phone':'+2348000000000'}, {'id':'second','phone':'+2348000000001'}]
    assert len(send_morning_briefing.reserve_briefing_recipients(subscribers)) == 2
    assert send_morning_briefing.reserve_briefing_recipients(subscribers) == []


def test_active_recipient_query_excludes_legacy_missing_consent(monkeypatch):
    import floodsight.db.supabase_client as db
    class Query:
        def table(self, *args): return self
        def select(self, fields):
            assert 'consent_at' in fields
            return self
        def eq(self, *args): return self
        def execute(self):
            return SimpleNamespace(data=[{'id':'valid','consent_at':'2026-10-05'}, {'id':'legacy','consent_at':None}])
    monkeypatch.setattr(db, '_get_client', Query)
    assert db.get_active_subscribers() == [{'id':'valid','consent_at':'2026-10-05'}]
