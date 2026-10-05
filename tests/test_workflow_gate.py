import pytest
from scripts.workflow_gate import decide, main


@pytest.mark.parametrize("enabled", ["", "false", "0", "yes", "1"])
def test_disabled_schedule_pauses_without_error(enabled):
    assert decide("schedule", "", enabled) == ("paused", False, 0)


def test_manual_read_only_does_not_need_send_approval():
    assert decide("workflow_dispatch", "true", "") == ("read_only", True, 0)


@pytest.mark.parametrize("dry", ["", "False", "arbitrary"])
def test_invalid_manual_mode_cannot_send(dry):
    assert decide("workflow_dispatch", dry, "true")[1:] == (False, 1)


def test_live_requires_explicit_approval():
    assert decide("workflow_dispatch", "false", "")[1:] == (False, 1)
    assert decide("schedule", "", "true") == ("approved_live", True, 0)
    assert decide("workflow_dispatch", "false", "true") == ("approved_live", True, 0)
    assert decide("push", "true", "true")[1:] == (False, 1)


def test_gate_receipt_without_secrets(monkeypatch, tmp_path):
    output, summary = tmp_path / 'output', tmp_path / 'summary'
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'schedule')
    monkeypatch.delenv('CHANNEL_ENABLED', raising=False)
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    assert main() == 0
    assert output.read_text() == 'run=false\nmode=paused\n'
    assert 'No API calls' in summary.read_text()
