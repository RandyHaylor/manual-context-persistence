"""Tests for the on-disk context-to-keep file and its rotation into history.

The timestamp generator is injected so filenames are deterministic; a real
clock would make the history assertions untestable.
"""
from __future__ import annotations

import json
import os

import pytest

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    ContextToKeepPackage,
)


def build_store_with_scripted_timestamps(
    project_directory, timestamp_texts: list[str]
) -> ContextToKeepFileStore:
    remaining_timestamp_texts = list(timestamp_texts)

    def generate_next_timestamp_text() -> str:
        return remaining_timestamp_texts.pop(0)

    return ContextToKeepFileStore(
        project_directory=str(project_directory),
        generate_timestamp_text=generate_next_timestamp_text,
    )


def build_package(summary_text: str = "did the thing") -> ContextToKeepPackage:
    return ContextToKeepPackage(
        next_task="Ask the user which pad naming should win.", context_to_keep=[summary_text]
    )


def test_reading_before_anything_is_written_returns_none(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, [])
    assert store.read_pending_context_to_keep_package() is None


def test_reading_an_empty_file_returns_none(tmp_path) -> None:
    """A rotated file is left empty on purpose; empty means 'nothing pending'."""
    store = build_store_with_scripted_timestamps(tmp_path, [])
    os.makedirs(os.path.dirname(store.context_to_keep_file_path), exist_ok=True)
    with open(store.context_to_keep_file_path, "w", encoding="utf-8"):
        pass
    assert store.read_pending_context_to_keep_package() is None


def test_reading_a_malformed_file_returns_none_rather_than_raising(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, [])
    os.makedirs(os.path.dirname(store.context_to_keep_file_path), exist_ok=True)
    with open(store.context_to_keep_file_path, "w", encoding="utf-8") as pending_file:
        pending_file.write("{ not json")
    assert store.read_pending_context_to_keep_package() is None


def test_a_written_package_reads_back_intact(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, [])
    store.write_pending_context_to_keep_package(build_package())
    read_back_package = store.read_pending_context_to_keep_package()
    assert read_back_package == build_package()


def test_the_written_file_records_the_package_version(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, [])
    store.write_pending_context_to_keep_package(build_package())
    with open(store.context_to_keep_file_path, "r", encoding="utf-8") as pending_file:
        written_dictionary = json.load(pending_file)
    assert written_dictionary["context_to_keep_version"] == CONTEXT_TO_KEEP_PACKAGE_VERSION


def test_rotation_moves_the_file_into_history_under_its_timestamp(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, ["20260728T120000Z"])
    store.write_pending_context_to_keep_package(build_package())

    history_path = store.rotate_pending_context_to_keep_into_history()

    assert history_path.endswith("context-to-keep-20260728T120000Z.json")
    assert os.path.exists(history_path)


def test_rotation_leaves_an_empty_pending_file_ready_for_the_next_turn(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, ["20260728T120000Z"])
    store.write_pending_context_to_keep_package(build_package())

    store.rotate_pending_context_to_keep_into_history()

    assert os.path.exists(store.context_to_keep_file_path)
    assert store.read_pending_context_to_keep_package() is None


def test_the_rotated_history_entry_keeps_the_package_and_adds_the_timestamp(
    tmp_path,
) -> None:
    store = build_store_with_scripted_timestamps(tmp_path, ["20260728T120000Z"])
    store.write_pending_context_to_keep_package(build_package("did the thing"))

    history_path = store.rotate_pending_context_to_keep_into_history()

    with open(history_path, "r", encoding="utf-8") as history_file:
        archived_dictionary = json.load(history_file)
    assert archived_dictionary["context_to_keep"] == ["did the thing"]
    assert archived_dictionary["rotated_at_timestamp"] == "20260728T120000Z"


def test_rotating_with_nothing_pending_raises(tmp_path) -> None:
    """Rotating an empty file would archive nothing and hide a real bug."""
    store = build_store_with_scripted_timestamps(tmp_path, ["20260728T120000Z"])
    with pytest.raises(FileNotFoundError):
        store.rotate_pending_context_to_keep_into_history()


def test_successive_rotations_accumulate_in_history(tmp_path) -> None:
    store = build_store_with_scripted_timestamps(
        tmp_path, ["20260728T120000Z", "20260728T130000Z"]
    )
    store.write_pending_context_to_keep_package(build_package("first turn"))
    store.rotate_pending_context_to_keep_into_history()
    store.write_pending_context_to_keep_package(build_package("second turn"))
    store.rotate_pending_context_to_keep_into_history()

    assert sorted(os.listdir(store.context_to_keep_history_directory)) == [
        "context-to-keep-20260728T120000Z.json",
        "context-to-keep-20260728T130000Z.json",
    ]


def test_a_history_filename_collision_does_not_overwrite_the_earlier_entry(
    tmp_path,
) -> None:
    """Two turns inside one timestamp tick must not lose the first handoff."""
    store = build_store_with_scripted_timestamps(
        tmp_path, ["20260728T120000Z", "20260728T120000Z"]
    )
    store.write_pending_context_to_keep_package(build_package("first turn"))
    first_history_path = store.rotate_pending_context_to_keep_into_history()
    store.write_pending_context_to_keep_package(build_package("second turn"))
    second_history_path = store.rotate_pending_context_to_keep_into_history()

    assert first_history_path != second_history_path
    assert len(os.listdir(store.context_to_keep_history_directory)) == 2


def test_change_detection_reports_new_content_once(tmp_path) -> None:
    """The turn loop polls this file; a turn must not be processed twice."""
    store = build_store_with_scripted_timestamps(tmp_path, ["20260728T120000Z"])
    assert store.has_pending_context_to_keep() is False

    store.write_pending_context_to_keep_package(build_package())
    assert store.has_pending_context_to_keep() is True

    store.rotate_pending_context_to_keep_into_history()
    assert store.has_pending_context_to_keep() is False
