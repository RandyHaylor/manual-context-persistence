"""Tests for the project's settings for this system.

Every setting has a default that is safe for a project with no git repository,
so an absent or unreadable file is an ordinary starting condition rather than an
error. What these tests pin down is that reading is total — no input makes it
raise — and that nothing overwrites a file the operator may have meant to keep.
"""
from __future__ import annotations

import json
import os

from context_handoff.project_state.context_handoff_settings_store import (
    ContextHandoffSettings,
    ContextHandoffSettingsStore,
    parse_context_handoff_settings,
)


def test_the_settings_file_lives_in_our_own_folder(tmp_path) -> None:
    store = ContextHandoffSettingsStore(str(tmp_path))
    assert store.settings_file_path == os.path.join(
        str(tmp_path), ".claude", "manual-context-persistence", "settings.json"
    )


def test_the_defaults_are_safe_for_a_project_with_no_repository() -> None:
    """A commit instruction in a directory with no repository is unfollowable."""
    defaults = ContextHandoffSettings()
    assert defaults.require_git_commit is False
    assert defaults.git_repository_url is None
    assert defaults.git_repository_is_local_only is False


def test_an_absent_file_reads_as_the_defaults(tmp_path) -> None:
    store = ContextHandoffSettingsStore(str(tmp_path))
    assert store.settings_file_exists() is False
    assert store.read_settings() == ContextHandoffSettings()


def test_written_settings_read_back(tmp_path) -> None:
    store = ContextHandoffSettingsStore(str(tmp_path))
    written_settings = ContextHandoffSettings(
        require_git_commit=True,
        git_repository_url="git@github.com:RandyHaylor/manual-context-persistence.git",
        git_repository_is_local_only=False,
    )
    store.write_settings(written_settings)
    assert store.read_settings() == written_settings


def test_a_local_only_repository_is_stated_rather_than_inferred(tmp_path) -> None:
    """Absent-URL and deliberately-no-remote are different states.

    Inferring the second from the first would make "not filled in yet" and
    "there is no remote" indistinguishable.
    """
    store = ContextHandoffSettingsStore(str(tmp_path))
    store.write_settings(
        ContextHandoffSettings(git_repository_is_local_only=True)
    )
    read_settings = store.read_settings()
    assert read_settings.git_repository_is_local_only is True
    assert read_settings.git_repository_url is None


def test_a_corrupt_file_reads_as_the_defaults(tmp_path) -> None:
    store = ContextHandoffSettingsStore(str(tmp_path))
    store.write_settings(ContextHandoffSettings(require_git_commit=True))
    with open(store.settings_file_path, "w", encoding="utf-8") as settings_file:
        settings_file.write("{ not json")
    assert store.read_settings() == ContextHandoffSettings()


def test_a_non_boolean_flag_falls_back_rather_than_being_guessed_at() -> None:
    """A hand-edited "true" is ambiguous enough that guessing is worse."""
    assert parse_context_handoff_settings(
        {"require_git_commit": "true"}
    ).require_git_commit is False
    assert parse_context_handoff_settings(
        {"require_git_commit": 1}
    ).require_git_commit is False


def test_a_blank_repository_url_reads_as_absent() -> None:
    assert parse_context_handoff_settings({"git_repository_url": "   "}).git_repository_url is None
    assert parse_context_handoff_settings({"git_repository_url": 7}).git_repository_url is None


def test_unknown_keys_are_ignored_rather_than_rejected() -> None:
    """An operator's own note in the file must not stop the run."""
    settings = parse_context_handoff_settings(
        {"require_git_commit": True, "_comment": "switched on for this project"}
    )
    assert settings.require_git_commit is True


def test_creating_defaults_reports_whether_it_created_anything(tmp_path) -> None:
    store = ContextHandoffSettingsStore(str(tmp_path))
    assert store.write_default_settings_if_absent() is True
    assert store.write_default_settings_if_absent() is False


def test_creating_defaults_never_overwrites_existing_settings(tmp_path) -> None:
    store = ContextHandoffSettingsStore(str(tmp_path))
    store.write_settings(ContextHandoffSettings(require_git_commit=True))

    store.write_default_settings_if_absent()

    assert store.read_settings().require_git_commit is True


def test_creating_defaults_leaves_an_unreadable_file_alone(tmp_path) -> None:
    """Overwriting would destroy settings someone meant to keep.

    A file that cannot be parsed is far more likely to be a typo than an
    invitation to replace it.
    """
    store = ContextHandoffSettingsStore(str(tmp_path))
    store.write_settings(ContextHandoffSettings(require_git_commit=True))
    with open(store.settings_file_path, "w", encoding="utf-8") as settings_file:
        settings_file.write("{ require_git_commit: yes")

    assert store.write_default_settings_if_absent() is False
    with open(store.settings_file_path, "r", encoding="utf-8") as settings_file:
        assert settings_file.read() == "{ require_git_commit: yes"


def test_the_written_file_names_every_setting(tmp_path) -> None:
    """It is a file an operator edits, so it must show what can be set."""
    store = ContextHandoffSettingsStore(str(tmp_path))
    store.write_default_settings_if_absent()
    with open(store.settings_file_path, "r", encoding="utf-8") as settings_file:
        written_dictionary = json.load(settings_file)
    assert set(written_dictionary) == {
        "require_git_commit",
        "git_repository_url",
        "git_repository_is_local_only",
    }


def test_no_override_leaves_the_stored_value_alone() -> None:
    """Not passing the flag is not the same as passing it as false."""
    stored_settings = ContextHandoffSettings(require_git_commit=True)
    assert stored_settings.with_require_git_commit_override(None) == stored_settings


def test_an_override_replaces_the_stored_value_either_way() -> None:
    switched_on = ContextHandoffSettings(require_git_commit=True)
    assert switched_on.with_require_git_commit_override(False).require_git_commit is False
    switched_off = ContextHandoffSettings(require_git_commit=False)
    assert switched_off.with_require_git_commit_override(True).require_git_commit is True


def test_an_override_changes_nothing_else() -> None:
    stored_settings = ContextHandoffSettings(
        require_git_commit=False,
        git_repository_url="git@example.com:project.git",
        git_repository_is_local_only=True,
    )
    overridden = stored_settings.with_require_git_commit_override(True)
    assert overridden.git_repository_url == stored_settings.git_repository_url
    assert (
        overridden.git_repository_is_local_only
        == stored_settings.git_repository_is_local_only
    )
