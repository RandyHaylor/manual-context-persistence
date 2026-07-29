"""Contract every UserInterfaceControlInterface implementation must satisfy.

The turn loop's central assumption is that ONE window survives many session
swaps, so these tests focus on idempotent open/close and on the window staying
alive across an interrupt-then-relaunch cycle.
"""
from __future__ import annotations

import pytest

from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)
from tests.fakes.fake_user_interface_control_recording_all_calls import (
    FakeUserInterfaceControlRecordingAllCalls,
)


WINDOW_IDENTIFIER_UNDER_TEST = "context-handoff-shared-window"
WORKING_DIRECTORY_UNDER_TEST = "/fake/project"


class UserInterfaceControlInterfaceContractTestSuite:
    """Subclass and override ``build_user_interface_control_under_test``."""

    def build_user_interface_control_under_test(self) -> UserInterfaceControlInterface:
        raise NotImplementedError

    def test_window_is_not_alive_before_it_is_opened(self) -> None:
        control = self.build_user_interface_control_under_test()
        assert control.is_shared_window_alive(WINDOW_IDENTIFIER_UNDER_TEST) is False

    def test_window_is_alive_after_opening(self) -> None:
        control = self.build_user_interface_control_under_test()
        control.open_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST
        )
        assert control.is_shared_window_alive(WINDOW_IDENTIFIER_UNDER_TEST) is True

    def test_opening_an_already_open_window_is_not_an_error(self) -> None:
        control = self.build_user_interface_control_under_test()
        control.open_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST
        )
        control.open_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST
        )
        assert control.is_shared_window_alive(WINDOW_IDENTIFIER_UNDER_TEST) is True

    def test_closing_an_absent_window_is_not_an_error(self) -> None:
        control = self.build_user_interface_control_under_test()
        control.close_shared_window(WINDOW_IDENTIFIER_UNDER_TEST)
        assert control.is_shared_window_alive(WINDOW_IDENTIFIER_UNDER_TEST) is False

    def test_window_survives_an_interrupt_and_relaunch_cycle(self) -> None:
        control = self.build_user_interface_control_under_test()
        control.open_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST
        )
        control.run_command_line_in_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, ["fake-harness", "--resume", "branch-one"]
        )
        control.send_interrupt_to_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, interrupt_repeat_count=2
        )
        control.display_status_line_in_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, "updating base session..."
        )
        control.run_command_line_in_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, ["fake-harness", "--resume", "branch-two"]
        )
        assert control.is_shared_window_alive(WINDOW_IDENTIFIER_UNDER_TEST) is True

    def test_reading_recent_output_returns_text(self) -> None:
        control = self.build_user_interface_control_under_test()
        control.open_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST
        )
        recent_output = control.read_recent_output_from_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, maximum_line_count=3
        )
        assert isinstance(recent_output, str)


class TestFakeUserInterfaceControlSatisfiesContract(
    UserInterfaceControlInterfaceContractTestSuite
):
    def build_user_interface_control_under_test(self) -> UserInterfaceControlInterface:
        return FakeUserInterfaceControlRecordingAllCalls(
            simulated_output_lines=["line one", "line two", "line three", "line four"]
        )


def test_fake_records_the_exact_session_swap_sequence() -> None:
    control = FakeUserInterfaceControlRecordingAllCalls()
    control.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)
    control.send_interrupt_to_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, interrupt_repeat_count=2
    )
    control.display_status_line_in_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, "updating base session..."
    )
    control.run_command_line_in_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, ["fake-harness", "--resume", "branch-two"]
    )
    assert control.event_log_by_window_identifier[WINDOW_IDENTIFIER_UNDER_TEST] == [
        ("open_shared_window", False),
        ("send_interrupt_to_shared_window", 2),
        ("display_status_line_in_shared_window", "updating base session..."),
        ("run_command_line_in_shared_window", ("fake-harness", "--resume", "branch-two")),
    ]


def test_fake_rejects_commands_sent_to_a_window_that_is_not_open() -> None:
    control = FakeUserInterfaceControlRecordingAllCalls()
    with pytest.raises(LookupError):
        control.run_command_line_in_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, ["fake-harness"]
        )


def test_fake_returns_only_the_requested_number_of_recent_lines() -> None:
    control = FakeUserInterfaceControlRecordingAllCalls(
        simulated_output_lines=["one", "two", "three", "four"]
    )
    control.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)
    assert (
        control.read_recent_output_from_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, maximum_line_count=2
        )
        == "three\nfour"
    )
