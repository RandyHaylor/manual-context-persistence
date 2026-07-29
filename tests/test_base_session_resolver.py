"""Tests for resolving which base session a run should use.

Startup either resumes a base the user names or creates a fresh one from the
preamble. The choice itself is the caller's — this resolver only carries it
out, which is what makes it testable.
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


def test_the_preamble_tells_the_base_session_to_only_accumulate() -> None:
    """The base must never start doing the work described in a handoff."""
    lowercased_preamble = BASE_SESSION_PREAMBLE_TEXT.lower()
    assert "acknowledge" in lowercased_preamble
    assert "do not" in lowercased_preamble
