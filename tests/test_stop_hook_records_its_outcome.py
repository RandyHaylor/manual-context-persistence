"""Tests that the Stop hook acts on its payload and records what it decided.

The hook reads the agent's final text straight from the payload field the
platform provides. Verified against a real session: a Stop payload carries
``last_assistant_message`` holding the final assistant text of the turn. That
removes any question of which message was read, or whether a transcript had
been written yet.

Every path leaves a record, including an unexpected failure. An earlier version
returned silently on exception, which meant the one case most in need of a
trace was the only case that left none.
"""
from __future__ import annotations

import json
import os

from context_handoff.hooks.context_to_keep_stop_hook_handler import (
    handle_stop_hook_payload,
    read_last_stop_hook_outcome,
)
from context_handoff.hooks.stop_hook_capture_decision import CaptureOutcome
from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    ContextToKeepPackage,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)


def build_project(tmp_path) -> str:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory, exist_ok=True)
    return project_directory


def build_reply_containing_a_package(summary_text: str = "Did the thing.") -> str:
    package_json = json.dumps(
        {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "context_to_keep": [summary_text],
        }
    )
    return f"prose\n\n```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{package_json}\n```"


def run_stop_hook(
    project_directory: str, last_assistant_message, session_identifier: str = "branch-session"
) -> dict:
    # The hook only captures from sessions the user works in, so a branch has
    # to be registered exactly as the orchestrator registers it.
    if session_identifier == "branch-session":
        UserFacingSessionRegistry(project_directory).register_user_facing_session(
            session_identifier
        )
    return handle_stop_hook_payload(
        {
            "cwd": project_directory,
            "session_id": session_identifier,
            "transcript_path": f"/transcripts/{session_identifier}.jsonl",
            "hook_event_name": "Stop",
            "last_assistant_message": last_assistant_message,
        }
    )


def test_a_reply_from_the_base_session_is_never_captured(tmp_path) -> None:
    """Delivering a handoff ends a turn in the base session and fires this hook.

    Its acknowledgement quotes the user's words back, so it can plausibly
    contain a fenced block. Capturing that would rotate the base's own reply as
    though it were a branch's work.
    """
    project_directory = build_project(tmp_path)

    run_stop_hook(
        project_directory,
        build_reply_containing_a_package("the base session's own reply"),
        session_identifier="the-base-session",
    )

    assert not ContextToKeepFileStore(project_directory).has_pending_context_to_keep()
    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NOT_A_USER_FACING_SESSION.value
    )


def test_a_reply_carrying_a_package_is_captured(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, build_reply_containing_a_package())

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.CAPTURED.value
    )
    assert ContextToKeepFileStore(project_directory).has_pending_context_to_keep()


def test_an_ordinary_reply_is_recorded_as_having_no_package(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, "just prose")

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NO_PACKAGE_IN_REPLY.value
    )


def test_an_unusable_package_is_recorded_distinctly(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(
        project_directory, f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ bad \n```"
    )

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.PACKAGE_PRESENT_BUT_UNUSABLE.value
    )


def test_a_payload_with_no_reply_is_recorded_as_no_reply_found(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, None)

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NO_AGENT_REPLY_FOUND.value
    )


def test_a_pending_handoff_is_recorded_as_blocking(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    ContextToKeepFileStore(project_directory).write_pending_context_to_keep_package(
        ContextToKeepPackage(context_to_keep=["an earlier turn"])
    )

    run_stop_hook(project_directory, build_reply_containing_a_package("a later turn"))

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.EARLIER_HANDOFF_STILL_PENDING.value
    )
    still_pending = ContextToKeepFileStore(
        project_directory
    ).read_pending_context_to_keep_package()
    assert still_pending.context_to_keep == ["an earlier turn"]


def test_an_unexpected_failure_is_recorded_rather_than_swallowed(tmp_path) -> None:
    """The case most in need of a trace previously left none.

    A payload whose reply field is not text is the realistic way this happens:
    the hook is handed something it cannot process, and returning quietly makes
    that indistinguishable from a turn with nothing to hand off.
    """
    project_directory = build_project(tmp_path)

    hook_response = run_stop_hook(project_directory, {"unexpected": "shape"})

    assert hook_response == {}
    recorded = read_last_stop_hook_outcome(project_directory)
    assert recorded["outcome"] == CaptureOutcome.UNEXPECTED_FAILURE.value
    assert recorded["reason_text"]


def test_the_record_names_the_session_and_transcript(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, "just prose")

    recorded = read_last_stop_hook_outcome(project_directory)
    assert recorded["session_identifier"] == "branch-session"
    assert recorded["transcript_path"] == "/transcripts/branch-session.jsonl"


def test_the_record_says_how_much_reply_the_hook_was_given(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    reply_text = build_reply_containing_a_package()

    run_stop_hook(project_directory, reply_text)

    assert read_last_stop_hook_outcome(project_directory)[
        "agent_reply_character_count"
    ] == len(reply_text)


def test_the_record_carries_the_end_of_the_reply(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, "prose then THE VERY END")

    assert read_last_stop_hook_outcome(project_directory)[
        "agent_reply_tail"
    ].endswith("THE VERY END")


def test_the_recorded_tail_is_bounded(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, "x" * 10000)

    recorded = read_last_stop_hook_outcome(project_directory)
    assert recorded["agent_reply_character_count"] == 10000
    assert len(recorded["agent_reply_tail"]) < 1000


def test_reading_before_any_hook_has_run_gives_nothing(tmp_path) -> None:
    assert read_last_stop_hook_outcome(build_project(tmp_path)) == {}


def test_each_run_replaces_the_previous_record(tmp_path) -> None:
    """The question is always "why did the LAST turn not capture"."""
    project_directory = build_project(tmp_path)
    run_stop_hook(project_directory, "prose")
    run_stop_hook(project_directory, None)

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NO_AGENT_REPLY_FOUND.value
    )


def test_a_payload_without_a_project_directory_still_returns_cleanly() -> None:
    """Nowhere to record, including a record of why."""
    assert handle_stop_hook_payload({"session_id": "s"}) == {}


def test_the_hook_returns_an_empty_response_on_every_path(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    for reply in (build_reply_containing_a_package(), None, {"bad": "shape"}):
        assert run_stop_hook(project_directory, reply) == {}
