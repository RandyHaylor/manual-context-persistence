"""Tests that the Stop hook leaves a record of what it decided.

A live run captured nothing and there was no way to find out why: the hook
returned an empty response whether it had seen no package, an unusable one, or
nothing at all. Every path now leaves a readable outcome behind.
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


def build_project(tmp_path) -> str:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory, exist_ok=True)
    return project_directory


def write_transcript_with_agent_reply(tmp_path, reply_text: str) -> str:
    transcript_path = str(tmp_path / "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        transcript_file.write(
            json.dumps(
                {
                    "type": "assistant",
                    "isSidechain": False,
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": reply_text}],
                    },
                }
            )
            + "\n"
        )
    return transcript_path


def build_reply_containing_a_package(summary_text: str = "Did the thing.") -> str:
    package_json = json.dumps(
        {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "summary_of_work_completed_this_turn": summary_text,
            "context_to_carry_forward": [],
        }
    )
    return f"prose\n\n```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{package_json}\n```"


def run_stop_hook(project_directory: str, transcript_path: str) -> dict:
    return handle_stop_hook_payload(
        {
            "cwd": project_directory,
            "session_id": "branch-session",
            "transcript_path": transcript_path,
            "hook_event_name": "Stop",
        }
    )


def test_a_captured_handoff_is_recorded_as_captured(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    transcript_path = write_transcript_with_agent_reply(
        tmp_path, build_reply_containing_a_package()
    )

    run_stop_hook(project_directory, transcript_path)

    recorded = read_last_stop_hook_outcome(project_directory)
    assert recorded["outcome"] == CaptureOutcome.CAPTURED.value
    assert ContextToKeepFileStore(project_directory).has_pending_context_to_keep()


def test_an_ordinary_reply_is_recorded_as_having_no_package(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    transcript_path = write_transcript_with_agent_reply(tmp_path, "just prose")

    run_stop_hook(project_directory, transcript_path)

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NO_PACKAGE_IN_REPLY.value
    )


def test_an_unusable_package_is_recorded_distinctly(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    transcript_path = write_transcript_with_agent_reply(
        tmp_path, f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ bad \n```"
    )

    run_stop_hook(project_directory, transcript_path)

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.PACKAGE_PRESENT_BUT_UNUSABLE.value
    )


def test_a_missing_transcript_is_recorded_as_no_reply_found(tmp_path) -> None:
    project_directory = build_project(tmp_path)

    run_stop_hook(project_directory, str(tmp_path / "absent.jsonl"))

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NO_AGENT_REPLY_FOUND.value
    )


def test_a_pending_handoff_is_recorded_as_blocking(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    ContextToKeepFileStore(project_directory).write_pending_context_to_keep_package(
        ContextToKeepPackage("an earlier turn", [])
    )
    transcript_path = write_transcript_with_agent_reply(
        tmp_path, build_reply_containing_a_package("a later turn")
    )

    run_stop_hook(project_directory, transcript_path)

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.EARLIER_HANDOFF_STILL_PENDING.value
    )
    still_pending = ContextToKeepFileStore(
        project_directory
    ).read_pending_context_to_keep_package()
    assert still_pending.summary_of_work_completed_this_turn == "an earlier turn"


def test_the_record_names_the_session_and_transcript(tmp_path) -> None:
    """Which session and which file — the two things needed to reproduce."""
    project_directory = build_project(tmp_path)
    transcript_path = write_transcript_with_agent_reply(tmp_path, "just prose")

    run_stop_hook(project_directory, transcript_path)

    recorded = read_last_stop_hook_outcome(project_directory)
    assert recorded["session_identifier"] == "branch-session"
    assert recorded["transcript_path"] == transcript_path


def test_the_record_carries_a_human_readable_reason(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    transcript_path = write_transcript_with_agent_reply(tmp_path, "just prose")

    run_stop_hook(project_directory, transcript_path)

    assert "no_package_in_reply" in read_last_stop_hook_outcome(project_directory)["reason_text"]


def test_reading_before_any_hook_has_run_gives_nothing(tmp_path) -> None:
    assert read_last_stop_hook_outcome(build_project(tmp_path)) == {}


def test_each_run_replaces_the_previous_record(tmp_path) -> None:
    """The question is always "why did the LAST turn not capture"."""
    project_directory = build_project(tmp_path)
    run_stop_hook(project_directory, write_transcript_with_agent_reply(tmp_path, "prose"))
    run_stop_hook(project_directory, str(tmp_path / "absent.jsonl"))

    assert (
        read_last_stop_hook_outcome(project_directory)["outcome"]
        == CaptureOutcome.NO_AGENT_REPLY_FOUND.value
    )


def test_a_payload_without_a_project_directory_still_returns_cleanly(tmp_path) -> None:
    """Nowhere to record; the hook must still never disturb the session."""
    assert handle_stop_hook_payload({"session_id": "s"}) == {}


def test_the_hook_still_returns_an_empty_response_on_every_path(tmp_path) -> None:
    project_directory = build_project(tmp_path)
    for transcript_path in (
        write_transcript_with_agent_reply(tmp_path, build_reply_containing_a_package()),
        str(tmp_path / "absent.jsonl"),
    ):
        assert run_stop_hook(project_directory, transcript_path) == {}
