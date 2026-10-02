from shared.contracts.models import PipelineStatus, AutomationMode
from services.orchestrator.app.state_machine import is_valid_transition, can_advance_mode


def test_valid_sequential_transitions():
    assert is_valid_transition(PipelineStatus.DISCOVERED, PipelineStatus.NORMALIZED)
    assert is_valid_transition(PipelineStatus.NORMALIZED, PipelineStatus.MATCHED)
    assert is_valid_transition(PipelineStatus.MATCHED, PipelineStatus.QUALIFIED)
    assert is_valid_transition(PipelineStatus.QUALIFIED, PipelineStatus.DOCUMENTS_READY)
    assert is_valid_transition(PipelineStatus.DOCUMENTS_READY, PipelineStatus.FORM_ANALYZED)
    assert is_valid_transition(PipelineStatus.FORM_ANALYZED, PipelineStatus.READY_TO_APPLY)
    assert is_valid_transition(PipelineStatus.READY_TO_APPLY, PipelineStatus.FILLING)
    assert is_valid_transition(PipelineStatus.FILLING, PipelineStatus.SUBMITTING)
    assert is_valid_transition(PipelineStatus.SUBMITTING, PipelineStatus.SUBMITTED)
    assert is_valid_transition(PipelineStatus.SUBMITTED, PipelineStatus.VERIFIED)


def test_invalid_transitions():
    # Direct jump from DISCOVERED to SUBMITTED must be rejected
    assert not is_valid_transition(PipelineStatus.DISCOVERED, PipelineStatus.SUBMITTED)
    # Cannot jump backwards from VERIFIED
    assert not is_valid_transition(PipelineStatus.VERIFIED, PipelineStatus.FILLING)
    # DUPLICATE is terminal
    assert not is_valid_transition(PipelineStatus.DUPLICATE, PipelineStatus.READY_TO_APPLY)


def test_failure_and_blocked_transitions():
    # Application can enter FAILED or BLOCKED from active operational states
    assert is_valid_transition(PipelineStatus.READY_TO_APPLY, PipelineStatus.FAILED)
    assert is_valid_transition(PipelineStatus.READY_TO_APPLY, PipelineStatus.BLOCKED)
    # FAILED and BLOCKED can transition back to READY_TO_APPLY upon resolution/retry
    assert is_valid_transition(PipelineStatus.FAILED, PipelineStatus.READY_TO_APPLY)
    assert is_valid_transition(PipelineStatus.BLOCKED, PipelineStatus.READY_TO_APPLY)


def test_discovery_only_mode():
    mode = AutomationMode.DISCOVERY_ONLY
    allowed, _ = can_advance_mode(PipelineStatus.NORMALIZED, mode)
    assert allowed

    blocked, reason = can_advance_mode(PipelineStatus.MATCHED, mode)
    assert not blocked
    assert "halts before matching" in reason


def test_prepare_application_mode():
    mode = AutomationMode.PREPARE_APPLICATION
    # Allowed up to READY_TO_APPLY
    allowed, _ = can_advance_mode(PipelineStatus.READY_TO_APPLY, mode)
    assert allowed

    # Cannot proceed to FILLING or SUBMITTING
    blocked, reason = can_advance_mode(PipelineStatus.FILLING, mode)
    assert not blocked
    assert "halts at READY_TO_APPLY" in reason


def test_full_auto_mode():
    mode = AutomationMode.FULL_AUTO
    # If auto_submit is False, cannot submit
    blocked, reason = can_advance_mode(PipelineStatus.SUBMITTING, mode, auto_submit=False)
    assert not blocked
    assert "requires explicit AUTO_SUBMIT=true" in reason

    # If auto_submit is True, allowed
    allowed, _ = can_advance_mode(PipelineStatus.SUBMITTING, mode, auto_submit=True)
    assert allowed
