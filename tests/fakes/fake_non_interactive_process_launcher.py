"""Process launcher that yields scripted lines and records every invocation.

Lets the Claude CLI adapter be tested end to end — argv construction, parsing,
timeout handling — with no Claude process and no subprocess of any kind.
"""
from __future__ import annotations

from typing import Iterator, Optional

from context_handoff.adapters.claude_cli.non_interactive_process_launcher import (
    NonInteractiveProcessLauncherInterface,
    NonInteractiveProcessTimedOutError,
)


class RecordedProcessLaunch:
    def __init__(self, command_argv: list[str], stdin_text: str, timeout_seconds: float):
        self.command_argv = list(command_argv)
        self.stdin_text = stdin_text
        self.timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"RecordedProcessLaunch(argv={self.command_argv!r})"


class FakeNonInteractiveProcessLauncher(NonInteractiveProcessLauncherInterface):
    def __init__(
        self,
        stdout_lines_to_yield: Optional[list[str]] = None,
        stdout_lines_by_launch_index: Optional[list[list[str]]] = None,
        should_time_out_after_yielding: bool = False,
        on_launch_side_effect=None,
    ) -> None:
        """``stdout_lines_by_launch_index`` scripts successive launches
        differently, which the branch-creation path needs because it launches
        once and then inspects the filesystem. ``on_launch_side_effect`` is
        called with the recorded launch before any line is yielded, so a test
        can simulate the transcript file appearing.
        """
        self._stdout_lines_to_yield = list(stdout_lines_to_yield or [])
        self._stdout_lines_by_launch_index = stdout_lines_by_launch_index
        self._should_time_out_after_yielding = should_time_out_after_yielding
        self._on_launch_side_effect = on_launch_side_effect
        self.recorded_launches: list[RecordedProcessLaunch] = []

    def stream_stdout_lines_until_exit(
        self,
        command_argv: list[str],
        stdin_text: str,
        timeout_seconds: float,
    ) -> Iterator[str]:
        recorded_launch = RecordedProcessLaunch(command_argv, stdin_text, timeout_seconds)
        launch_index = len(self.recorded_launches)
        self.recorded_launches.append(recorded_launch)

        if self._on_launch_side_effect is not None:
            self._on_launch_side_effect(recorded_launch)

        if self._stdout_lines_by_launch_index is not None:
            lines_for_this_launch = (
                self._stdout_lines_by_launch_index[launch_index]
                if launch_index < len(self._stdout_lines_by_launch_index)
                else []
            )
        else:
            lines_for_this_launch = self._stdout_lines_to_yield

        for line in lines_for_this_launch:
            yield line

        if self._should_time_out_after_yielding:
            raise NonInteractiveProcessTimedOutError(
                f"fake launcher timed out after {timeout_seconds}s"
            )
