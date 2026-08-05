"""Tests that a typed line is submitted as its own keystroke.

Driving the real system by hand exposed this: sending the text and the Enter in
one send-keys call left the text sitting unsubmitted in the interactive
agent's input box. The adapter had exactly that bug; the manual session only
worked because the driver noticed and pressed Enter again.

The settle delay is injected so the ordering can be asserted without waiting.
"""
from __future__ import annotations

import pytest

from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
    SharedWindowNeverBecameReadyError,
    TmuxUserInterfaceControlAdapter,
)
from tests.fakes.fake_tmux_command_runner import FakeTmuxCommandRunner

WINDOW_IDENTIFIER = "shared-window"
WORKING_DIRECTORY = "/fake/project"


def build_adapter(tmp_path, busy_pane_command_names_before_going_idle=None):
    recorded_settle_delays: list[float] = []
    fake_runner = FakeTmuxCommandRunner()
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=lambda _identifier: None,
        wait_for_input_to_settle=recorded_settle_delays.append,
    )
    adapter.open_shared_window(WINDOW_IDENTIFIER, WORKING_DIRECTORY)
    # After opening, never before: the pane is in its shell when the window is
    # created, which is what the adapter learns from.
    if busy_pane_command_names_before_going_idle:
        fake_runner.begin_reporting_busy_pane_commands(
            busy_pane_command_names_before_going_idle
        )
    return adapter, fake_runner, recorded_settle_delays


def index_of_first_send_keys_in_call_order(fake_runner) -> int:
    for call_index, recorded_argv in enumerate(fake_runner.recorded_tmux_argvs):
        if recorded_argv and recorded_argv[0] == "send-keys":
            return call_index
    raise AssertionError("no send-keys was issued at all")


def test_nothing_is_typed_until_the_pane_is_back_in_its_shell(tmp_path) -> None:
    """The defect that lost an entire launch, pinned.

    Driving the real system: the loop interrupted the running session and typed
    the next launch immediately. Sending an interrupt only hands the keys to
    tmux — it says nothing about the session having finished exiting — so the
    1180-character command was echoed at a terminal no shell was reading, and
    vanished. The pane fell to a bare prompt and no fork was ever created.
    """
    adapter, fake_runner, _ = build_adapter(
        tmp_path, busy_pane_command_names_before_going_idle=["claude", "claude", "node"]
    )

    adapter.run_command_line_in_shared_window(
        WINDOW_IDENTIFIER, ["claude", "--resume", "x"]
    )

    pane_queries_before_typing = 0
    for recorded_argv in fake_runner.recorded_tmux_argvs:
        if recorded_argv and recorded_argv[0] == "send-keys":
            break
        if recorded_argv and recorded_argv[0] == "display-message":
            pane_queries_before_typing += 1
    # One query while the window was opened, then one per busy poll, then the
    # one that saw the shell — all of them ahead of the first keystroke.
    assert pane_queries_before_typing >= 4


def test_the_readiness_check_asks_what_the_pane_is_running(tmp_path) -> None:
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.run_command_line_in_shared_window(WINDOW_IDENTIFIER, ["claude"])

    pane_query_argvs = fake_runner.find_recorded_argvs_for_subcommand("display-message")
    assert pane_query_argvs, "the pane was never asked what it is running"
    assert "#{pane_current_command}" in pane_query_argvs[0]


def test_the_idle_command_is_learned_rather_than_assumed(tmp_path) -> None:
    """A hardcoded list of shell names would be a guess about the user's shell."""
    fake_runner = FakeTmuxCommandRunner(idle_pane_command_name="fish")
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=lambda _identifier: None,
        wait_for_input_to_settle=lambda _seconds: None,
    )
    adapter.open_shared_window(WINDOW_IDENTIFIER, WORKING_DIRECTORY)

    assert (
        adapter.wait_until_shared_window_is_ready_for_a_command(WINDOW_IDENTIFIER)
        is True
    )


def test_readiness_reports_false_rather_than_waiting_forever(tmp_path) -> None:
    """Timing out is reported; refusing to ever type again would be worse."""
    fake_runner = FakeTmuxCommandRunner()
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=lambda _identifier: None,
        wait_for_input_to_settle=lambda _seconds: None,
        shell_readiness_timeout_seconds=0.0,
    )
    adapter.open_shared_window(WINDOW_IDENTIFIER, WORKING_DIRECTORY)
    fake_runner.begin_reporting_busy_pane_commands(["claude"] * 5000)

    assert (
        adapter.wait_until_shared_window_is_ready_for_a_command(WINDOW_IDENTIFIER)
        is False
    )


def build_adapter_whose_pane_never_returns_to_its_shell(tmp_path):
    fake_runner = FakeTmuxCommandRunner()
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=lambda _identifier: None,
        wait_for_input_to_settle=lambda _seconds: None,
        shell_readiness_timeout_seconds=0.0,
    )
    adapter.open_shared_window(WINDOW_IDENTIFIER, WORKING_DIRECTORY)
    fake_runner.begin_reporting_busy_pane_commands(["claude"] * 5000)
    return adapter, fake_runner


def test_an_occupied_pane_is_never_typed_into(tmp_path) -> None:
    """The failure that lost a launch and polluted the user's own session.

    Text sent to a pane running an interactive agent does not bounce — it is fed
    to that agent as though the user had typed it. A full session launch went
    into a working agent's prompt box and the agent answered it, so the launch
    was lost and nothing was reported.
    """
    adapter, fake_runner = build_adapter_whose_pane_never_returns_to_its_shell(tmp_path)

    with pytest.raises(SharedWindowNeverBecameReadyError):
        adapter.run_command_line_in_shared_window(
            WINDOW_IDENTIFIER, ["claude", "--resume", "x"]
        )

    assert send_keys_calls(fake_runner) == [], (
        "an occupied pane was typed into anyway"
    )


def test_a_status_line_is_also_withheld_from_an_occupied_pane(tmp_path) -> None:
    adapter, fake_runner = build_adapter_whose_pane_never_returns_to_its_shell(tmp_path)

    with pytest.raises(SharedWindowNeverBecameReadyError):
        adapter.display_status_line_in_shared_window(WINDOW_IDENTIFIER, "updating…")

    assert send_keys_calls(fake_runner) == []


def test_the_refusal_names_what_the_pane_is_still_running(tmp_path) -> None:
    """A silent refusal reads exactly like a rotation that worked."""
    adapter, _ = build_adapter_whose_pane_never_returns_to_its_shell(tmp_path)

    with pytest.raises(SharedWindowNeverBecameReadyError) as raised:
        adapter.run_command_line_in_shared_window(WINDOW_IDENTIFIER, ["claude"])

    assert "claude" in str(raised.value)
    assert WINDOW_IDENTIFIER in str(raised.value)


def test_a_status_line_also_waits_for_the_shell(tmp_path) -> None:
    """The status line is typed straight after an interrupt too."""
    adapter, fake_runner, _ = build_adapter(
        tmp_path, busy_pane_command_names_before_going_idle=["claude"]
    )

    adapter.display_status_line_in_shared_window(WINDOW_IDENTIFIER, "updating base…")

    first_send_keys_index = index_of_first_send_keys_in_call_order(fake_runner)
    pane_query_indexes = [
        call_index
        for call_index, recorded_argv in enumerate(fake_runner.recorded_tmux_argvs)
        if recorded_argv and recorded_argv[0] == "display-message"
    ]
    assert any(
        query_index < first_send_keys_index for query_index in pane_query_indexes
    )
    assert len(pane_query_indexes) >= 2


def test_a_reopened_window_relearns_its_shell(tmp_path) -> None:
    """A closed and reopened window is a new pane; the old name would be a guess."""
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.close_shared_window(WINDOW_IDENTIFIER)
    query_count_after_close = fake_runner.pane_current_command_query_count
    adapter.open_shared_window(WINDOW_IDENTIFIER, WORKING_DIRECTORY)

    assert fake_runner.pane_current_command_query_count > query_count_after_close


def send_keys_calls(fake_runner) -> list[list[str]]:
    return fake_runner.find_recorded_argvs_for_subcommand("send-keys")


def test_the_text_and_the_enter_are_separate_send_keys_calls(tmp_path) -> None:
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.run_command_line_in_shared_window(WINDOW_IDENTIFIER, ["claude", "--resume", "x"])

    calls = send_keys_calls(fake_runner)
    assert len(calls) == 2
    assert "Enter" not in calls[0]
    assert calls[1][-1] == "Enter"


def test_the_typed_text_carries_the_quoted_command_line(tmp_path) -> None:
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.run_command_line_in_shared_window(
        WINDOW_IDENTIFIER, ["claude", "--name", "branch with spaces"]
    )

    typed_call = send_keys_calls(fake_runner)[0]
    assert "'branch with spaces'" in typed_call[typed_call.index("-t") + 2]


def test_the_enter_call_carries_no_text(tmp_path) -> None:
    """A stray repeat of the text would submit the line twice."""
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.run_command_line_in_shared_window(WINDOW_IDENTIFIER, ["claude"])

    enter_call = send_keys_calls(fake_runner)[1]
    assert enter_call == ["send-keys", "-t", WINDOW_IDENTIFIER, "Enter"]


def test_the_adapter_waits_between_typing_and_submitting(tmp_path) -> None:
    """The interactive agent needs the text registered before Enter arrives."""
    adapter, _, recorded_settle_delays = build_adapter(tmp_path)

    adapter.run_command_line_in_shared_window(WINDOW_IDENTIFIER, ["claude"])

    assert len(recorded_settle_delays) == 1
    assert recorded_settle_delays[0] > 0


def test_a_status_line_is_also_typed_then_submitted(tmp_path) -> None:
    adapter, fake_runner, recorded_settle_delays = build_adapter(tmp_path)

    adapter.display_status_line_in_shared_window(WINDOW_IDENTIFIER, "updating base…")

    calls = send_keys_calls(fake_runner)
    assert len(calls) == 2
    assert calls[1][-1] == "Enter"
    assert len(recorded_settle_delays) == 1


def test_repeated_interrupts_arrive_as_one_rapid_burst(tmp_path) -> None:
    """Spacing decides whether the session cancels at all.

    Verified against a real session: two interrupts sent back to back cancel it,
    while interrupts two seconds apart clear the input box and leave the session
    running — four in a row failed to end it. Sending them as separate commands
    leaves that spacing at the mercy of process-launch latency, so they go in a
    single call.
    """
    adapter, fake_runner, recorded_settle_delays = build_adapter(tmp_path)

    adapter.send_interrupt_to_shared_window(WINDOW_IDENTIFIER, interrupt_repeat_count=2)

    calls = send_keys_calls(fake_runner)
    assert len(calls) == 1
    assert calls[0] == ["send-keys", "-t", WINDOW_IDENTIFIER, "C-c", "C-c"]
    assert recorded_settle_delays == []


def test_a_single_interrupt_sends_one_key(tmp_path) -> None:
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.send_interrupt_to_shared_window(WINDOW_IDENTIFIER, interrupt_repeat_count=1)

    assert send_keys_calls(fake_runner) == [
        ["send-keys", "-t", WINDOW_IDENTIFIER, "C-c"]
    ]


def test_an_interrupt_never_carries_an_enter(tmp_path) -> None:
    """An interrupt is a key, not a line; an Enter would submit what remains."""
    adapter, fake_runner, _ = build_adapter(tmp_path)

    adapter.send_interrupt_to_shared_window(WINDOW_IDENTIFIER, interrupt_repeat_count=2)

    assert all("Enter" not in call for call in send_keys_calls(fake_runner))
