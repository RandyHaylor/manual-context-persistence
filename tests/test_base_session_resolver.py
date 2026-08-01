"""Tests for resolving which base session a run should use, and its preamble.

Spec 2 line 6 asks for one preamble, injected when the base session is created.
Branches are forked from the base, so they inherit it — there is no second
instruction layer, and an earlier version that added one is what drove the
handoffs into writing project encyclopedias.
"""
from __future__ import annotations

import json

import pytest

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    extract_context_to_keep_package_from_agent_response,
)
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


def test_the_preamble_states_the_handoff_format() -> None:
    """Branches inherit this, and it is the only place the format is stated."""
    assert CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG in BASE_SESSION_PREAMBLE_TEXT
    assert "summary_of_work_completed_this_turn" in BASE_SESSION_PREAMBLE_TEXT
    assert "context_to_carry_forward" in BASE_SESSION_PREAMBLE_TEXT
    assert (
        f'"context_to_keep_version": {CONTEXT_TO_KEEP_PACKAGE_VERSION}'
        in BASE_SESSION_PREAMBLE_TEXT
    )


def test_the_example_in_the_preamble_parses_as_a_real_package() -> None:
    """If the worked example does not parse, the format is taught wrong."""
    extracted = extract_context_to_keep_package_from_agent_response(
        BASE_SESSION_PREAMBLE_TEXT
    )
    assert extracted is not None


def test_the_preamble_keeps_recoverable_facts_out_of_the_handoff() -> None:
    """Spec 1 line 30: no full project memory.

    Without this, carried context fills with file state and script results —
    things the next session can simply look up — and it grows every turn.
    """
    lowercased = BASE_SESSION_PREAMBLE_TEXT.lower()
    assert "do not" in lowercased
    assert "reading the files" in lowercased
    assert "not asked for" in lowercased


def test_the_preamble_is_short() -> None:
    """It is inherited by every branch and prepended to the whole project."""
    assert len(BASE_SESSION_PREAMBLE_TEXT) < 1200


def test_the_preamble_is_stable_across_calls() -> None:
    from context_handoff.startup.base_session_resolver import (
        BASE_SESSION_PREAMBLE_TEXT as second_read,
    )

    assert BASE_SESSION_PREAMBLE_TEXT == second_read
