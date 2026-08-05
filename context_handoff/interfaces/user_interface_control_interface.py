"""Abstract interface for the window the user watches and types into.

tmux is the first concrete implementation; another launch or terminal-control
method may replace it without the core changing. No method name, argument, or
return value here may reference a tmux command, and no method may reference the
harness: command lines arrive as an opaque argv built by the harness layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class UserInterfaceControlInterface(ABC):
    """Control of one long-lived window shared by the user and the orchestrator.

    The window outlives individual sessions: the turn loop repeatedly
    interrupts whatever is running in it and starts the next branch session in
    the same window, so the user never loses their place.
    """

    @abstractmethod
    def open_shared_window(self, window_identifier: str, working_directory: str) -> None:
        """Create the shared window and make it visible to the user.

        Must be idempotent: opening an already-open window is not an error.
        """

    @abstractmethod
    def is_shared_window_alive(self, window_identifier: str) -> bool:
        """Return whether the shared window still exists and can accept input."""

    @abstractmethod
    def run_command_line_in_shared_window(
        self, window_identifier: str, command_line_argv: list[str]
    ) -> None:
        """Start an interactive program in the shared window.

        ``command_line_argv`` is opaque; implementations must quote it safely
        for their own transport rather than interpreting its contents.

        Implementations must not deliver the command until the window is
        actually able to receive one. A window that has just been interrupted
        may still be shutting the previous program down, and a command handed
        over during that gap is silently lost rather than refused — which cost a
        whole session launch before this was stated. Waiting must be on observed
        readiness, not a fixed delay: how long a teardown takes depends on what
        the program was doing.
        """

    @abstractmethod
    def send_interrupt_to_shared_window(
        self, window_identifier: str, interrupt_repeat_count: int = 1
    ) -> None:
        """Interrupt whatever is running in the shared window.

        ``interrupt_repeat_count`` exists because interactive agents commonly
        treat a single interrupt as "cancel the current turn" and only exit on
        a second one.
        """

    @abstractmethod
    def send_confirmation_keypress_to_shared_window(
        self, window_identifier: str
    ) -> None:
        """Accept whatever prompt the program in the window is waiting on.

        Exists for the safety prompt an interactive harness opens with the first
        time it runs somewhere: nothing can proceed until it is answered, and
        its default choice is the one that proceeds. Sent blind, because a
        program with no prompt open simply discards it.
        """

    @abstractmethod
    def display_status_line_in_shared_window(
        self, window_identifier: str, status_text: str
    ) -> None:
        """Show a short orchestrator status message to the watching user.

        Used to explain pauses (for example while the base session is being
        updated) so the window never looks frozen.
        """

    @abstractmethod
    def read_recent_output_from_shared_window(
        self, window_identifier: str, maximum_line_count: int
    ) -> str:
        """Return the most recent output from the shared window.

        Implementations should prefer a complete captured stream over whatever
        happens to be visible on screen, so scrolled-off output is not lost.
        """

    @abstractmethod
    def close_shared_window(self, window_identifier: str) -> None:
        """Destroy the shared window.

        Must be idempotent: closing an absent window is not an error.
        """
