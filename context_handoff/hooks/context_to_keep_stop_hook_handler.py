"""Stop hook: capture the handoff package the agent emitted this turn.

Runs when the agent finishes a turn. It gathers two facts — the agent's last
reply, and whether an earlier handoff is still waiting — hands them to a pure
decision, and carries that decision out.

Every run leaves its outcome behind. A live run once captured nothing and there
was no way to tell whether the agent had emitted no package, emitted a broken
one, or whether the hook had run at all: all three returned the same empty
response. The record is what makes those different answers.

The hook still never raises. That rule now applies to a much smaller shell,
because the branching it used to hide lives in the decision instead.
"""
from __future__ import annotations

from typing import Any

from context_handoff.adapters.claude_cli.claude_cli_transcript_reader import (
    read_last_assistant_text_message,
)
from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.project_state.project_state_directory import ProjectStateDirectory

from .stop_hook_capture_decision import CaptureOutcome, decide_whether_to_capture_handoff

EMPTY_HOOK_RESPONSE: dict[str, Any] = {}
LAST_STOP_HOOK_OUTCOME_FILE_NAME = "context-handoff-last-stop-hook-outcome.json"


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
    session_identifier: str,
    transcript_path: str,
) -> None:
    ProjectStateDirectory(project_directory).json_document(
        LAST_STOP_HOOK_OUTCOME_FILE_NAME
    ).write_dictionary(
        {
            "outcome": outcome.value,
            "reason_text": reason_text,
            "session_identifier": session_identifier,
            "transcript_path": transcript_path,
        }
    )


def handle_stop_hook_payload(hook_payload: dict[str, Any]) -> dict[str, Any]:
    """Capture any handoff in the agent's last reply, and record the outcome."""
    project_directory = hook_payload.get("cwd")
    if not project_directory:
        # Nowhere to write anything, including a record of why.
        return EMPTY_HOOK_RESPONSE

    transcript_path = hook_payload.get("transcript_path") or ""
    session_identifier = hook_payload.get("session_id") or ""

    try:
        context_to_keep_store = ContextToKeepFileStore(project_directory)
        decision = decide_whether_to_capture_handoff(
            last_agent_reply_text=(
                read_last_assistant_text_message(transcript_path)
                if transcript_path
                else None
            ),
            a_handoff_is_already_pending=(
                context_to_keep_store.has_pending_context_to_keep()
            ),
        )
        if decision.package is not None:
            context_to_keep_store.write_pending_context_to_keep_package(decision.package)
        _record_outcome(
            project_directory,
            decision.outcome,
            decision.reason_text,
            session_identifier,
            transcript_path,
        )
    except Exception:
        # Deliberately broad: no failure in this hook may wedge a session.
        return EMPTY_HOOK_RESPONSE
    return EMPTY_HOOK_RESPONSE
