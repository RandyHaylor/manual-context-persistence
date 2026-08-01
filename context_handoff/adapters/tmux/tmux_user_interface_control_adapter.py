"""UserInterfaceControlInterface implemented against tmux.

The shared window is a detached tmux session that the user attaches to through
a terminal emulator. Detached creation and visible attachment are deliberately
separate: the orchestrator must be able to drive the window whether or not the
user currently has it on screen, and the window must survive every session swap
the turn loop performs.

Pane output is piped to a log file rather than read from the visible pane,
because a pane capture only returns what currently fits on screen.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from typing import Callable, Optional

# Long enough for a full-screen interactive agent to register typed text before
# the submit keystroke lands, short enough not to be felt between turns.
DEFAULT_INPUT_SETTLE_DELAY_SECONDS = 1.0

from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)

from .tmux_command_runner import (
    SubprocessTmuxCommandRunner,
    TmuxCommandRunnerInterface,
)

DEFAULT_PANE_OUTPUT_LOG_DIRECTORY = os.path.expanduser(
    "~/.claude/context-handoff-pane-logs"
)

# Tried in order; the first one present on PATH is used to show the window.
CANDIDATE_TERMINAL_EMULATOR_NAMES = (
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "lxterminal",
    "alacritty",
    "kitty",
    "xterm",
)


class NoTerminalEmulatorAvailableError(RuntimeError):
    """No known terminal emulator was found, so the window cannot be shown.

    Raised rather than silently continuing: a shared window the user cannot see
    defeats the purpose of the shared window.
    """


def build_terminal_emulator_launch_argv(
    terminal_emulator_name: str, tmux_session_name: str
) -> list[str]:
    """Return the argv that opens ``terminal_emulator_name`` attached to a session.

    Most emulators take the command after a bare ``-e``; gnome-terminal
    deprecated ``-e`` in favour of ``--`` and kitty takes the command directly.
    """
    attach_argv = ["tmux", "attach", "-t", tmux_session_name]
    if terminal_emulator_name == "gnome-terminal":
        return [terminal_emulator_name, "--"] + attach_argv
    if terminal_emulator_name == "kitty":
        return [terminal_emulator_name] + attach_argv
    return [terminal_emulator_name, "-e"] + attach_argv


def attach_first_available_terminal_emulator(tmux_session_name: str) -> None:
    """Open the first terminal emulator found on PATH, detached from this process."""
    for candidate_terminal_emulator_name in CANDIDATE_TERMINAL_EMULATOR_NAMES:
        if shutil.which(candidate_terminal_emulator_name) is None:
            continue
        subprocess.Popen(
            build_terminal_emulator_launch_argv(
                candidate_terminal_emulator_name, tmux_session_name
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    raise NoTerminalEmulatorAvailableError(
        "none of these terminal emulators is on PATH: "
        + ", ".join(CANDIDATE_TERMINAL_EMULATOR_NAMES)
    )


class TmuxUserInterfaceControlAdapter(UserInterfaceControlInterface):
    def __init__(
        self,
        tmux_command_runner: Optional[TmuxCommandRunnerInterface] = None,
        pane_output_log_directory: str = DEFAULT_PANE_OUTPUT_LOG_DIRECTORY,
        attach_terminal_emulator: Optional[Callable[[str], None]] = None,
        wait_for_input_to_settle: Optional[Callable[[float], None]] = None,
        input_settle_delay_seconds: float = DEFAULT_INPUT_SETTLE_DELAY_SECONDS,
    ) -> None:
        self._tmux_command_runner = tmux_command_runner or SubprocessTmuxCommandRunner()
        self._pane_output_log_directory = pane_output_log_directory
        self._attach_terminal_emulator = (
            attach_terminal_emulator or attach_first_available_terminal_emulator
        )
        self._wait_for_input_to_settle = wait_for_input_to_settle or time.sleep
        self._input_settle_delay_seconds = input_settle_delay_seconds
        self._window_identifiers_already_attached: set[str] = set()

    def build_pane_output_log_path(self, window_identifier: str) -> str:
        return os.path.join(
            self._pane_output_log_directory, f"{window_identifier}-pane-output.log"
        )

    def _require_open_window(self, window_identifier: str) -> None:
        if not self.is_shared_window_alive(window_identifier):
            raise LookupError(f"shared window {window_identifier!r} is not open")

    def _type_shell_line_into_window(
        self, window_identifier: str, shell_line: str
    ) -> None:
        """Type a line, let it register, then submit it.

        Typing and submitting are deliberately separate calls. An interactive
        agent running in the pane reads its input through a full-screen editor
        rather than a shell line discipline, and a send-keys that carries the
        text and the Enter together arrives faster than the editor registers
        the text — leaving the line sitting unsubmitted in the input box. A
        real driven session is what exposed this; a shell alone never would.
        """
        self._tmux_command_runner.run_tmux_command(
            ["send-keys", "-t", window_identifier, shell_line]
        )
        self._wait_for_input_to_settle(self._input_settle_delay_seconds)
        self._tmux_command_runner.run_tmux_command(
            ["send-keys", "-t", window_identifier, "Enter"]
        )

    def open_shared_window(self, window_identifier: str, working_directory: str) -> None:
        if not self.is_shared_window_alive(window_identifier):
            self._tmux_command_runner.run_tmux_command(
                ["new-session", "-s", window_identifier, "-d", "-c", working_directory]
            )
            os.makedirs(self._pane_output_log_directory, exist_ok=True)
            pane_output_log_path = self.build_pane_output_log_path(window_identifier)
            # Touch the log so a reader that runs before any output exists
            # finds an empty file rather than falling back to a pane capture.
            with open(pane_output_log_path, "a", encoding="utf-8"):
                pass
            self._tmux_command_runner.run_tmux_command(
                [
                    "pipe-pane",
                    "-t",
                    window_identifier,
                    "-o",
                    f"cat >> {shlex.quote(pane_output_log_path)}",
                ]
            )

        if window_identifier not in self._window_identifiers_already_attached:
            self._attach_terminal_emulator(window_identifier)
            self._window_identifiers_already_attached.add(window_identifier)

    def is_shared_window_alive(self, window_identifier: str) -> bool:
        return self._tmux_command_runner.run_tmux_command(
            ["has-session", "-t", window_identifier]
        ).succeeded

    def run_command_line_in_shared_window(
        self, window_identifier: str, command_line_argv: list[str]
    ) -> None:
        self._require_open_window(window_identifier)
        # send-keys types a line into a shell, so the opaque argv must be
        # quoted back into a single safe shell line.
        self._type_shell_line_into_window(
            window_identifier, shlex.join(command_line_argv)
        )

    def send_interrupt_to_shared_window(
        self, window_identifier: str, interrupt_repeat_count: int = 1
    ) -> None:
        self._require_open_window(window_identifier)
        if interrupt_repeat_count < 1:
            return
        # One command carrying every interrupt, so they arrive as a rapid
        # burst. Spacing decides whether the session cancels at all: verified
        # against a real session, two interrupts back to back end it, while
        # interrupts two seconds apart merely clear the input box and leave it
        # running — four in a row failed to end it. Separate commands would
        # leave that spacing to process-launch latency.
        #
        # No Enter: an interrupt is a keypress, and a trailing Enter would
        # submit whatever line the interrupt left behind.
        self._tmux_command_runner.run_tmux_command(
            ["send-keys", "-t", window_identifier] + ["C-c"] * interrupt_repeat_count
        )

    def send_confirmation_keypress_to_shared_window(
        self, window_identifier: str
    ) -> None:
        self._require_open_window(window_identifier)
        # Enter alone, with nothing typed ahead of it: the prompt this answers
        # already has its accepting choice selected, so a keystroke naming that
        # choice would be a second guess about which option sits where.
        self._tmux_command_runner.run_tmux_command(
            ["send-keys", "-t", window_identifier, "Enter"]
        )

    def display_status_line_in_shared_window(
        self, window_identifier: str, status_text: str
    ) -> None:
        self._require_open_window(window_identifier)
        self._type_shell_line_into_window(
            window_identifier, f"echo {shlex.quote(status_text)}"
        )

    def read_recent_output_from_shared_window(
        self, window_identifier: str, maximum_line_count: int
    ) -> str:
        self._require_open_window(window_identifier)
        pane_output_log_path = self.build_pane_output_log_path(window_identifier)
        if os.path.exists(pane_output_log_path):
            with open(
                pane_output_log_path, "r", encoding="utf-8", errors="replace"
            ) as log_file:
                logged_lines = log_file.read().splitlines()
            return "\n".join(logged_lines[-maximum_line_count:])

        # Fallback only: a pane capture loses anything scrolled off screen.
        capture_outcome = self._tmux_command_runner.run_tmux_command(
            ["capture-pane", "-t", window_identifier, "-p"]
        )
        captured_lines = capture_outcome.stdout_text.splitlines()
        return "\n".join(captured_lines[-maximum_line_count:])

    def close_shared_window(self, window_identifier: str) -> None:
        self._window_identifiers_already_attached.discard(window_identifier)
        # kill-session on an absent session exits non-zero; that is the
        # idempotent outcome the interface requires, so it is not an error.
        self._tmux_command_runner.run_tmux_command(
            ["kill-session", "-t", window_identifier]
        )
