"""tmux command runner that records invocations and simulates session state.

Models just enough of tmux for the adapter's logic to be exercised: which
sessions exist, and what each command was. Output capture is simulated by
whatever the test writes to the pipe log path itself, so the adapter's log
handling is tested against a real file rather than a stub.
"""
from __future__ import annotations

from typing import Optional

from context_handoff.adapters.tmux.tmux_command_runner import (
    TmuxCommandOutcome,
    TmuxCommandRunnerInterface,
)


class FakeTmuxCommandRunner(TmuxCommandRunnerInterface):
    def __init__(
        self,
        initially_existing_session_names: Optional[list[str]] = None,
        capture_pane_output_text: str = "",
    ) -> None:
        self.existing_session_names: set[str] = set(initially_existing_session_names or [])
        self.recorded_tmux_argvs: list[list[str]] = []
        self._capture_pane_output_text = capture_pane_output_text

    def _extract_target_session_name(self, tmux_argv: list[str]) -> Optional[str]:
        for flag_name in ("-t", "-s"):
            if flag_name in tmux_argv:
                return tmux_argv[tmux_argv.index(flag_name) + 1]
        return None

    def run_tmux_command(self, tmux_argv: list[str]) -> TmuxCommandOutcome:
        self.recorded_tmux_argvs.append(list(tmux_argv))
        subcommand_name = tmux_argv[0] if tmux_argv else ""
        target_session_name = self._extract_target_session_name(tmux_argv)

        if subcommand_name == "has-session":
            exists = target_session_name in self.existing_session_names
            return TmuxCommandOutcome(
                exit_code=0 if exists else 1,
                stdout_text="",
                stderr_text="" if exists else "can't find session",
            )
        if subcommand_name == "new-session":
            if target_session_name in self.existing_session_names:
                return TmuxCommandOutcome(1, "", "duplicate session")
            if target_session_name is not None:
                self.existing_session_names.add(target_session_name)
            return TmuxCommandOutcome(0, "", "")
        if subcommand_name == "kill-session":
            if target_session_name not in self.existing_session_names:
                return TmuxCommandOutcome(1, "", "can't find session")
            self.existing_session_names.discard(target_session_name)
            return TmuxCommandOutcome(0, "", "")
        if subcommand_name == "capture-pane":
            return TmuxCommandOutcome(0, self._capture_pane_output_text, "")
        return TmuxCommandOutcome(0, "", "")

    def find_recorded_argvs_for_subcommand(self, subcommand_name: str) -> list[list[str]]:
        return [
            recorded_argv
            for recorded_argv in self.recorded_tmux_argvs
            if recorded_argv and recorded_argv[0] == subcommand_name
        ]
