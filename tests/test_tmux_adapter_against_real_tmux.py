"""Integration tests for the tmux adapter against a real tmux server.

These use a real detached tmux session but never attach a terminal emulator, so
nothing appears on screen and the tests are safe to run unattended. They are
skipped when tmux is not installed.

This is the layer the fake cannot vouch for: whether the commands the adapter
builds are actually accepted by tmux.
"""
from __future__ import annotations

import os
import shutil
import time
import uuid

import pytest

from context_handoff.adapters.tmux.tmux_command_runner import SubprocessTmuxCommandRunner
from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
    TmuxUserInterfaceControlAdapter,
)

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux is not installed"
)


@pytest.fixture
def adapter_and_window_identifier(tmp_path):
    """Yield an adapter plus a unique window name, killing the session after."""
    window_identifier = f"context-handoff-test-{uuid.uuid4().hex[:8]}"
    adapter = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=SubprocessTmuxCommandRunner(),
        pane_output_log_directory=str(tmp_path / "pane-logs"),
        attach_terminal_emulator=lambda _window_identifier: None,
    )
    try:
        yield adapter, window_identifier
    finally:
        adapter.close_shared_window(window_identifier)


def wait_until_log_contains(
    adapter: TmuxUserInterfaceControlAdapter,
    window_identifier: str,
    expected_text: str,
    timeout_seconds: float = 10.0,
) -> str:
    """Poll the pane log until the text appears or the deadline passes.

    tmux writes the pane log asynchronously, so a bare read races the shell.
    """
    deadline_monotonic_seconds = time.monotonic() + timeout_seconds
    most_recent_output = ""
    while time.monotonic() < deadline_monotonic_seconds:
        most_recent_output = adapter.read_recent_output_from_shared_window(
            window_identifier, maximum_line_count=200
        )
        if expected_text in most_recent_output:
            return most_recent_output
        time.sleep(0.2)
    return most_recent_output


def test_real_tmux_session_opens_and_reports_alive(adapter_and_window_identifier) -> None:
    adapter, window_identifier = adapter_and_window_identifier
    assert adapter.is_shared_window_alive(window_identifier) is False

    adapter.open_shared_window(window_identifier, os.getcwd())

    assert adapter.is_shared_window_alive(window_identifier) is True


def test_real_tmux_open_is_idempotent(adapter_and_window_identifier) -> None:
    adapter, window_identifier = adapter_and_window_identifier
    adapter.open_shared_window(window_identifier, os.getcwd())
    adapter.open_shared_window(window_identifier, os.getcwd())
    assert adapter.is_shared_window_alive(window_identifier) is True


def test_real_tmux_runs_a_command_and_the_output_reaches_the_log(
    adapter_and_window_identifier,
) -> None:
    adapter, window_identifier = adapter_and_window_identifier
    adapter.open_shared_window(window_identifier, os.getcwd())

    adapter.run_command_line_in_shared_window(
        window_identifier, ["echo", "hello from the shared window"]
    )

    assert "hello from the shared window" in wait_until_log_contains(
        adapter, window_identifier, "hello from the shared window"
    )


def test_real_tmux_preserves_arguments_containing_spaces(
    adapter_and_window_identifier,
) -> None:
    """Proves the shell quoting survives a real shell, not just an assertion."""
    adapter, window_identifier = adapter_and_window_identifier
    adapter.open_shared_window(window_identifier, os.getcwd())

    adapter.run_command_line_in_shared_window(
        window_identifier, ["echo", "argument with spaces"]
    )

    assert "argument with spaces" in wait_until_log_contains(
        adapter, window_identifier, "argument with spaces"
    )


def test_real_tmux_status_line_is_visible_in_the_window(
    adapter_and_window_identifier,
) -> None:
    adapter, window_identifier = adapter_and_window_identifier
    adapter.open_shared_window(window_identifier, os.getcwd())

    adapter.display_status_line_in_shared_window(
        window_identifier, "updating base session..."
    )

    assert "updating base session..." in wait_until_log_contains(
        adapter, window_identifier, "updating base session..."
    )


def test_real_tmux_window_survives_interrupting_a_running_command(
    adapter_and_window_identifier,
) -> None:
    """The turn loop's core assumption: interrupt, then reuse the same window."""
    adapter, window_identifier = adapter_and_window_identifier
    adapter.open_shared_window(window_identifier, os.getcwd())
    adapter.run_command_line_in_shared_window(window_identifier, ["sleep", "120"])
    time.sleep(0.5)

    adapter.send_interrupt_to_shared_window(window_identifier, interrupt_repeat_count=2)

    assert adapter.is_shared_window_alive(window_identifier) is True
    adapter.run_command_line_in_shared_window(
        window_identifier, ["echo", "window still usable"]
    )
    assert "window still usable" in wait_until_log_contains(
        adapter, window_identifier, "window still usable"
    )


def test_real_tmux_close_is_idempotent(adapter_and_window_identifier) -> None:
    adapter, window_identifier = adapter_and_window_identifier
    adapter.open_shared_window(window_identifier, os.getcwd())

    adapter.close_shared_window(window_identifier)
    adapter.close_shared_window(window_identifier)

    assert adapter.is_shared_window_alive(window_identifier) is False
