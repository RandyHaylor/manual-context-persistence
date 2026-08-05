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

# How long to wait for the pane to hand itself back to its shell before typing.
# Generous, because what it waits on is an interactive agent shutting down, and
# how long that takes depends on what the agent was in the middle of.
DEFAULT_SHELL_READINESS_TIMEOUT_SECONDS = 30.0
DEFAULT_SHELL_READINESS_POLL_INTERVAL_SECONDS = 0.25

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


class SharedWindowNeverBecameReadyError(RuntimeError):
    """The pane never handed itself back to its shell, so nothing was typed.

    Raised rather than typing anyway. Text delivered to a pane that is still
    running something does not bounce — it is fed to that program as if the user
    had typed it. A whole session launch went into a working agent's prompt box
    that way, and the agent answered it: the launch was lost and the session the
    user was working in was polluted, with nothing reported.

    Raised rather than returning quietly, too. The turn loop already catches a
    failed rotation, reports it, and keeps running, so an exception is both
    visible and survivable — whereas a silent refusal looks identical to a
    rotation that worked.
    """


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
        shell_readiness_timeout_seconds: float = (
            DEFAULT_SHELL_READINESS_TIMEOUT_SECONDS
        ),
        shell_readiness_poll_interval_seconds: float = (
            DEFAULT_SHELL_READINESS_POLL_INTERVAL_SECONDS
        ),
    ) -> None:
        self._tmux_command_runner = tmux_command_runner or SubprocessTmuxCommandRunner()
        self._pane_output_log_directory = pane_output_log_directory
        self._attach_terminal_emulator = (
            attach_terminal_emulator or attach_first_available_terminal_emulator
        )
        self._wait_for_input_to_settle = wait_for_input_to_settle or time.sleep
        self._input_settle_delay_seconds = input_settle_delay_seconds
        self._shell_readiness_timeout_seconds = shell_readiness_timeout_seconds
        self._shell_readiness_poll_interval_seconds = (
            shell_readiness_poll_interval_seconds
        )
        self._window_identifiers_already_attached: set[str] = set()
        # The command a pane runs when it is idle — its shell. Learned by asking
        # the window at the moment it is opened, rather than compared against a
        # hardcoded list of shell names, because the user's shell is theirs to
        # choose and a list would be a guess that fails silently.
        self._idle_pane_command_by_window_identifier: dict[str, str] = {}

    def build_pane_output_log_path(self, window_identifier: str) -> str:
        return os.path.join(
            self._pane_output_log_directory, f"{window_identifier}-pane-output.log"
        )

    def _require_open_window(self, window_identifier: str) -> None:
        if not self.is_shared_window_alive(window_identifier):
            raise LookupError(f"shared window {window_identifier!r} is not open")

    def _read_pane_current_command(self, window_identifier: str) -> str:
        """Return the name of the program currently running in the pane."""
        return self._tmux_command_runner.run_tmux_command(
            [
                "display-message",
                "-p",
                "-t",
                window_identifier,
                "-F",
                "#{pane_current_command}",
            ]
        ).stdout_text.strip()

    def wait_until_shared_window_is_ready_for_a_command(
        self, window_identifier: str
    ) -> bool:
        """Wait for the pane to hand itself back to its shell.

        Found by driving the real system: interrupting a session and then typing
        the next command lost the command entirely. Sending an interrupt only
        tells tmux to deliver the keys — it says nothing about the session having
        finished exiting, and anything typed while it tears down is echoed to a
        terminal that no shell is reading. The whole 1180-character launch
        vanished and the pane fell to a bare prompt.

        Readiness is therefore observed rather than waited out with a guessed
        delay, since teardown time depends on what the session was doing.

        Reports rather than raises, so a caller can ask without committing to an
        outcome. The one caller that types does raise on False — see
        _type_shell_line_into_window for why proceeding is not an option.

        In practice this returns almost immediately: a rotation only interrupts a
        session that has already finished its turn, so the pane is a shell within
        moments. A timeout here means something genuinely unexpected, which is
        why it is worth failing loudly over.
        """
        idle_pane_command = self._idle_pane_command_by_window_identifier.get(
            window_identifier
        )
        if idle_pane_command is None:
            # Never learned, so there is nothing to compare against and nothing
            # to wait for. Only reachable for a window this adapter did not open.
            return True
        deadline = time.monotonic() + self._shell_readiness_timeout_seconds
        while True:
            if self._read_pane_current_command(window_identifier) == idle_pane_command:
                return True
            if time.monotonic() >= deadline:
                return False
            self._wait_for_input_to_settle(
                self._shell_readiness_poll_interval_seconds
            )

    def _type_shell_line_into_window(
        self, window_identifier: str, shell_line: str
    ) -> None:
        """Wait for a shell to be listening, then type a line and submit it.

        The wait lives here rather than in each caller because every caller has
        the same problem and only one of them would remember to solve it.

        Typing and submitting are deliberately separate calls. An interactive
        agent running in the pane reads its input through a full-screen editor
        rather than a shell line discipline, and a send-keys that carries the
        text and the Enter together arrives faster than the editor registers
        the text — leaving the line sitting unsubmitted in the input box. A
        real driven session is what exposed this; a shell alone never would.
        """
        if not self.wait_until_shared_window_is_ready_for_a_command(window_identifier):
            raise SharedWindowNeverBecameReadyError(
                f"shared window {window_identifier!r} is still running "
                f"{self._read_pane_current_command(window_identifier)!r} after "
                f"{self._shell_readiness_timeout_seconds}s; nothing was typed"
            )
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

        # Learned here, before anything has been run, which is the only moment
        # the pane is guaranteed to be sitting in its shell and nothing else.
        if window_identifier not in self._idle_pane_command_by_window_identifier:
            self._idle_pane_command_by_window_identifier[window_identifier] = (
                self._read_pane_current_command(window_identifier)
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
        # burst. Spacing decides whether they land as a pair at all: measured
        # against a real session, two interrupts back to back are treated as a
        # pair, while interrupts two seconds apart merely clear the input box —
        # four spaced out failed to end the session. Separate commands would
        # leave that spacing to process-launch latency.
        #
        # What a pair actually achieves depends on what the session is doing,
        # and an earlier version of this comment claimed more than was true.
        # Measured, on CLI 2.1.220:
        #   idle at its prompt  -> the pair exits the session
        #   mid-turn            -> the pair cancels the turn and the session
        #                          stays alive; a second pair then exits it
        #
        # This is only ever called on an idle session, so one pair is enough.
        # See rotate_to_next_branch_session for why that is guaranteed. Do not
        # conclude from the mid-turn measurement that this needs to escalate or
        # retry — that conclusion cost a day once already.
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
        # Forgotten along with the window: a window opened again later is a new
        # pane, and a remembered shell name from the old one would be a guess.
        self._idle_pane_command_by_window_identifier.pop(window_identifier, None)
        # kill-session on an absent session exits non-zero; that is the
        # idempotent outcome the interface requires, so it is not an error.
        self._tmux_command_runner.run_tmux_command(
            ["kill-session", "-t", window_identifier]
        )
