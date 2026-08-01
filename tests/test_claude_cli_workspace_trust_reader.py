"""Tests for reading whether a project directory has been trusted yet.

This matters beyond the prompt itself. The documentation states that project
settings are honoured "only after you accept the workspace trust dialog", and
this system's capture hooks live in project settings — so an untrusted
directory means a branch that launches, waits on a prompt, and records nothing.

The state file location is injected, so these tests never read the developer's
real one. The key name was confirmed by inspecting a real file rather than
guessed; it is undocumented, so an unreadable or absent answer is reported as
unknown rather than as untrusted.
"""
from __future__ import annotations

import json

from context_handoff.adapters.claude_cli.claude_cli_workspace_trust_reader import (
    read_whether_project_directory_is_trusted,
)


def write_state(tmp_path, projects: dict) -> str:
    state_path = str(tmp_path / "claude.json")
    with open(state_path, "w", encoding="utf-8") as state_file:
        json.dump({"projects": projects}, state_file)
    return state_path


def test_a_trusted_directory_reads_as_trusted(tmp_path) -> None:
    state_path = write_state(tmp_path, {"/a/project": {"hasTrustDialogAccepted": True}})
    assert read_whether_project_directory_is_trusted("/a/project", state_path) is True


def test_an_untrusted_directory_reads_as_untrusted(tmp_path) -> None:
    state_path = write_state(tmp_path, {"/a/project": {"hasTrustDialogAccepted": False}})
    assert read_whether_project_directory_is_trusted("/a/project", state_path) is False


def test_a_directory_the_cli_has_never_seen_is_unknown(tmp_path) -> None:
    """Never opened is not the same as declined, and the difference matters."""
    state_path = write_state(tmp_path, {"/another/project": {}})
    assert read_whether_project_directory_is_trusted("/a/project", state_path) is None


def test_an_entry_without_the_key_is_unknown(tmp_path) -> None:
    state_path = write_state(tmp_path, {"/a/project": {"allowedTools": []}})
    assert read_whether_project_directory_is_trusted("/a/project", state_path) is None


def test_a_missing_state_file_is_unknown(tmp_path) -> None:
    assert (
        read_whether_project_directory_is_trusted(
            "/a/project", str(tmp_path / "absent.json")
        )
        is None
    )


def test_an_unreadable_state_file_is_unknown_rather_than_untrusted(tmp_path) -> None:
    """This reads undocumented state; a wrong guess must not become a warning."""
    state_path = str(tmp_path / "claude.json")
    with open(state_path, "w", encoding="utf-8") as state_file:
        state_file.write("{ not json")
    assert read_whether_project_directory_is_trusted("/a/project", state_path) is None


def test_a_non_boolean_value_is_unknown(tmp_path) -> None:
    state_path = write_state(
        tmp_path, {"/a/project": {"hasTrustDialogAccepted": "yes please"}}
    )
    assert read_whether_project_directory_is_trusted("/a/project", state_path) is None


def test_the_lookup_uses_the_absolute_directory(tmp_path) -> None:
    state_path = write_state(tmp_path, {"/a/project": {"hasTrustDialogAccepted": True}})
    assert read_whether_project_directory_is_trusted("/a/project/", state_path) is True
