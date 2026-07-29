"""Tests for the two hook entry points, exercised through their real contract.

A hook is a process: JSON on stdin, JSON on stdout, exit code 0. These tests
call the same handler the scripts call, with the payload shapes Claude Code
actually sends, and hold both hooks to one rule — a hook must never be the
reason a session breaks, so every failure path still exits cleanly.
"""
from __future__ import annotations

import json
import os

from context_handoff.hooks.context_to_keep_stop_hook_handler import (
    handle_stop_hook_payload,
)
from context_handoff.hooks.user_prompt_submit_hook_handler import (
    handle_user_prompt_submit_payload,
)
from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore


def write_transcript(tmp_path, records: list[dict]) -> str:
    transcript_path = str(tmp_path / "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        for record in records:
            transcript_file.write(json.dumps(record) + "\n")
    return transcript_path


def assistant_text_record(text: str) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def user_prompt_record(prompt_text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": prompt_text},
    }


def build_agent_reply_containing_a_package(summary_text: str) -> str:
    package_json = json.dumps(
        {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "summary_of_work_completed_this_turn": summary_text,
            "context_to_carry_forward": ["a fact worth keeping"],
        }
    )
    return (
        "Here is what I did.\n\n"
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{package_json}\n```\n"
    )


# --- Stop hook -------------------------------------------------------------


def test_stop_hook_writes_the_package_the_agent_emitted(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    transcript_path = write_transcript(
        tmp_path, [assistant_text_record(build_agent_reply_containing_a_package("Did it."))]
    )

    hook_response = handle_stop_hook_payload(
        {
            "cwd": project_directory,
            "session_id": "branch-session",
            "transcript_path": transcript_path,
            "hook_event_name": "Stop",
        }
    )

    stored_package = ContextToKeepFileStore(
        project_directory
    ).read_pending_context_to_keep_package()
    assert stored_package is not None
    assert stored_package.summary_of_work_completed_this_turn == "Did it."
    assert hook_response == {}


def test_stop_hook_writes_nothing_when_the_reply_has_no_package(tmp_path) -> None:
    """Most turns end without a handoff; that is normal, not a failure."""
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    transcript_path = write_transcript(
        tmp_path, [assistant_text_record("Just an ordinary reply.")]
    )

    hook_response = handle_stop_hook_payload(
        {"cwd": project_directory, "session_id": "s", "transcript_path": transcript_path}
    )

    assert (
        ContextToKeepFileStore(project_directory).read_pending_context_to_keep_package()
        is None
    )
    assert hook_response == {}


def test_stop_hook_survives_a_missing_transcript(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    assert (
        handle_stop_hook_payload(
            {
                "cwd": project_directory,
                "session_id": "s",
                "transcript_path": str(tmp_path / "absent.jsonl"),
            }
        )
        == {}
    )


def test_stop_hook_survives_a_payload_with_nothing_in_it() -> None:
    assert handle_stop_hook_payload({}) == {}


def test_stop_hook_does_not_overwrite_an_unconsumed_package(tmp_path) -> None:
    """A pending handoff belongs to a turn the loop has not processed yet."""
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    first_transcript = write_transcript(
        tmp_path,
        [assistant_text_record(build_agent_reply_containing_a_package("first turn"))],
    )
    handle_stop_hook_payload(
        {"cwd": project_directory, "session_id": "s", "transcript_path": first_transcript}
    )

    second_transcript = str(tmp_path / "second.jsonl")
    with open(second_transcript, "w", encoding="utf-8") as transcript_file:
        transcript_file.write(
            json.dumps(
                assistant_text_record(
                    build_agent_reply_containing_a_package("second turn")
                )
            )
            + "\n"
        )
    handle_stop_hook_payload(
        {"cwd": project_directory, "session_id": "s", "transcript_path": second_transcript}
    )

    stored_package = ContextToKeepFileStore(
        project_directory
    ).read_pending_context_to_keep_package()
    assert stored_package.summary_of_work_completed_this_turn == "first turn"


# --- UserPromptSubmit hook -------------------------------------------------


def test_prompt_hook_logs_the_prompt_verbatim(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    awkward_prompt_text = "  keep  my   spacing\tand “quotes”  "

    hook_response = handle_user_prompt_submit_payload(
        {
            "cwd": project_directory,
            "session_id": "branch-session",
            "prompt": awkward_prompt_text,
            "transcript_path": str(tmp_path / "absent.jsonl"),
        }
    )

    logged_entries = UserPromptLogStore(project_directory).read_entries_for_session(
        "branch-session"
    )
    assert [entry.user_prompt_text for entry in logged_entries] == [awkward_prompt_text]
    assert hook_response == {}


def test_prompt_hook_captures_the_agent_output_that_preceded_the_prompt(
    tmp_path,
) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    transcript_path = write_transcript(
        tmp_path,
        [
            user_prompt_record("an older question"),
            assistant_text_record("Shall I use adapter boundaries?"),
        ],
    )

    handle_user_prompt_submit_payload(
        {
            "cwd": project_directory,
            "session_id": "branch-session",
            "prompt": "yes",
            "transcript_path": transcript_path,
        }
    )

    logged_entry = UserPromptLogStore(project_directory).read_entries_for_session(
        "branch-session"
    )[0]
    assert "Shall I use adapter boundaries?" in logged_entry.pre_submission_content


def test_prompt_hook_ignores_an_empty_prompt(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)

    handle_user_prompt_submit_payload(
        {"cwd": project_directory, "session_id": "s", "prompt": "   "}
    )

    assert UserPromptLogStore(project_directory).read_entries_for_session("s") == []


def test_prompt_hook_survives_a_payload_with_nothing_in_it() -> None:
    assert handle_user_prompt_submit_payload({}) == {}


def test_prompt_hook_logs_each_prompt_separately(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    for prompt_text in ("first", "second", "third"):
        handle_user_prompt_submit_payload(
            {"cwd": project_directory, "session_id": "s", "prompt": prompt_text}
        )
    assert [
        entry.user_prompt_text
        for entry in UserPromptLogStore(project_directory).read_entries_for_session("s")
    ] == ["first", "second", "third"]
