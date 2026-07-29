"""Stop hook: capture the handoff package the agent emitted this turn.

Runs when the agent finishes a turn. It reads the agent's last reply out of the
transcript, looks for a context-to-keep package inside it, and writes the
package where the turn loop will find it.

Two rules govern everything here. A hook must never break a session, so every
failure path returns an empty response instead of raising. And a pending
package is never overwritten: it belongs to a turn the loop has not consumed
yet, and clobbering it would silently drop a handoff.
"""
from __future__ import annotations

from typing import Any

from context_handoff.adapters.claude_cli.claude_cli_transcript_reader import (
    read_last_assistant_text_message,
)
from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import (
    extract_context_to_keep_package_from_agent_response,
)

EMPTY_HOOK_RESPONSE: dict[str, Any] = {}


def handle_stop_hook_payload(hook_payload: dict[str, Any]) -> dict[str, Any]:
    """Write any handoff package found in the agent's last reply."""
    try:
        project_directory = hook_payload.get("cwd")
        transcript_path = hook_payload.get("transcript_path")
        if not project_directory or not transcript_path:
            return EMPTY_HOOK_RESPONSE

        last_agent_reply_text = read_last_assistant_text_message(transcript_path)
        if not last_agent_reply_text:
            return EMPTY_HOOK_RESPONSE

        extracted_package = extract_context_to_keep_package_from_agent_response(
            last_agent_reply_text
        )
        if extracted_package is None:
            return EMPTY_HOOK_RESPONSE

        context_to_keep_store = ContextToKeepFileStore(project_directory)
        if context_to_keep_store.has_pending_context_to_keep():
            return EMPTY_HOOK_RESPONSE

        context_to_keep_store.write_pending_context_to_keep_package(extracted_package)
        return EMPTY_HOOK_RESPONSE
    except Exception:
        # Deliberately broad: no failure in this hook may wedge a session.
        return EMPTY_HOOK_RESPONSE
