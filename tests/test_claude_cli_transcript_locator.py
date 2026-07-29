"""Tests for locating Claude CLI session transcripts on disk.

The projects root is an injected parameter rather than a hard-coded home
directory, so these tests run entirely inside tmp_path with no environment
patching and no risk of reading the developer's real sessions.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from context_handoff.adapters.claude_cli.claude_cli_transcript_locator import (
    build_transcript_directory_path,
    build_transcript_file_path,
    encode_working_directory_for_transcript_directory_name,
    find_active_session_identifier_for_working_directory,
    read_session_display_name_from_transcript,
)


def write_transcript_file(
    projects_root_directory: str,
    working_directory: str,
    session_identifier: str,
    transcript_lines: list[str],
    modification_time_epoch_seconds: float | None = None,
) -> str:
    transcript_directory = build_transcript_directory_path(
        working_directory, projects_root_directory
    )
    os.makedirs(transcript_directory, exist_ok=True)
    transcript_path = os.path.join(transcript_directory, f"{session_identifier}.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        for line in transcript_lines:
            transcript_file.write(line + "\n")
    if modification_time_epoch_seconds is not None:
        os.utime(
            transcript_path,
            (modification_time_epoch_seconds, modification_time_epoch_seconds),
        )
    return transcript_path


def test_encoding_replaces_every_non_alphanumeric_character() -> None:
    assert (
        encode_working_directory_for_transcript_directory_name("/home/user/my_project.v2")
        == "-home-user-my-project-v2"
    )


def test_transcript_file_path_is_the_session_identifier_inside_the_encoded_directory(
    tmp_path,
) -> None:
    transcript_path = build_transcript_file_path(
        session_identifier="abc-123",
        working_directory="/home/user/project",
        claude_projects_root_directory=str(tmp_path),
    )
    assert transcript_path.endswith(os.path.join("-home-user-project", "abc-123.jsonl"))


def test_no_transcript_anywhere_raises_lookup_error(tmp_path) -> None:
    with pytest.raises(LookupError):
        find_active_session_identifier_for_working_directory(
            working_directory="/home/user/project",
            claude_projects_root_directory=str(tmp_path),
        )


def test_the_newest_transcript_is_the_active_session(tmp_path) -> None:
    working_directory = "/home/user/project"
    now_epoch_seconds = time.time()
    write_transcript_file(
        str(tmp_path), working_directory, "older-session", ["{}"],
        modification_time_epoch_seconds=now_epoch_seconds - 500,
    )
    write_transcript_file(
        str(tmp_path), working_directory, "newer-session", ["{}"],
        modification_time_epoch_seconds=now_epoch_seconds,
    )
    assert (
        find_active_session_identifier_for_working_directory(
            working_directory, str(tmp_path)
        )
        == "newer-session"
    )


def test_a_transcript_registered_against_an_ancestor_directory_is_found(tmp_path) -> None:
    """The CLI keys transcripts to where it was launched, not to a subdirectory."""
    write_transcript_file(str(tmp_path), "/home/user/project", "root-session", ["{}"])
    assert (
        find_active_session_identifier_for_working_directory(
            "/home/user/project/nested/deeper", str(tmp_path)
        )
        == "root-session"
    )


def test_the_nearest_newest_transcript_wins_across_ancestor_directories(tmp_path) -> None:
    now_epoch_seconds = time.time()
    write_transcript_file(
        str(tmp_path), "/home/user/project", "ancestor-session", ["{}"],
        modification_time_epoch_seconds=now_epoch_seconds - 500,
    )
    write_transcript_file(
        str(tmp_path), "/home/user/project/nested", "nested-session", ["{}"],
        modification_time_epoch_seconds=now_epoch_seconds,
    )
    assert (
        find_active_session_identifier_for_working_directory(
            "/home/user/project/nested", str(tmp_path)
        )
        == "nested-session"
    )


def test_display_name_is_none_when_the_transcript_is_absent(tmp_path) -> None:
    assert (
        read_session_display_name_from_transcript(
            "missing-session", "/home/user/project", str(tmp_path)
        )
        is None
    )


def test_display_name_is_none_when_the_transcript_never_names_the_session(
    tmp_path,
) -> None:
    write_transcript_file(
        str(tmp_path), "/home/user/project", "unnamed", [json.dumps({"type": "user"})]
    )
    assert (
        read_session_display_name_from_transcript(
            "unnamed", "/home/user/project", str(tmp_path)
        )
        is None
    )


def test_the_last_display_name_record_wins(tmp_path) -> None:
    write_transcript_file(
        str(tmp_path),
        "/home/user/project",
        "named",
        [
            json.dumps({"type": "agent-name", "agentName": "first name"}),
            json.dumps({"type": "user"}),
            json.dumps({"type": "agent-name", "agentName": "second name"}),
        ],
    )
    assert (
        read_session_display_name_from_transcript(
            "named", "/home/user/project", str(tmp_path)
        )
        == "second name"
    )


def test_unparsable_transcript_lines_do_not_break_display_name_reading(tmp_path) -> None:
    write_transcript_file(
        str(tmp_path),
        "/home/user/project",
        "noisy",
        [
            '{"type":"agent-name", TRUNCATED',
            json.dumps({"type": "agent-name", "agentName": "recovered name"}),
        ],
    )
    assert (
        read_session_display_name_from_transcript(
            "noisy", "/home/user/project", str(tmp_path)
        )
        == "recovered name"
    )
