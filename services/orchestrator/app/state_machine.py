from typing import Optional, Set, Tuple, Dict
from shared.contracts.models import PipelineStatus, AutomationMode


# Allowed state transitions in the pipeline
VALID_TRANSITIONS: Dict[PipelineStatus, Set[PipelineStatus]] = {
    PipelineStatus.DISCOVERED: {
        PipelineStatus.NORMALIZED,
        PipelineStatus.FAILED,
        PipelineStatus.DUPLICATE,
    },
    PipelineStatus.NORMALIZED: {
        PipelineStatus.MATCHED,
        PipelineStatus.FAILED,
        PipelineStatus.DUPLICATE,
    },
    PipelineStatus.MATCHED: {
        PipelineStatus.QUALIFIED,
        PipelineStatus.FAILED,
        PipelineStatus.BLOCKED,
    },
    PipelineStatus.QUALIFIED: {
        PipelineStatus.DOCUMENTS_READY,
        PipelineStatus.DOC_REVIEW_REQUIRED,
        PipelineStatus.FAILED,
        PipelineStatus.BLOCKED,
    },
    PipelineStatus.DOC_REVIEW_REQUIRED: {
        PipelineStatus.DOCUMENTS_READY,
        PipelineStatus.QUALIFIED,
        PipelineStatus.FAILED,
        PipelineStatus.BLOCKED,
    },
    PipelineStatus.DOCUMENTS_READY: {
        PipelineStatus.FORM_ANALYZED,
        PipelineStatus.FAILED,
        PipelineStatus.BLOCKED,
    },
    PipelineStatus.FORM_ANALYZED: {
        PipelineStatus.READY_TO_APPLY,
        PipelineStatus.FAILED,
        PipelineStatus.BLOCKED,
    },
    PipelineStatus.READY_TO_APPLY: {
        PipelineStatus.FILLING,
        PipelineStatus.BLOCKED,
        PipelineStatus.FAILED,
    },
    PipelineStatus.FILLING: {
        PipelineStatus.SUBMITTING,
        PipelineStatus.BLOCKED,
        PipelineStatus.FAILED,
    },
    PipelineStatus.SUBMITTING: {
        PipelineStatus.SUBMITTED,
        PipelineStatus.BLOCKED,
        PipelineStatus.FAILED,
    },
    PipelineStatus.SUBMITTED: {
        PipelineStatus.VERIFIED,
        PipelineStatus.FAILED,
    },
    PipelineStatus.VERIFIED: set(),
    PipelineStatus.FAILED: {
        PipelineStatus.DISCOVERED,
        PipelineStatus.READY_TO_APPLY,
    },
    PipelineStatus.BLOCKED: {
        PipelineStatus.READY_TO_APPLY,
    },
    PipelineStatus.DUPLICATE: set(),
}


def is_valid_transition(
    current: PipelineStatus,
    target: PipelineStatus,
) -> bool:
    """Verifies whether transition from current to target status is valid."""
    allowed = VALID_TRANSITIONS.get(current, set())
    return target in allowed


def can_advance_mode(
    target: PipelineStatus,
    mode: AutomationMode,
    auto_submit: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Evaluates whether the current automation mode allows advancing to target state:
    - DISCOVERY_ONLY: only up to NORMALIZED
    - MATCH_ONLY: only up to QUALIFIED
    - DOCUMENTS: only up to DOCUMENTS_READY
    - PREPARE_APPLICATION: only up to READY_TO_APPLY (default)
    - FULL_AUTO: up to SUBMITTED if auto_submit is enabled
    """
    if mode == AutomationMode.DISCOVERY_ONLY:
        if target in {
            PipelineStatus.MATCHED,
            PipelineStatus.QUALIFIED,
            PipelineStatus.DOC_REVIEW_REQUIRED,
            PipelineStatus.DOCUMENTS_READY,
            PipelineStatus.FORM_ANALYZED,
            PipelineStatus.READY_TO_APPLY,
            PipelineStatus.FILLING,
            PipelineStatus.SUBMITTING,
            PipelineStatus.SUBMITTED,
        }:
            return False, f"Mode {mode.value} halts before matching and application"

    elif mode == AutomationMode.MATCH_ONLY:
        if target in {
            PipelineStatus.DOC_REVIEW_REQUIRED,
            PipelineStatus.DOCUMENTS_READY,
            PipelineStatus.FORM_ANALYZED,
            PipelineStatus.READY_TO_APPLY,
            PipelineStatus.FILLING,
            PipelineStatus.SUBMITTING,
            PipelineStatus.SUBMITTED,
        }:
            return False, f"Mode {mode.value} halts after match qualification"

    elif mode == AutomationMode.DOCUMENTS:
        if target in {
            PipelineStatus.FORM_ANALYZED,
            PipelineStatus.READY_TO_APPLY,
            PipelineStatus.FILLING,
            PipelineStatus.SUBMITTING,
            PipelineStatus.SUBMITTED,
        }:
            return False, f"Mode {mode.value} halts after document generation"

    elif mode == AutomationMode.PREPARE_APPLICATION:
        if target in {
            PipelineStatus.FILLING,
            PipelineStatus.SUBMITTING,
            PipelineStatus.SUBMITTED,
        }:
            return False, f"Mode {mode.value} halts at READY_TO_APPLY until manual approval"

    elif mode == AutomationMode.FULL_AUTO:
        if target in {PipelineStatus.SUBMITTING, PipelineStatus.SUBMITTED} and not auto_submit:
            return False, "FULL_AUTO requires explicit AUTO_SUBMIT=true for final submission"

    return True, None
