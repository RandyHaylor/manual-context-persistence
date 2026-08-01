"""Tests for the tmux user-interface control adapter, driven by a fake runner.

Like the harness adapter, this must satisfy the shared contract suite and must
build the right commands — a wrong tmux flag is invisible to a fake unless the
argv is asserted directly.
"""
from __future__ import annotations

import os

import pytest

from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
    TmuxUserInterfaceControlAdapter,
)
from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)
from tests.fakes.fake_tmux_command_runner import FakeTmuxCommandRunner
from tests.test_user_interface_control_interface_contract import (
    WINDOW_IDENTIFIER_UNDER_TEST,
    WORKING_DIRECTORY_UNDER_TEST,
    UserInterfaceControlInterfaceContractTestSuite,
)


def build_adapter_with_fake_runner(
    tmp_path,
    initially_existing_session_names=None,
    capture_pane_output_text: str = "",
) -> tuple[TmuxUserInterfaceControlAdapter, FakeTmuxCommandRunner]:
    fake_runner = FakeTmuxCommandRunner(
        initially_existing_session_names=initially_existing_session_names,
        capture_pane_output_text=capture_pane_output_text,
    )
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=lambda window_identifier: None,
    )
    return adapter, fake_runner


class TestTmuxAdapterSatisfiesUserInterfaceControlContract(
    UserInterfaceControlInterfaceContractTestSuite
):
    @pytest.fixture(autouse=True)
    def _bind_temporary_log_directory(self, tmp_path) -> None:
        self._tmp_path = tmp_path

    def build_user_interface_control_under_test(self) -> UserInterfaceControlInterface:
        adapter, _ = build_adapter_with_fake_runner(self._tmp_path)
        return adapter


def test_opening_creates_a_detached_session_in_the_working_directory(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)

    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    new_session_argvs = fake_runner.find_recorded_argvs_for_subcommand("new-session")
    assert len(new_session_argvs) == 1
    new_session_argv = new_session_argvs[0]
    assert "-s" in new_session_argv
    assert WINDOW_IDENTIFIER_UNDER_TEST in new_session_argv
    # Detached, because the visible window is attached separately by the
    # terminal emulator rather than by this process.
    assert "-d" in new_session_argv
    assert "-c" in new_session_argv
    assert WORKING_DIRECTORY_UNDER_TEST in new_session_argv


def test_opening_an_existing_session_does_not_create_a_second_one(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(
        tmp_path, initially_existing_session_names=[WINDOW_IDENTIFIER_UNDER_TEST]
    )

    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    assert fake_runner.find_recorded_argvs_for_subcommand("new-session") == []


def test_opening_pipes_pane_output_to_a_log_file(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)

    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    pipe_pane_argvs = fake_runner.find_recorded_argvs_for_subcommand("pipe-pane")
    assert len(pipe_pane_argvs) == 1
    assert adapter.build_pane_output_log_path(WINDOW_IDENTIFIER_UNDER_TEST) in " ".join(
        pipe_pane_argvs[0]
    )
    assert os.path.isdir(os.path.dirname(adapter.build_pane_output_log_path(
        WINDOW_IDENTIFIER_UNDER_TEST
    )))


def test_the_terminal_emulator_is_asked_to_attach_once(tmp_path) -> None:
    attach_call_window_identifiers: list[str] = []
    fake_runner = FakeTmuxCommandRunner()
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=attach_call_window_identifiers.append,
    )

    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    assert attach_call_window_identifiers == [WINDOW_IDENTIFIER_UNDER_TEST]


def test_command_lines_are_shell_quoted_before_being_typed(tmp_path) -> None:
    """send-keys types a shell line, so an unquoted argument would be reparsed."""
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    adapter.run_command_line_in_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST,
        ["claude", "--resume", "abc", "--name", "branch with spaces"],
    )

    # Typing and submitting are separate calls, so the text is in the one
    # before the Enter.
    send_keys_argvs = fake_runner.find_recorded_argvs_for_subcommand("send-keys")
    typed_shell_line = send_keys_argvs[-2][send_keys_argvs[-2].index("-t") + 2]
    assert "'branch with spaces'" in typed_shell_line
    assert send_keys_argvs[-1][-1] == "Enter"


def test_interrupt_is_sent_the_requested_number_of_times(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    adapter.send_interrupt_to_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, interrupt_repeat_count=2
    )

    interrupt_argvs = [
        recorded_argv
        for recorded_argv in fake_runner.find_recorded_argvs_for_subcommand("send-keys")
        if "C-c" in recorded_argv
    ]
    # One command carrying both, so they land as a rapid burst; spacing is what
    # decides whether the session actually cancels.
    assert len(interrupt_argvs) == 1
    assert interrupt_argvs[0].count("C-c") == 2
    # An interrupt must not be followed by Enter, which would submit a line.
    assert "Enter" not in interrupt_argvs[0]


def test_status_line_is_echoed_into_the_window(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    adapter.display_status_line_in_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, "updating base session..."
    )

    send_keys_argvs = fake_runner.find_recorded_argvs_for_subcommand("send-keys")
    typed_shell_line = send_keys_argvs[-2][send_keys_argvs[-2].index("-t") + 2]
    assert typed_shell_line.startswith("echo ")
    assert "updating base session..." in typed_shell_line


def test_recent_output_is_read_from_the_pipe_log(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)
    log_path = adapter.build_pane_output_log_path(WINDOW_IDENTIFIER_UNDER_TEST)
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("one\ntwo\nthree\nfour\n")

    recent_output = adapter.read_recent_output_from_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, maximum_line_count=2
    )

    assert recent_output == "three\nfour"
    # The complete log is preferred over the visible pane, which is lossy.
    assert fake_runner.find_recorded_argvs_for_subcommand("capture-pane") == []


def test_recent_output_falls_back_to_the_visible_pane_when_no_log_exists(
    tmp_path,
) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(
        tmp_path, capture_pane_output_text="visible line\n"
    )
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)
    os.remove(adapter.build_pane_output_log_path(WINDOW_IDENTIFIER_UNDER_TEST))

    recent_output = adapter.read_recent_output_from_shared_window(
        WINDOW_IDENTIFIER_UNDER_TEST, maximum_line_count=5
    )

    assert "visible line" in recent_output
    assert fake_runner.find_recorded_argvs_for_subcommand("capture-pane")


def test_closing_kills_the_session(tmp_path) -> None:
    adapter, fake_runner = build_adapter_with_fake_runner(tmp_path)
    adapter.open_shared_window(WINDOW_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST)

    adapter.close_shared_window(WINDOW_IDENTIFIER_UNDER_TEST)

    assert fake_runner.find_recorded_argvs_for_subcommand("kill-session")
    assert adapter.is_shared_window_alive(WINDOW_IDENTIFIER_UNDER_TEST) is False


def test_sending_to_a_window_that_is_not_open_raises_lookup_error(tmp_path) -> None:
    adapter, _ = build_adapter_with_fake_runner(tmp_path)
    with pytest.raises(LookupError):
        adapter.run_command_line_in_shared_window(
            WINDOW_IDENTIFIER_UNDER_TEST, ["claude", "--resume", "abc"]
        )
