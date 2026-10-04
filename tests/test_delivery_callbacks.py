"""Delivery reports must reach the actual audience table or be retried."""
from types import SimpleNamespace

import pytest

from floodsight.db import supabase_client as db


class DeliveryClient:
    def __init__(self, match=None, failing=()):
        self.match = match
        self.failing = failing
        self.tables = []
        self.patches = []

    def table(self, name):
        self.current = name
        self.tables.append(name)
        return self

    def update(self, patch):
        self.patches.append(dict(patch))
        return self

    def eq(self, column, value):
        assert (column, value) == ('at_message_id', 'test-message')
        return self

    def execute(self):
        if self.current in self.failing:
            raise RuntimeError('test database unavailable')
        return SimpleNamespace(data=[{'id':'test'}] if self.current == self.match else [])


@pytest.mark.parametrize('table', ['alert_log', 'health_alerts'])
def test_callback_updates_actual_audience(monkeypatch, table):
    client = DeliveryClient(match=table)
    monkeypatch.setattr(db, '_get_client', lambda:client)
    assert db.record_delivery_report('test-message', 'Success') == table
    assert 'delivered_at' in client.patches[-1]
    assert 'health_alert_log' not in client.tables


def test_unknown_welcome_or_otp_message_is_not_an_error(monkeypatch):
    monkeypatch.setattr(db, '_get_client', lambda:DeliveryClient())
    assert db.record_delivery_report('test-message', 'Success') == 'not_found'


def test_storage_failure_is_not_acknowledged(monkeypatch):
    monkeypatch.setattr(db, '_get_client', lambda:DeliveryClient(failing=['health_alerts']))
    with pytest.raises(RuntimeError, match='please retry'):
        db.record_delivery_report('test-message', 'Success')
