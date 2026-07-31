"""Stop hook: capture the handoff package the agent emitted this turn.

The agent's final text comes from the payload. The platform supplies it as
``last_assistant_message``, which was confirmed against a real session before
this was written. Taking it from there removes the questions an earlier version
had to answer badly: which message in the transcript was the right one, and
whether the transcript had been written yet when the hook ran.

Every path leaves a record, including an unexpected failure. The earlier
version returned silently when it raised, so the one case most in need of a
trace was the only case that left none — and that is exactly the case that
happened.
"""
from __future__ import annotations

from typing import Any, Optional

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.project_state.project_state_directory import ProjectStateDirectory

from .stop_hook_capture_decision import CaptureOutcome, decide_whether_to_capture_handoff

EMPTY_HOOK_RESPONSE: dict[str, Any] = {}
LAST_STOP_HOOK_OUTCOME_FILE_NAME = "context-handoff-last-stop-hook-outcome.json"

# Enough to show whether the handoff block was present, without copying
# transcript-sized content into a second file.
RECORDED_REPLY_TAIL_CHARACTERS = 400


def read_last_stop_hook_outcome(project_directory: str) -> dict[str, Any]:
    """Return what the Stop hook decided last time, or {} if it never ran."""
    return (
        ProjectStateDirectory(project_directory)
        .json_document(LAST_STOP_HOOK_OUTCOME_FILE_NAME)
        .read_dictionary_or_default({})
    )


def _record_outcome(
    project_directory: str,
    outcome: CaptureOutcome,
    reason_text: str,
    hook_payload: dict[str, Any],
    agent_reply_text: Optional[str],
) -> None:
    reply_text = agent_reply_text if isinstance(agent_reply_text, str) else ""
    ProjectStateDirectory(project_directory).json_document(
        LAST_STOP_HOOK_OUTCOME_FILE_NAME
    ).write_dictionary(
        {
            "outcome": outcome.value,
            "reason_text": reason_text,
            "session_identifier": hook_payload.get("session_id") or "",
            "transcript_path": hook_payload.get("transcript_path") or "",
            "agent_reply_character_count": len(reply_text),
            "agent_reply_tail": reply_text[-RECORDED_REPLY_TAIL_CHARACTERS:],
        }
    )


def handle_stop_hook_payload(hook_payload: dict[str, Any]) -> dict[str, Any]:
    """Capture any handoff in the agent's final message, and record the outcome."""
    project_directory = hook_payload.get("cwd")
    if not project_directory:
        # Nowhere to write anything, including a record of why.
        return EMPTY_HOOK_RESPONSE

    agent_reply_text = hook_payload.get("last_assistant_message")

    try:
        context_to_keep_store = ContextToKeepFileStore(project_directory)
        decision = decide_whether_to_capture_handoff(
            last_agent_reply_text=agent_reply_text,
            a_handoff_is_already_pending=(
                context_to_keep_store.has_pending_context_to_keep()
            ),
        )
        if decision.package is not None:
            context_to_keep_store.write_pending_context_to_keep_package(decision.package)
        outcome, reason_text = decision.outcome, decision.reason_text
    except Exception as unexpected_error:
        outcome = CaptureOutcome.UNEXPECTED_FAILURE
        reason_text = f"unexpected_failure: {unexpected_error!r}"

    try:
        _record_outcome(
            project_directory, outcome, reason_text, hook_payload, agent_reply_text
        )
    except Exception:
        # Recording is best effort. A hook must never wedge a session, and
        # there is nowhere left to report a failure to report.
        pass
    return EMPTY_HOOK_RESPONSE
