"""Tests that a typed line is submitted as its own keystroke.

Driving the real system by hand exposed this: sending the text and the Enter in
one send-keys call left the text sitting unsubmitted in the interactive
agent's input box. The adapter had exactly that bug; the manual session only
worked because the driver noticed and pressed Enter again.

The settle delay is injected so the ordering can be asserted without waiting.
"""
from __future__ import annotations

from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
    TmuxUserInterfaceControlAdapter,
)
from tests.fakes.fake_tmux_command_runner import FakeTmuxCommandRunner

WINDOW_IDENTIFIER = "shared-window"
WORKING_DIRECTORY = "/fake/project"


def build_adapter(tmp_path):
    recorded_settle_delays: list[float] = []
    fake_runner = FakeTmuxCommandRunner()
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=fake_runner,
        pane_output_log_directory=str(tmp_path / "logs"),
        attach_terminal_emulator=lambda _identifier: None,
        wait_for_input_to_settle=recorded_settle_delays.append,
    )
    adapter.open_shared_window(WINDOW_IDENTIFIER, WORKING_DIRECTORY)
    return adapter, fake_runner, recorded_settle_delays


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
