"""Tests for the reminder that puts the handoff requirement back in front.

The contract arrives once, when a session is opened. A session that then works
for dozens of tool calls has it far behind — and the run that prompted this hook
worked continuously and never returned, not because it finished and forgot, but
because it never reached a stopping point at all.

What the tool was is irrelevant here: the firing is only an occasion to speak.
"""
from __future__ import annotations

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
)
from context_handoff.hooks.post_tool_use_handoff_reminder_hook_handler import (
    HANDOFF_REMINDER_TEXT,
    handle_post_tool_use_payload,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)

USER_FACING_SESSION_IDENTIFIER = "a-session-the-user-works-in"


def build_payload(project_directory: str, session_identifier: str, **overrides) -> dict:
    payload = {
        "cwd": project_directory,
        "session_id": session_identifier,
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/somewhere/index.html"},
        "tool_response": {"ok": True},
    }
    payload.update(overrides)
    return payload


def register_user_facing_session(project_directory: str) -> None:
    UserFacingSessionRegistry(project_directory).register_user_facing_session(
        USER_FACING_SESSION_IDENTIFIER
    )


def read_additional_context(response: dict) -> str:
    return response["hookSpecificOutput"]["additionalContext"]


def test_the_reminder_reaches_the_agent_through_additional_context(tmp_path) -> None:
    """The documented channel for a PostToolUse hook to speak to the agent."""
    register_user_facing_session(str(tmp_path))

    response = handle_post_tool_use_payload(
        build_payload(str(tmp_path), USER_FACING_SESSION_IDENTIFIER)
    )

    assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert read_additional_context(response) == HANDOFF_REMINDER_TEXT


def test_the_reminder_states_the_requirement_is_not_optional(tmp_path) -> None:
    """Wording is the whole mechanism here, so it is pinned rather than assumed."""
    lowercased = HANDOFF_REMINDER_TEXT.lower()
    assert "not optional" in lowercased
    assert "stop there" in lowercased


def test_the_reminder_anchors_on_the_commit_point(tmp_path) -> None:
    """"Work worth saving" is a judgement; the commit point is a boundary.

    It holds whether or not the project uses git, because it names when to stop
    rather than a command to run.
    """
    lowercased = HANDOFF_REMINDER_TEXT.lower()
    assert "git commit" in lowercased
    assert "coherent piece of work" in lowercased


def test_the_reminder_says_not_to_continue_into_more_work(tmp_path) -> None:
    """The observed failure: it kept going instead of handing off."""
    lowercased = HANDOFF_REMINDER_TEXT.lower()
    assert "do not carry on" in lowercased
    assert "returning early" in lowercased


def test_the_reminder_names_the_block_it_is_asking_for() -> None:
    assert CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG in HANDOFF_REMINDER_TEXT


def test_a_session_the_user_does_not_work_in_is_left_alone(tmp_path) -> None:
    """The accumulating session and the orchestrator's own calls have no handoff.

    Reminding them would be noise written into a place nobody reads.
    """
    register_user_facing_session(str(tmp_path))

    response = handle_post_tool_use_payload(
        build_payload(str(tmp_path), "some-other-session")
    )

    assert response == {}


def test_a_project_with_no_registry_yet_is_left_alone(tmp_path) -> None:
    response = handle_post_tool_use_payload(
        build_payload(str(tmp_path), USER_FACING_SESSION_IDENTIFIER)
    )
    assert response == {}


def test_a_payload_missing_its_fields_is_survived(tmp_path) -> None:
    """No hook may be the reason a session breaks."""
    assert handle_post_tool_use_payload({}) == {}
    assert handle_post_tool_use_payload({"cwd": str(tmp_path)}) == {}
    assert handle_post_tool_use_payload({"session_id": "x"}) == {}


def test_the_tool_that_fired_does_not_change_the_answer(tmp_path) -> None:
    """The firing is an occasion to speak; the tool itself is irrelevant."""
    register_user_facing_session(str(tmp_path))

    responses = [
        handle_post_tool_use_payload(
            build_payload(
                str(tmp_path), USER_FACING_SESSION_IDENTIFIER, tool_name=tool_name
            )
        )
        for tool_name in ("Bash", "Read", "Write", "Edit", "WebSearch")
    ]

    assert all(read_additional_context(response) == HANDOFF_REMINDER_TEXT for response in responses)
