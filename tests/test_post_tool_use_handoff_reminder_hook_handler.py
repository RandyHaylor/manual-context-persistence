"""Tests for the reminder that puts the handoff requirement back in front.

The contract arrives once, when a session is opened. A session that then works
for dozens of tool calls has it far behind — and the run that prompted this hook
worked continuously and never returned, not because it finished and forgot, but
because it never reached a stopping point at all.

There is deliberately no session gate. The other two hooks gate because they
write; this one only speaks, and the sessions that reach it are the ones worth
speaking to. It was gated once, which contradicted a decision already taken and
suppressed nothing that happens: verified in a live run that the base session
produced only text turns and no PostToolUse event at all.
"""
from __future__ import annotations

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
)
from context_handoff.hooks.post_tool_use_handoff_reminder_hook_handler import (
    HANDOFF_REMINDER_TEXT,
    handle_post_tool_use_payload,
)


def build_payload(**overrides) -> dict:
    payload = {
        "cwd": "/some/project",
        "session_id": "any-session",
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/somewhere/index.html"},
        "tool_response": {"ok": True},
    }
    payload.update(overrides)
    return payload


def read_additional_context(response: dict) -> str:
    return response["hookSpecificOutput"]["additionalContext"]


def test_the_reminder_reaches_the_agent_through_additional_context() -> None:
    """The documented channel for a PostToolUse hook to speak to the agent.

    Confirmed live: the platform echoed this back as a hook_additional_context
    attachment alongside two of the operator's own PostToolUse hooks.
    """
    response = handle_post_tool_use_payload(build_payload())

    assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert read_additional_context(response) == HANDOFF_REMINDER_TEXT


def test_it_speaks_for_any_session_without_consulting_a_registry() -> None:
    """No gate. Only sessions that call tools reach this, and those want it.

    A gate would add a way to go wrong — an unreadable registry denies by
    default — in exchange for suppressing an event that does not occur.
    """
    for session_identifier in ("a-branch", "the-base-session", "", "unknown"):
        response = handle_post_tool_use_payload(
            build_payload(session_id=session_identifier)
        )
        assert read_additional_context(response) == HANDOFF_REMINDER_TEXT


def test_it_needs_nothing_from_the_payload() -> None:
    """The firing is the signal; the payload is not consulted."""
    assert read_additional_context(handle_post_tool_use_payload({})) == (
        HANDOFF_REMINDER_TEXT
    )


def test_the_tool_that_fired_does_not_change_the_answer() -> None:
    for tool_name in ("Bash", "Read", "Write", "Edit", "WebSearch"):
        response = handle_post_tool_use_payload(build_payload(tool_name=tool_name))
        assert read_additional_context(response) == HANDOFF_REMINDER_TEXT


def test_the_reminder_states_the_requirement_is_not_optional() -> None:
    """Wording is the whole mechanism here, so it is pinned rather than assumed."""
    lowercased = HANDOFF_REMINDER_TEXT.lower()
    assert "not optional" in lowercased
    assert "stop there" in lowercased


def test_the_reminder_anchors_on_the_commit_point() -> None:
    """"Work worth saving" is a judgement; the commit point is a boundary.

    It holds whether or not the project uses git, because it names when to stop
    rather than a command to run.
    """
    lowercased = HANDOFF_REMINDER_TEXT.lower()
    assert "git commit" in lowercased
    assert "coherent piece of work" in lowercased


def test_the_reminder_says_not_to_continue_into_more_work() -> None:
    """The observed failure: it kept going instead of handing off."""
    lowercased = HANDOFF_REMINDER_TEXT.lower()
    assert "do not carry on" in lowercased
    assert "returning early" in lowercased


def test_the_reminder_names_the_block_it_is_asking_for() -> None:
    assert CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG in HANDOFF_REMINDER_TEXT
