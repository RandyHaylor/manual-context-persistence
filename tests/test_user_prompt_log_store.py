"""Tests for the verbatim user-prompt log.

The log's whole value is that it stores what the user actually typed, so the
tests are mostly about what must NOT happen to the text: no trimming, no
normalising, no reordering. Pre-submission context is capped because it is
context, not the requirement itself.
"""
from __future__ import annotations

import json
import os

from context_handoff.user_prompt_log.user_prompt_log_store import (
    MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS,
    UserPromptLogStore,
)


def build_store(tmp_path) -> UserPromptLogStore:
    return UserPromptLogStore(project_directory=str(tmp_path))


def test_reading_before_anything_is_logged_returns_no_entries(tmp_path) -> None:
    assert build_store(tmp_path).read_entries_for_session("session-a") == []


def test_an_appended_prompt_reads_back_for_its_session(tmp_path) -> None:
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "do the thing")
    entries = store.read_entries_for_session("session-a")
    assert len(entries) == 1
    assert entries[0].user_prompt_text == "do the thing"
    assert entries[0].session_identifier == "session-a"


def test_prompt_text_is_stored_byte_for_byte(tmp_path) -> None:
    """Verbatim means verbatim: no strip, no collapse, no unicode folding."""
    store = build_store(tmp_path)
    awkward_prompt_text = "  leading and trailing  \n\ttabs\tand “curly quotes”  "
    store.append_user_prompt_entry("session-a", awkward_prompt_text)
    assert (
        store.read_entries_for_session("session-a")[0].user_prompt_text
        == awkward_prompt_text
    )


def test_entries_are_returned_in_submission_order(tmp_path) -> None:
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "first")
    store.append_user_prompt_entry("session-a", "second")
    store.append_user_prompt_entry("session-a", "third")
    assert [
        entry.user_prompt_text for entry in store.read_entries_for_session("session-a")
    ] == ["first", "second", "third"]


def test_entries_are_scoped_to_their_session(tmp_path) -> None:
    """Each branch is a separate session; a handoff must not pull in another's."""
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "for a")
    store.append_user_prompt_entry("session-b", "for b")
    assert [
        entry.user_prompt_text for entry in store.read_entries_for_session("session-a")
    ] == ["for a"]


def test_pre_submission_content_is_capped_at_the_documented_limit(tmp_path) -> None:
    store = build_store(tmp_path)
    oversized_pre_submission_content = "x" * (
        MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS + 500
    )
    store.append_user_prompt_entry(
        "session-a", "prompt", pre_submission_content=oversized_pre_submission_content
    )
    stored_entry = store.read_entries_for_session("session-a")[0]
    assert (
        len(stored_entry.pre_submission_content)
        == MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS
    )


def test_capping_keeps_the_end_of_the_pre_submission_content(tmp_path) -> None:
    """The text immediately before the prompt is the part that gives it meaning."""
    store = build_store(tmp_path)
    pre_submission_content = (
        "y" * MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS + "THE QUESTION ASKED"
    )
    store.append_user_prompt_entry(
        "session-a", "yes", pre_submission_content=pre_submission_content
    )
    stored_entry = store.read_entries_for_session("session-a")[0]
    assert stored_entry.pre_submission_content.endswith("THE QUESTION ASKED")


def test_prompt_text_is_never_capped(tmp_path) -> None:
    store = build_store(tmp_path)
    very_long_prompt_text = "z" * (MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS * 3)
    store.append_user_prompt_entry("session-a", very_long_prompt_text)
    assert (
        store.read_entries_for_session("session-a")[0].user_prompt_text
        == very_long_prompt_text
    )


def test_the_log_survives_a_new_store_instance(tmp_path) -> None:
    build_store(tmp_path).append_user_prompt_entry("session-a", "persisted")
    assert (
        build_store(tmp_path).read_entries_for_session("session-a")[0].user_prompt_text
        == "persisted"
    )


def test_a_corrupt_log_file_reads_as_empty_rather_than_raising(tmp_path) -> None:
    """A broken log must not stop the hook that is trying to append to it."""
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "first")
    with open(store.user_prompt_log_file_path, "w", encoding="utf-8") as log_file:
        log_file.write("{ not json")
    assert store.read_entries_for_session("session-a") == []


def test_appending_after_corruption_starts_a_usable_log_again(tmp_path) -> None:
    store = build_store(tmp_path)
    os.makedirs(os.path.dirname(store.user_prompt_log_file_path), exist_ok=True)
    with open(store.user_prompt_log_file_path, "w", encoding="utf-8") as log_file:
        log_file.write("{ not json")
    store.append_user_prompt_entry("session-a", "after corruption")
    assert [
        entry.user_prompt_text for entry in store.read_entries_for_session("session-a")
    ] == ["after corruption"]


def test_the_log_file_is_valid_json_on_disk(tmp_path) -> None:
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "readable by other tools")
    with open(store.user_prompt_log_file_path, "r", encoding="utf-8") as log_file:
        decoded_log = json.load(log_file)
    assert decoded_log["entries"][0]["user_prompt_text"] == "readable by other tools"


def test_unconsumed_entries_can_be_marked_consumed_for_a_session(tmp_path) -> None:
    """A handoff must not resend prompts the base session already received."""
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "first")
    store.append_user_prompt_entry("session-a", "second")

    unconsumed_entries = store.read_unconsumed_entries_for_session("session-a")
    assert len(unconsumed_entries) == 2

    store.mark_entries_consumed(entry.entry_identifier for entry in unconsumed_entries)
    assert store.read_unconsumed_entries_for_session("session-a") == []
    assert len(store.read_entries_for_session("session-a")) == 2


def test_a_prompt_arriving_after_consumption_is_still_unconsumed(tmp_path) -> None:
    """Mid-turn prompts land after the swap began; the next handoff must carry them."""
    store = build_store(tmp_path)
    store.append_user_prompt_entry("session-a", "first")
    store.mark_entries_consumed(
        entry.entry_identifier
        for entry in store.read_unconsumed_entries_for_session("session-a")
    )
    store.append_user_prompt_entry("session-a", "sent while the agent was working")

    remaining_unconsumed = store.read_unconsumed_entries_for_session("session-a")
    assert [entry.user_prompt_text for entry in remaining_unconsumed] == [
        "sent while the agent was working"
    ]
