"""Pure synthetic tests: no archive, credentials, directory or DB access."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'local_restore_drill', Path(__file__).resolve().parents[1] / 'scripts/ops/local_restore_drill.py')
DRILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRILL)


def synthetic_archive():
    tables = ['alert_log', 'briefing_log', 'chew_responses', 'chew_subscribers',
              'dhis2_malaria_cases', 'dispatch_cells', 'entomology_observations',
              'health_alerts', 'lga_health_risk', 'mel_events', 'pending_subscriptions',
              'prediction_log', 'subscribers', 'verifications']
    return ''.join(f'COPY public.{t} (id, area_km2) FROM stdin;\n1\ttext\u2028kept\\ntext\n\\.\n' for t in tables)


def test_copy_parser_preserves_unicode_and_digit_columns():
    parsed = DRILL.archive_rows(synthetic_archive())
    assert len(parsed) == 14
    assert parsed['subscribers'][0] == ('id', 'area_km2')
    assert parsed['subscribers'][1] == ['1\ttext\u2028kept\\ntext'.encode('utf-8')]


def test_copy_parser_rejects_incomplete_archive():
    with pytest.raises(RuntimeError, match='Unterminated COPY'):
        DRILL.archive_rows('COPY public.subscribers (id) FROM stdin;\n1\n')


def test_copy_parser_accepts_exact_release_table_set():
    text = synthetic_archive() + ''.join(
        f'COPY public.{t} (id) FROM stdin;\n\\.\n'
        for t in ('alert_claims', 'subscription_attempts'))
    parsed = DRILL.archive_rows(text, expected_tables=DRILL.RELEASE_TABLES)
    assert set(parsed) == DRILL.RELEASE_TABLES
    assert parsed['alert_claims'][1] == []
    with pytest.raises(RuntimeError, match='Archived table set'):
        DRILL.archive_rows(text)


def test_copy_parser_rejects_wrong_names_even_with_same_count():
    text = synthetic_archive().replace('public.alert_log ', 'public.other_table ')
    with pytest.raises(RuntimeError, match='Archived table set'):
        DRILL.archive_rows(text)
    with pytest.raises(RuntimeError, match='Source table set'):
        DRILL.archive_rows(text, expected_tables={'other_table'})


def test_row_digest_ignores_order_but_not_duplicates_or_boundaries():
    assert DRILL.rows_digest([b'a', b'b']) == DRILL.rows_digest([b'b', b'a'])
    assert DRILL.rows_digest([b'a']) != DRILL.rows_digest([b'a', b'a'])
    assert DRILL.rows_digest([b'ab', b'c']) != DRILL.rows_digest([b'a', b'bc'])


def test_pg18_constraint_mapping_requires_equivalent_nullability():
    source = {'postgres_version':'17.6','constraints':[],
              'columns':[{'table':'example','column':'id','nullable':'NO'}]}
    target = {'postgres_version':'18.3','constraints':[
        {'table':'example','name':'example_id_not_null','kind':'n',
         'definition':'NOT NULL id','validated':True}]}
    assert DRILL.constraint_equivalence(source,target)
    target['constraints'][0]['validated'] = False
    assert not DRILL.constraint_equivalence(source,target)
    target['constraints'][0]['validated'] = True
    target['constraints'][0]['definition'] = 'NOT NULL other'
    assert not DRILL.constraint_equivalence(source,target)
