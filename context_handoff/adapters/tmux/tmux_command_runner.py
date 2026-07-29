"""Command-execution seam for the tmux adapter.

Separated for the same reason as the harness's process launcher: it is the only
part that cannot run in a unit test. Every tmux command this project issues is
short-lived and produces small output, so unlike the harness launcher this runs
to completion and returns the whole result rather than streaming.
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

DEFAULT_TMUX_COMMAND_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class TmuxCommandOutcome:
    """Result of one tmux invocation.

    A non-zero exit code is data, not an exception: ``has-session`` uses a
    non-zero exit to mean "no such session", which is an ordinary answer.
    """

    exit_code: int
    stdout_text: str
    stderr_text: str

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class TmuxCommandRunnerInterface(ABC):
    @abstractmethod
    def run_tmux_command(self, tmux_argv: list[str]) -> TmuxCommandOutcome:
        """Run one tmux command to completion and return its outcome."""


class SubprocessTmuxCommandRunner(TmuxCommandRunnerInterface):
    def __init__(
        self,
        tmux_executable_name: str = "tmux",
        command_timeout_seconds: float = DEFAULT_TMUX_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self._tmux_executable_name = tmux_executable_name
        self._command_timeout_seconds = command_timeout_seconds

    def run_tmux_command(self, tmux_argv: list[str]) -> TmuxCommandOutcome:
        completed_process = subprocess.run(
            [self._tmux_executable_name] + tmux_argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self._command_timeout_seconds,
        )
        return TmuxCommandOutcome(
            exit_code=completed_process.returncode,
            stdout_text=completed_process.stdout,
            stderr_text=completed_process.stderr,
        )
