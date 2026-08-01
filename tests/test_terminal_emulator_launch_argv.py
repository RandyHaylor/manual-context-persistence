"""Tests for the argv that opens a terminal emulator attached to the window.

Emulators disagree about how a command is passed, and getting it wrong shows up
only as a window that flashes and dies — the orchestrator carries on happily
driving a session nobody can see. That makes this worth pinning down even
though it is only argv construction.
"""
from __future__ import annotations

import pytest

from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
    CANDIDATE_TERMINAL_EMULATOR_NAMES,
    build_terminal_emulator_launch_argv,
)

WINDOW_NAME = "context-handoff-window"


@pytest.mark.parametrize("terminal_emulator_name", CANDIDATE_TERMINAL_EMULATOR_NAMES)
def test_every_candidate_builds_an_argv_that_attaches_the_session(
    terminal_emulator_name: str,
) -> None:
    argv = build_terminal_emulator_launch_argv(terminal_emulator_name, WINDOW_NAME)
    assert argv[0] == terminal_emulator_name
    assert argv[-3:] == ["attach", "-t", WINDOW_NAME]
    assert "tmux" in argv


def test_gnome_terminal_uses_the_double_dash_form() -> None:
    """gnome-terminal deprecated -e; passing it there silently fails to launch."""
    argv = build_terminal_emulator_launch_argv("gnome-terminal", WINDOW_NAME)
    assert argv[1] == "--"
    assert "-e" not in argv


def test_kitty_takes_the_command_with_no_separator() -> None:
    argv = build_terminal_emulator_launch_argv("kitty", WINDOW_NAME)
    assert argv[1] == "tmux"


@pytest.mark.parametrize(
    "terminal_emulator_name", ["konsole", "xfce4-terminal", "lxterminal", "alacritty", "xterm"]
)
def test_the_remaining_emulators_use_the_dash_e_form(terminal_emulator_name: str) -> None:
    argv = build_terminal_emulator_launch_argv(terminal_emulator_name, WINDOW_NAME)
    assert argv[1] == "-e"


def test_an_unknown_emulator_falls_back_to_the_common_form() -> None:
    """Better a documented guess than a crash on an emulator we have not met."""
    argv = build_terminal_emulator_launch_argv("some-new-terminal", WINDOW_NAME)
    assert argv[0] == "some-new-terminal"
    assert argv[1] == "-e"


def test_the_window_name_is_passed_through_unaltered() -> None:
    argv = build_terminal_emulator_launch_argv("xterm", "name with spaces")
    assert argv[-1] == "name with spaces"
