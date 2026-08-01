"""Tests for resolving which base session a run should use, and its preamble.

The base preamble says only what a session needs in order to use the material
it is given. The instruction to emit a handoff block is not here — branches emit
it, so branches are told at fork time.
"""
from __future__ import annotations

import pytest

from context_handoff.startup.base_session_resolver import (
    BASE_SESSION_PREAMBLE_TEXT,
    BaseSessionNotDurableError,
    INTERRUPT_REPEAT_COUNT_TO_LEAVE_BASE_SESSION,
    resolve_base_session_for_startup,
)
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls
from tests.fakes.fake_user_interface_control_recording_all_calls import (
    FakeUserInterfaceControlRecordingAllCalls,
)

WORKING_DIRECTORY_UNDER_TEST = "/fake/project"
WINDOW_IDENTIFIER_UNDER_TEST = "context-handoff-window"


def resolve_base_session_without_really_waiting(
    fake_harness,
    fake_user_interface_control,
    base_session_identifier_to_resume=None,
):
    """Call the resolver with its startup grace collapsed to nothing."""
    return resolve_base_session_for_startup(
        harness=fake_harness,
        user_interface_control=fake_user_interface_control,
        working_directory=WORKING_DIRECTORY_UNDER_TEST,
        build_shared_window_identifier=lambda _base: WINDOW_IDENTIFIER_UNDER_TEST,
        base_session_identifier_to_resume=base_session_identifier_to_resume,
        sleep_for_seconds=lambda _seconds: None,
    )


def window_event_kinds(fake_user_interface_control) -> list[str]:
    return [
        event[0]
        for event in fake_user_interface_control.event_log_by_window_identifier[
            WINDOW_IDENTIFIER_UNDER_TEST
        ]
    ]


def test_creating_a_fresh_base_session_uses_the_preamble() -> None:
    fake_harness = FakeHarnessRecordingAllCalls()

    result = resolve_base_session_without_really_waiting(
        fake_harness, FakeUserInterfaceControlRecordingAllCalls()
    )

    assert fake_harness.created_base_session_preambles == [BASE_SESSION_PREAMBLE_TEXT]
    assert result.session_identifier
    assert result.was_newly_created is True


def test_the_base_session_is_created_in_the_window_and_never_headlessly() -> None:
    """The trust prompt can only be answered by a session that has a terminal."""
    fake_harness = FakeHarnessRecordingAllCalls()
    fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()

    resolve_base_session_without_really_waiting(
        fake_harness, fake_user_interface_control
    )

    launched_argv = [
        event[1]
        for event in fake_user_interface_control.event_log_by_window_identifier[
            WINDOW_IDENTIFIER_UNDER_TEST
        ]
        if event[0] == "run_command_line_in_shared_window"
    ]
    assert len(launched_argv) == 1
    assert "-p" not in launched_argv[0]
    assert "--print" not in launched_argv[0]
    # Nothing to resume from: this launch is what brings the session into being.
    assert "--resume" not in launched_argv[0]


def test_the_trust_prompt_is_answered_before_durability_is_awaited() -> None:
    """Waiting first would wait forever: the prompt blocks the session's start."""
    fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()

    resolve_base_session_without_really_waiting(
        FakeHarnessRecordingAllCalls(), fake_user_interface_control
    )

    event_kinds = window_event_kinds(fake_user_interface_control)
    assert event_kinds.index("run_command_line_in_shared_window") < event_kinds.index(
        "send_confirmation_keypress_to_shared_window"
    )


def test_the_base_session_is_interrupted_out_of_once_it_is_durable() -> None:
    """From here the base is only ever spoken to without a terminal."""
    fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()

    resolve_base_session_without_really_waiting(
        FakeHarnessRecordingAllCalls(), fake_user_interface_control
    )

    interrupt_counts = [
        event[1]
        for event in fake_user_interface_control.event_log_by_window_identifier[
            WINDOW_IDENTIFIER_UNDER_TEST
        ]
        if event[0] == "send_interrupt_to_shared_window"
    ]
    assert interrupt_counts == [INTERRUPT_REPEAT_COUNT_TO_LEAVE_BASE_SESSION]


def test_a_base_session_that_never_reaches_disk_is_fatal() -> None:
    """Unlike a slow branch: without a base there is nothing to fork from."""
    fake_harness = FakeHarnessRecordingAllCalls()
    fake_harness.durability_wait_result = False

    with pytest.raises(BaseSessionNotDurableError):
        resolve_base_session_without_really_waiting(
            fake_harness, FakeUserInterfaceControlRecordingAllCalls()
        )


def test_resuming_a_named_base_session_creates_nothing() -> None:
    fake_harness = FakeHarnessRecordingAllCalls()
    fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()

    result = resolve_base_session_without_really_waiting(
        fake_harness,
        fake_user_interface_control,
        base_session_identifier_to_resume="an-existing-base",
    )

    assert fake_harness.created_base_session_preambles == []
    assert result.session_identifier == "an-existing-base"
    assert result.was_newly_created is False
    # And touches no window at all: there is nothing to create or to trust.
    assert fake_user_interface_control.event_log_by_window_identifier == {}


def test_an_empty_identifier_is_rejected_rather_than_treated_as_absent() -> None:
    """Silently creating a new base would strand the user's accumulated context."""
    with pytest.raises(ValueError):
        resolve_base_session_without_really_waiting(
            FakeHarnessRecordingAllCalls(),
            FakeUserInterfaceControlRecordingAllCalls(),
            base_session_identifier_to_resume="   ",
        )


def test_the_preamble_says_what_will_arrive_and_what_to_do_with_it() -> None:
    lowercased = BASE_SESSION_PREAMBLE_TEXT.lower()
    assert "user messages" in lowercased
    assert "work notes" in lowercased
    assert "factor these in" in lowercased


def test_the_preamble_tells_the_session_that_nothing_is_being_asked_yet() -> None:
    """Found in a real run, so it is pinned rather than left to be tidied away.

    The seed is delivered as a message, and the session answers it. With no
    closing sentence it went looking for a request, found none, and replied
    asking what the user wanted — which is the seed turn producing a reply to
    nobody.
    """
    assert "Stand by to receive." in BASE_SESSION_PREAMBLE_TEXT


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
