"""PostToolUse hook: put the handoff requirement back in front of the agent.

The contract arrives once, in the text a session is opened with. A session that
then works for forty tool calls has that instruction far behind it, and the
observed result was a session that worked continuously and never returned — not
one that finished and forgot the block, but one that never reached a stopping
point at all.

So the requirement is repeated. The tool that fired is irrelevant; this hook only
uses the firing as an occasion to speak, and what it says goes back to the agent
through ``hookSpecificOutput.additionalContext``.

The wording anchors on the commit point on purpose. "Work worth saving" is a
judgement with nothing to measure it against, while "the point where you would
commit" names a boundary an agent already recognises — and it holds whether or not
the project uses git, because it describes when to stop rather than what to run.

Gated to sessions the user works in, like the other hooks. The session that
accumulates history and the orchestrator's own non-interactive calls have no
handoff to make, and reminding them would be noise in a place nobody reads.
"""
from __future__ import annotations

from typing import Any

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)

EMPTY_HOOK_RESPONSE: dict[str, Any] = {}

POST_TOOL_USE_HOOK_EVENT_NAME = "PostToolUse"

HANDOFF_REMINDER_TEXT = (
    "Required, not optional: the moment you reach a point where you would make a "
    "git commit — one coherent piece of work finished — stop there and end that "
    f"response with the `{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}` block. Do not carry "
    "on into the next piece of work first. Returning early with a small result is "
    "correct; continuing until everything is done is not."
)


def build_additional_context_response(additional_context_text: str) -> dict[str, Any]:
    """The shape that puts text back in front of the agent after a tool call."""
    return {
        "hookSpecificOutput": {
            "hookEventName": POST_TOOL_USE_HOOK_EVENT_NAME,
            "additionalContext": additional_context_text,
        }
    }


def handle_post_tool_use_payload(hook_payload: dict[str, Any]) -> dict[str, Any]:
    """Return the reminder for a session the user works in, or nothing."""
    try:
        project_directory = hook_payload.get("cwd")
        session_identifier = hook_payload.get("session_id")
        if not project_directory or not session_identifier:
            return EMPTY_HOOK_RESPONSE
        if not UserFacingSessionRegistry(project_directory).is_user_facing_session(
            session_identifier
        ):
            return EMPTY_HOOK_RESPONSE
        return build_additional_context_response(HANDOFF_REMINDER_TEXT)
    except Exception:
        # No hook may be the reason a session breaks, and this one only speaks.
        return EMPTY_HOOK_RESPONSE
