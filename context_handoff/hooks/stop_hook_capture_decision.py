"""Should this turn's reply be captured as a handoff, and if not, why not?

Split out of the hook itself because the hook had folded five different
outcomes into one silent empty response. When a live run captured nothing there
was no way to tell "the agent emitted no package" from "the package was
malformed" from "the hook never really ran" — all three looked identical from
outside.

Pure by design: values in, a named outcome out. No transcript, no disk, no
exception handling. The hook keeps those, and keeps them small.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    ContextToKeepPackage,
    extract_context_to_keep_package_from_agent_response,
)


class CaptureOutcome(Enum):
    """Why the hook did what it did. Values are written to disk for diagnosis."""

    CAPTURED = "captured"
    NO_AGENT_REPLY_FOUND = "no_agent_reply_found"
    NO_PACKAGE_IN_REPLY = "no_package_in_reply"
    PACKAGE_PRESENT_BUT_UNUSABLE = "package_present_but_unusable"
    EARLIER_HANDOFF_STILL_PENDING = "earlier_handoff_still_pending"
    NOT_A_USER_FACING_SESSION = "not_a_user_facing_session"
    UNEXPECTED_FAILURE = "unexpected_failure"


_REASON_TEXT_BY_OUTCOME = {
    CaptureOutcome.CAPTURED: "captured: the reply carried a usable handoff package",
    CaptureOutcome.NO_AGENT_REPLY_FOUND: (
        "no_agent_reply_found: the transcript yielded no agent reply for this turn"
    ),
    CaptureOutcome.NO_PACKAGE_IN_REPLY: (
        "no_package_in_reply: the agent replied but emitted no handoff block"
    ),
    CaptureOutcome.PACKAGE_PRESENT_BUT_UNUSABLE: (
        "package_present_but_unusable: a handoff block was present but could not "
        "be parsed into a valid package"
    ),
    CaptureOutcome.EARLIER_HANDOFF_STILL_PENDING: (
        "earlier_handoff_still_pending: a previous handoff has not been consumed "
        "yet and must not be overwritten"
    ),
    CaptureOutcome.NOT_A_USER_FACING_SESSION: (
        "not_a_user_facing_session: this turn belongs to a session the user does "
        "not work in, so its reply is not a handoff"
    ),
    CaptureOutcome.UNEXPECTED_FAILURE: (
        "unexpected_failure: the hook raised before it could reach a decision"
    ),
}


@dataclass(frozen=True)
class CaptureDecision:
    outcome: CaptureOutcome
    reason_text: str
    package: Optional[ContextToKeepPackage] = None


def _build_decision(
    outcome: CaptureOutcome, package: Optional[ContextToKeepPackage] = None
) -> CaptureDecision:
    return CaptureDecision(
        outcome=outcome, reason_text=_REASON_TEXT_BY_OUTCOME[outcome], package=package
    )


def decide_whether_to_capture_handoff(
    last_agent_reply_text: Optional[str],
    a_handoff_is_already_pending: bool,
    session_is_user_facing: bool = True,
) -> CaptureDecision:
    """Decide, and say why.

    Ownership is settled first. The orchestrator drives sessions of its own —
    the base session most of all — and every one of them ends turns and reaches
    this hook. A reply from one of those is not a handoff, and judging it on
    any other ground would be answering the wrong question.

    The pending check comes next because it is the more actionable of the
    remaining answers: a stalled loop explains every later quiet turn, and
    reporting a parse problem instead would send a reader after the wrong
    thing.
    """
    if not session_is_user_facing:
        return _build_decision(CaptureOutcome.NOT_A_USER_FACING_SESSION)

    if a_handoff_is_already_pending:
        return _build_decision(CaptureOutcome.EARLIER_HANDOFF_STILL_PENDING)

    if not last_agent_reply_text or not last_agent_reply_text.strip():
        return _build_decision(CaptureOutcome.NO_AGENT_REPLY_FOUND)

    extracted_package = extract_context_to_keep_package_from_agent_response(
        last_agent_reply_text
    )
    if extracted_package is not None:
        return _build_decision(CaptureOutcome.CAPTURED, extracted_package)

    # A fence with nothing usable inside is a protocol problem worth naming
    # separately from a turn that simply had nothing to hand off.
    if f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}" in last_agent_reply_text:
        return _build_decision(CaptureOutcome.PACKAGE_PRESENT_BUT_UNUSABLE)

    return _build_decision(CaptureOutcome.NO_PACKAGE_IN_REPLY)
