"""In-memory UserInterfaceControlInterface that records every call.

Models the one property the turn loop actually depends on: the window survives
across session swaps. Each window keeps an ordered event log so a test can
assert the exact sequence — interrupt, status line, next command line — without
a terminal emulator.
"""
from __future__ import annotations

from typing import Optional


from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)


class FakeUserInterfaceControlRecordingAllCalls(UserInterfaceControlInterface):
    def __init__(self, simulated_output_lines: Optional[list[str]] = None) -> None:
        self.open_window_identifiers: set[str] = set()
        self.working_directory_by_window_identifier: dict[str, str] = {}
        self.event_log_by_window_identifier: dict[str, list[tuple]] = {}
        self.closed_window_identifiers: list[str] = []
        self._simulated_output_lines = list(simulated_output_lines or [])

    def _append_event(self, window_identifier: str, event: tuple) -> None:
        self.event_log_by_window_identifier.setdefault(window_identifier, []).append(event)

    def _require_open_window(self, window_identifier: str) -> None:
        if window_identifier not in self.open_window_identifiers:
            raise LookupError(f"fake window {window_identifier!r} is not open")

    def open_shared_window(self, window_identifier: str, working_directory: str) -> None:
        already_open = window_identifier in self.open_window_identifiers
        self.open_window_identifiers.add(window_identifier)
        self.working_directory_by_window_identifier[window_identifier] = working_directory
        self._append_event(window_identifier, ("open_shared_window", already_open))

    def is_shared_window_alive(self, window_identifier: str) -> bool:
        return window_identifier in self.open_window_identifiers

    def run_command_line_in_shared_window(
        self, window_identifier: str, command_line_argv: list[str]
    ) -> None:
        self._require_open_window(window_identifier)
        self._append_event(
            window_identifier,
            ("run_command_line_in_shared_window", tuple(command_line_argv)),
        )

    def send_interrupt_to_shared_window(
        self, window_identifier: str, interrupt_repeat_count: int = 1
    ) -> None:
        self._require_open_window(window_identifier)
        self._append_event(
            window_identifier,
            ("send_interrupt_to_shared_window", interrupt_repeat_count),
        )

    def send_confirmation_keypress_to_shared_window(
        self, window_identifier: str
    ) -> None:
        self._require_open_window(window_identifier)
        self._append_event(
            window_identifier, ("send_confirmation_keypress_to_shared_window", None)
        )

    def display_status_line_in_shared_window(
        self, window_identifier: str, status_text: str
    ) -> None:
        self._require_open_window(window_identifier)
        self._append_event(
            window_identifier, ("display_status_line_in_shared_window", status_text)
        )

    def read_recent_output_from_shared_window(
        self, window_identifier: str, maximum_line_count: int
    ) -> str:
        self._require_open_window(window_identifier)
        self._append_event(
            window_identifier,
            ("read_recent_output_from_shared_window", maximum_line_count),
        )
        return "\n".join(self._simulated_output_lines[-maximum_line_count:])

    def close_shared_window(self, window_identifier: str) -> None:
        self.open_window_identifiers.discard(window_identifier)
        self.closed_window_identifiers.append(window_identifier)
        self._append_event(window_identifier, ("close_shared_window", None))
