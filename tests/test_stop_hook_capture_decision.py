"""Tests for the Stop hook's decision, separated from its file access.

The hook previously folded five outcomes into one silent empty response, so a
live failure could not be told apart from a normal quiet turn. The decision is
now a value: pure inputs in, a named outcome out.

Nothing here touches a disk or a transcript.
"""
from __future__ import annotations

import json

import pytest

from context_handoff.hooks.stop_hook_capture_decision import (
    CaptureDecision,
    CaptureOutcome,
    decide_whether_to_capture_handoff,
)
from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
)


def build_reply_containing_a_package(summary_text: str = "Did the thing.") -> str:
    package_json = json.dumps(
        {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "next_task": "Ask the user which pad naming should win.",
            "context_to_keep": [summary_text],
        }
    )
    return f"Some prose.\n\n```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{package_json}\n```"


def test_a_reply_carrying_a_package_is_captured() -> None:
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=build_reply_containing_a_package("Did the thing."),
        a_handoff_is_already_pending=False,
    )
    assert decision.outcome is CaptureOutcome.CAPTURED
    assert decision.package is not None
    assert decision.package.context_to_keep == ["Did the thing."]


def test_a_session_the_user_does_not_work_in_is_never_captured_from() -> None:
    """The base session ends turns too, and its replies are not handoffs.

    Observed in a driven run: delivering a handoff is a resume against the base
    session, which ends a turn and fires this hook. The base's acknowledgement
    was inspected for a package. It was only harmless because something else
    happened to block it.
    """
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=build_reply_containing_a_package(),
        a_handoff_is_already_pending=False,
        session_is_user_facing=False,
    )
    assert decision.outcome is CaptureOutcome.NOT_A_USER_FACING_SESSION
    assert decision.package is None


def test_the_user_facing_check_precedes_every_other_reason() -> None:
    """A reply from elsewhere is not ours to judge on any other ground."""
    for pending in (True, False):
        for reply_text in (None, "ordinary", build_reply_containing_a_package()):
            decision = decide_whether_to_capture_handoff(
                last_agent_reply_text=reply_text,
                a_handoff_is_already_pending=pending,
                session_is_user_facing=False,
            )
            assert decision.outcome is CaptureOutcome.NOT_A_USER_FACING_SESSION


def test_a_user_facing_session_is_the_default() -> None:
    """Existing callers keep working; the gate is opt-in for the hook."""
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=build_reply_containing_a_package(),
        a_handoff_is_already_pending=False,
    )
    assert decision.outcome is CaptureOutcome.CAPTURED


def test_an_ordinary_reply_is_declined_as_having_no_package() -> None:
    """Most turns end without a handoff; that is normal, not a failure."""
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text="Just an ordinary reply.",
        a_handoff_is_already_pending=False,
    )
    assert decision.outcome is CaptureOutcome.NO_PACKAGE_IN_REPLY
    assert decision.package is None


def test_a_missing_reply_is_its_own_outcome() -> None:
    """Distinct from "no package": it means the transcript gave us nothing."""
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=None, a_handoff_is_already_pending=False
    )
    assert decision.outcome is CaptureOutcome.NO_AGENT_REPLY_FOUND


def test_an_empty_reply_counts_as_no_reply() -> None:
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text="   ", a_handoff_is_already_pending=False
    )
    assert decision.outcome is CaptureOutcome.NO_AGENT_REPLY_FOUND


def test_a_malformed_package_is_reported_separately_from_no_package() -> None:
    """Tells a broken protocol apart from a turn that simply had nothing."""
    malformed_reply = (
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ not valid json \n```"
    )
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=malformed_reply, a_handoff_is_already_pending=False
    )
    assert decision.outcome is CaptureOutcome.PACKAGE_PRESENT_BUT_UNUSABLE
    assert decision.package is None


def test_a_package_missing_a_required_field_is_unusable_not_absent() -> None:
    incomplete_package_json = json.dumps(
        {"context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION}
    )
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=(
            f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{incomplete_package_json}\n```"
        ),
        a_handoff_is_already_pending=False,
    )
    assert decision.outcome is CaptureOutcome.PACKAGE_PRESENT_BUT_UNUSABLE


def test_an_unconsumed_handoff_is_never_overwritten() -> None:
    """The pending one belongs to a turn the loop has not processed yet."""
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=build_reply_containing_a_package(),
        a_handoff_is_already_pending=True,
    )
    assert decision.outcome is CaptureOutcome.EARLIER_HANDOFF_STILL_PENDING
    assert decision.package is None


def test_the_pending_check_takes_priority_over_a_malformed_package() -> None:
    """Reporting the pending handoff is the more actionable of the two."""
    decision = decide_whether_to_capture_handoff(
        last_agent_reply_text=f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ bad \n```",
        a_handoff_is_already_pending=True,
    )
    assert decision.outcome is CaptureOutcome.EARLIER_HANDOFF_STILL_PENDING


def test_every_outcome_carries_a_human_readable_reason() -> None:
    """The reason is what a person reads when a live run captured nothing."""
    for reply_text, pending in (
        (build_reply_containing_a_package(), False),
        ("ordinary reply", False),
        (None, False),
        (f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ bad \n```", False),
        (build_reply_containing_a_package(), True),
    ):
        decision = decide_whether_to_capture_handoff(reply_text, pending)
        assert isinstance(decision, CaptureDecision)
        assert decision.reason_text
        assert decision.outcome.value in decision.reason_text


def test_only_the_captured_outcome_carries_a_package() -> None:
    for reply_text, pending in (
        ("ordinary reply", False),
        (None, False),
        (build_reply_containing_a_package(), True),
    ):
        assert decide_whether_to_capture_handoff(reply_text, pending).package is None


@pytest.mark.parametrize("outcome", list(CaptureOutcome))
def test_outcome_names_are_stable_identifiers(outcome: CaptureOutcome) -> None:
    """These are written to disk for diagnosis, so they must not be prose."""
    assert outcome.value == outcome.value.lower()
    assert " " not in outcome.value
