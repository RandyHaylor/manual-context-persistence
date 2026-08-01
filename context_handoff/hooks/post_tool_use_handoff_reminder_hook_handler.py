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

Unlike the other two hooks, this one has no session gate, and needs none. Those
gate because they *write*: a prompt logged from the wrong session corrupts the
record of what the user said, and a handoff captured from the wrong session
rotates a turn that was never the user's. This hook only speaks, and the sessions
that reach it are the ones worth speaking to — the base session and the
orchestrator's own non-interactive calls do not call tools, so this never fires
for them. A gate here would add a way to go wrong (an unreadable registry denies
by default) in exchange for suppressing an event that does not occur.
"""
from __future__ import annotations

from typing import Any

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
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
    """Return the reminder. The payload is not consulted; the firing is the signal."""
    try:
        return build_additional_context_response(HANDOFF_REMINDER_TEXT)
    except Exception:
        # No hook may be the reason a session breaks, and this one only speaks.
        return EMPTY_HOOK_RESPONSE
