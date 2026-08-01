"""Tests for resolving which base session a run should use, and its preamble.

The base preamble says only what a session needs in order to use the material
it is given. The instruction to emit a handoff block is not here — branches emit
it, so branches are told at fork time.
"""
from __future__ import annotations

import pytest

from context_handoff.startup.base_session_resolver import (
    BASE_SESSION_PREAMBLE_TEXT,
    resolve_base_session_for_startup,
)
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls

WORKING_DIRECTORY_UNDER_TEST = "/fake/project"


def test_creating_a_fresh_base_session_uses_the_preamble() -> None:
    fake_harness = FakeHarnessRecordingAllCalls()

    result = resolve_base_session_for_startup(
        harness=fake_harness,
        working_directory=WORKING_DIRECTORY_UNDER_TEST,
        base_session_identifier_to_resume=None,
    )

    assert fake_harness.created_base_session_preambles == [BASE_SESSION_PREAMBLE_TEXT]
    assert result.session_identifier
    assert result.was_newly_created is True


def test_resuming_a_named_base_session_creates_nothing() -> None:
    fake_harness = FakeHarnessRecordingAllCalls()

    result = resolve_base_session_for_startup(
        harness=fake_harness,
        working_directory=WORKING_DIRECTORY_UNDER_TEST,
        base_session_identifier_to_resume="an-existing-base",
    )

    assert fake_harness.created_base_session_preambles == []
    assert result.session_identifier == "an-existing-base"
    assert result.was_newly_created is False


def test_an_empty_identifier_is_rejected_rather_than_treated_as_absent() -> None:
    """Silently creating a new base would strand the user's accumulated context."""
    with pytest.raises(ValueError):
        resolve_base_session_for_startup(
            harness=FakeHarnessRecordingAllCalls(),
            working_directory=WORKING_DIRECTORY_UNDER_TEST,
            base_session_identifier_to_resume="   ",
        )


def test_the_preamble_says_what_will_arrive_and_what_to_do_with_it() -> None:
    lowercased = BASE_SESSION_PREAMBLE_TEXT.lower()
    assert "user messages" in lowercased
    assert "work notes" in lowercased
    assert "factor these in" in lowercased


def test_the_preamble_does_not_carry_the_block_instruction() -> None:
    """Branches emit the block, so branches are told about it, not everyone."""
    assert "context_to_keep" not in BASE_SESSION_PREAMBLE_TEXT
    assert "```" not in BASE_SESSION_PREAMBLE_TEXT


def test_the_preamble_never_describes_the_machinery() -> None:
    """Every working session inherits this by forking, and reads it."""
    lowercased = BASE_SESSION_PREAMBLE_TEXT.lower()
    for machinery_word in (
        "base session",
        "branch",
        "fork",
        "handoff",
        "short-lived",
        "resumed",
        "acknowledge",
        "orchestrat",
        "rotation",
    ):
        assert machinery_word not in lowercased, (
            f"the preamble mentions {machinery_word!r}; every working session reads it"
        )


def test_the_preamble_never_governs_how_the_agent_replies() -> None:
    """Anything here that shapes replies shapes replies to the user."""
    lowercased = BASE_SESSION_PREAMBLE_TEXT.lower()
    for reply_instruction in (
        "one short sentence",
        "reply with",
        "briefly",
        "be brief",
        "do nothing else",
        "and nothing else",
    ):
        assert reply_instruction not in lowercased


def test_the_preamble_is_short() -> None:
    """It is inherited by every session and prepended to the whole project."""
    assert len(BASE_SESSION_PREAMBLE_TEXT) < 200
