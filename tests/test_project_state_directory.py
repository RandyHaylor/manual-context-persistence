"""Tests for the one place that knows the project's on-disk layout.

Before this existed, four modules each hard-coded the .claude convention and
three of them hand-rolled the same corruption-tolerant JSON read/write. This
owns both, so a store can describe what it stores without also knowing where
files live or how to survive a half-written one.

Two locations are the substance of these tests. ``.claude`` belongs to the
harness and holds exactly one file we touch; everything of ours lives one level
down in its own folder, so nothing we write can collide with a file the harness
or another tool puts there.
"""
from __future__ import annotations

import json
import os

from context_handoff.project_state.project_state_directory import (
    APPLICATION_STATE_DIRECTORY_NAME,
    JsonDocumentFile,
    ProjectStateDirectory,
)


def application_document_for(tmp_path, document_file_name: str) -> JsonDocumentFile:
    return ProjectStateDirectory(str(tmp_path)).application_json_document(
        document_file_name
    )


def test_only_this_module_names_the_state_directory(tmp_path) -> None:
    """Guards the reason this module exists.

    Four modules previously hard-coded the layout. Each new one is another
    place that has to be found and changed together, and another chance for
    them to disagree.
    """
    import pathlib

    package_root = pathlib.Path(__file__).resolve().parent.parent / "context_handoff"
    modules_naming_the_state_directory = [
        module_path.name
        for module_path in package_root.rglob("*.py")
        if '".claude"' in module_path.read_text(encoding="utf-8")
    ]
    assert modules_naming_the_state_directory == ["project_state_directory.py"]


def test_the_harness_directory_is_dot_claude_inside_the_project(tmp_path) -> None:
    state_directory = ProjectStateDirectory(str(tmp_path))
    assert state_directory.harness_directory_path == os.path.join(
        str(tmp_path), ".claude"
    )


def test_our_directory_is_named_for_this_repository_inside_dot_claude(tmp_path) -> None:
    state_directory = ProjectStateDirectory(str(tmp_path))
    assert state_directory.application_directory_path == os.path.join(
        str(tmp_path), ".claude", "manual-context-persistence"
    )
    assert APPLICATION_STATE_DIRECTORY_NAME == "manual-context-persistence"


def test_a_harness_document_sits_directly_in_dot_claude(tmp_path) -> None:
    """settings.local.json is read by the harness, so it cannot move."""
    document = ProjectStateDirectory(str(tmp_path)).harness_json_document(
        "settings.local.json"
    )
    assert document.file_path == os.path.join(
        str(tmp_path), ".claude", "settings.local.json"
    )


def test_one_of_our_documents_lives_in_our_own_folder(tmp_path) -> None:
    document = application_document_for(tmp_path, "thing.json")
    assert document.file_path == os.path.join(
        str(tmp_path), ".claude", "manual-context-persistence", "thing.json"
    )


def test_a_named_subdirectory_path_is_offered_without_being_created(tmp_path) -> None:
    """Callers decide when to create; asking for a path must not touch disk."""
    state_directory = ProjectStateDirectory(str(tmp_path))
    subdirectory_path = state_directory.application_subdirectory_path("history")
    assert subdirectory_path.endswith(
        os.path.join(".claude", "manual-context-persistence", "history")
    )
    assert not os.path.exists(subdirectory_path)


def test_our_directory_can_be_created_on_demand_and_twice_is_harmless(tmp_path) -> None:
    """Startup creates it, and startup runs again on the next launch."""
    state_directory = ProjectStateDirectory(str(tmp_path))
    assert not os.path.isdir(state_directory.application_directory_path)
    created_path = state_directory.create_application_directory()
    assert os.path.isdir(created_path)
    assert state_directory.create_application_directory() == created_path


def test_reading_a_document_that_was_never_written_gives_the_default(tmp_path) -> None:
    document = application_document_for(tmp_path, "absent.json")
    assert document.read_dictionary_or_default({"fallback": True}) == {"fallback": True}


def test_a_written_document_reads_back(tmp_path) -> None:
    document = application_document_for(tmp_path, "thing.json")
    document.write_dictionary({"answer": 42})
    assert document.read_dictionary_or_default({}) == {"answer": 42}


def test_writing_creates_our_folder_and_the_harness_directory_above_it(
    tmp_path,
) -> None:
    document = application_document_for(tmp_path, "thing.json")
    document.write_dictionary({"answer": 42})
    assert os.path.isdir(
        os.path.join(str(tmp_path), ".claude", "manual-context-persistence")
    )


def test_a_corrupt_document_reads_as_the_default(tmp_path) -> None:
    """Writers here include agents and hooks; a half-written file is expected."""
    document = application_document_for(tmp_path, "thing.json")
    document.write_dictionary({"answer": 42})
    with open(document.file_path, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    assert document.read_dictionary_or_default({"fallback": True}) == {"fallback": True}


def test_a_document_holding_a_non_object_reads_as_the_default(tmp_path) -> None:
    document = application_document_for(tmp_path, "thing.json")
    os.makedirs(os.path.dirname(document.file_path), exist_ok=True)
    with open(document.file_path, "w", encoding="utf-8") as handle:
        json.dump([1, 2, 3], handle)
    assert document.read_dictionary_or_default({"fallback": True}) == {"fallback": True}


def test_an_empty_document_reads_as_the_default(tmp_path) -> None:
    """Emptied on purpose after rotation; that means "nothing here", not broken."""
    document = application_document_for(tmp_path, "thing.json")
    document.write_empty()
    assert document.read_dictionary_or_default({"fallback": True}) == {"fallback": True}


def test_write_empty_leaves_the_file_present_but_blank(tmp_path) -> None:
    document = application_document_for(tmp_path, "thing.json")
    document.write_dictionary({"answer": 42})
    document.write_empty()
    assert os.path.exists(document.file_path)
    assert os.path.getsize(document.file_path) == 0


def test_holds_content_reports_only_real_content(tmp_path) -> None:
    document = application_document_for(tmp_path, "thing.json")
    assert document.holds_content() is False
    document.write_empty()
    assert document.holds_content() is False
    document.write_dictionary({"answer": 42})
    assert document.holds_content() is True


def test_exists_reports_the_file_even_when_its_content_is_unusable(tmp_path) -> None:
    """Startup must tell "not set up yet" from "set up, and I cannot read it".

    Collapsing the two would let startup overwrite a settings file someone
    meant to keep, in order to fix a typo for them.
    """
    document = application_document_for(tmp_path, "thing.json")
    assert document.exists() is False
    document.write_empty()
    assert document.exists() is True
    assert document.holds_content() is False


def test_the_written_file_is_human_readable_json(tmp_path) -> None:
    """These files are inspected by hand when a handoff looks wrong."""
    document = application_document_for(tmp_path, "thing.json")
    document.write_dictionary({"answer": 42, "text": "curly “quotes” kept"})
    with open(document.file_path, "r", encoding="utf-8") as handle:
        raw_text = handle.read()
    assert "\n" in raw_text
    assert "curly “quotes” kept" in raw_text
    assert json.loads(raw_text)["answer"] == 42
