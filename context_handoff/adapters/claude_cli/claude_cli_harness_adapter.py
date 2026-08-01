"""HarnessInterface implemented against the Claude CLI.

All Claude-specific knowledge in the project is meant to live here and in the
three modules this one composes: the transcript locator, the stream parser, and
the process launcher. The core turn loop never sees a flag name.

Authentication: this adapter assumes the CLI is installed and the user is
already logged in through the CLI's own local OAuth flow. It never prompts for
credentials and never writes credential state. Its availability probe therefore
reports ``is_authorized=None`` — distinguishing "installed" from "logged in"
would require a billable call, and guessing would be worse than admitting the
limit.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Callable, Optional

from context_handoff.interfaces.harness_interface import (
    HarnessAvailabilityReport,
    HarnessInterface,
    SessionAcknowledgment,
)

from .claude_cli_stream_json_event_parser import parse_stream_json_event_lines
from .claude_cli_transcript_locator import (
    DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
    build_transcript_file_path,
    find_active_session_identifier_for_working_directory,
    read_session_display_name_from_transcript,
)
from .non_interactive_process_launcher import (
    NonInteractiveProcessLauncherInterface,
    NonInteractiveProcessTimedOutError,
    SubprocessNonInteractiveProcessLauncher,
)

DEFAULT_CLAUDE_EXECUTABLE_NAME = "claude"
DEFAULT_AVAILABILITY_PROBE_TIMEOUT_SECONDS = 30.0
DEFAULT_BRANCH_SEED_TIMEOUT_SECONDS = 180.0
TRANSCRIPT_DURABILITY_POLL_INTERVAL_SECONDS = 0.5


# No SessionNotDurableError: nothing in this adapter creates a session any more,
# so nothing here can fail to create one. A session now comes into being in a
# window this process does not drive, which makes non-durability something to
# report (see wait_until_session_transcript_is_durable) rather than to raise.


class ClaudeCliHarnessAdapter(HarnessInterface):
    def __init__(
        self,
        process_launcher: Optional[NonInteractiveProcessLauncherInterface] = None,
        claude_projects_root_directory: str = DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
        claude_executable_name: str = DEFAULT_CLAUDE_EXECUTABLE_NAME,
        observe_stream_event: Optional[Callable[[str, str], None]] = None,
        generate_branch_session_identifier: Optional[Callable[[], str]] = None,
        project_working_directory: Optional[str] = None,
    ) -> None:
        """``project_working_directory`` is where resume-style invocations run.

        Branch creation takes its directory from the call, but resuming a
        session has no directory argument in the interface, and the CLI resolves
        a session against the directory it is launched from — so the adapter
        must be told once, at construction, which project it belongs to.
        """
        self._process_launcher = process_launcher or SubprocessNonInteractiveProcessLauncher(
            observe_stream_event=observe_stream_event
        )
        self._claude_projects_root_directory = claude_projects_root_directory
        self._claude_executable_name = claude_executable_name
        self._observe_stream_event = observe_stream_event
        self._generate_branch_session_identifier = (
            generate_branch_session_identifier or (lambda: str(uuid.uuid4()))
        )
        self._project_working_directory = project_working_directory

    def _collect_stdout_lines_reporting_timeout(
        self,
        command_argv: list[str],
        stdin_text: str,
        timeout_seconds: float,
        working_directory: Optional[str] = None,
    ) -> tuple[list[str], bool]:
        """Buffer stdout lines, returning whatever arrived plus a timeout flag.

        Buffering rather than streaming into the parser keeps the parser pure
        and keeps partial output usable when the deadline is hit mid-stream.
        """
        collected_stdout_lines: list[str] = []
        timed_out = False
        try:
            for stdout_line in self._process_launcher.stream_stdout_lines_until_exit(
                command_argv=command_argv,
                stdin_text=stdin_text,
                timeout_seconds=timeout_seconds,
                working_directory=working_directory,
            ):
                collected_stdout_lines.append(stdout_line)
        except NonInteractiveProcessTimedOutError:
            timed_out = True
        return collected_stdout_lines, timed_out

    def _build_non_interactive_stream_json_argv(self) -> list[str]:
        return [
            self._claude_executable_name,
            "-p",
            "--output-format",
            "stream-json",
            # The CLI rejects stream-json output without --verbose.
            "--verbose",
        ]

    def verify_harness_available_and_authorized(self) -> HarnessAvailabilityReport:
        version_probe_argv = [self._claude_executable_name, "--version"]
        try:
            collected_stdout_lines, timed_out = self._collect_stdout_lines_reporting_timeout(
                version_probe_argv, "", DEFAULT_AVAILABILITY_PROBE_TIMEOUT_SECONDS
            )
        except (FileNotFoundError, OSError) as launch_error:
            return HarnessAvailabilityReport(
                is_available=False,
                is_authorized=None,
                detail_text=f"could not launch {self._claude_executable_name}: {launch_error}",
            )

        version_text = "".join(collected_stdout_lines).strip()
        if timed_out or not version_text:
            return HarnessAvailabilityReport(
                is_available=False,
                is_authorized=None,
                detail_text=(
                    f"{self._claude_executable_name} --version produced no output"
                    + (" before the timeout" if timed_out else "")
                ),
            )
        return HarnessAvailabilityReport(
            is_available=True,
            is_authorized=None,
            detail_text=(
                f"{version_text}; login state assumed from the existing local "
                "OAuth session and not probed"
            ),
        )

    def find_active_session_identifier_for_working_directory(
        self, working_directory: str
    ) -> str:
        return find_active_session_identifier_for_working_directory(
            working_directory, self._claude_projects_root_directory
        )

    def read_session_display_name(
        self, session_identifier: str, working_directory: str
    ) -> Optional[str]:
        return read_session_display_name_from_transcript(
            session_identifier, working_directory, self._claude_projects_root_directory
        )

    def allocate_base_session_identifier(self) -> str:
        return self._generate_branch_session_identifier()

    def build_interactive_base_session_creation_command_line(
        self,
        new_base_session_identifier: str,
        preamble_text: str,
        display_name: Optional[str] = None,
    ) -> list[str]:
        """A plain interactive session with a fixed identifier and a first prompt.

        No ``--resume``, because there is nothing yet to resume from, and no
        ``-p``, because this launch exists partly to let the workspace-trust
        prompt be answered — which non-interactive mode skips rather than
        answers.
        """
        command_argv = [
            self._claude_executable_name,
            "--session-id",
            new_base_session_identifier,
        ]
        if display_name is not None:
            command_argv += ["--name", display_name]
        # Last, so a preamble beginning with a dash cannot be read as a flag.
        command_argv.append(preamble_text)
        return command_argv

    def allocate_branch_session_identifier(self) -> str:
        return self._generate_branch_session_identifier()

    def build_interactive_branch_fork_command_line(
        self,
        base_session_identifier: str,
        new_branch_session_identifier: str,
        branch_seed_prompt_text: str,
        display_name: Optional[str] = None,
    ) -> list[str]:
        """One interactive command that both forks the branch and opens it.

        Note what is absent: ``-p``. This project reserves non-interactive mode
        for updating the base session, which nobody watches. A branch is the
        session the user works in, so it must come up as a real terminal UI,
        and the seed rides along as the prompt argument that its first visible
        turn answers.
        """
        command_argv = [
            self._claude_executable_name,
            "--resume",
            base_session_identifier,
            "--fork-session",
            "--session-id",
            new_branch_session_identifier,
        ]
        if display_name is not None:
            command_argv += ["--name", display_name]
        # Positional, and last: the CLI takes the prompt as a bare argument, and
        # keeping it at the end means the seed can never be read as a flag value.
        command_argv.append(branch_seed_prompt_text)
        return command_argv

    def wait_until_session_transcript_is_durable(
        self,
        session_identifier: str,
        working_directory: str,
        timeout_seconds: float,
    ) -> bool:
        transcript_path = build_transcript_file_path(
            session_identifier, working_directory, self._claude_projects_root_directory
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            if os.path.exists(transcript_path):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(TRANSCRIPT_DURABILITY_POLL_INTERVAL_SECONDS)

    def submit_text_to_session_and_await_acknowledgment(
        self,
        session_identifier: str,
        submitted_text: str,
        acknowledgment_timeout_seconds: float,
    ) -> SessionAcknowledgment:
        submission_argv = self._build_non_interactive_stream_json_argv() + [
            "--resume",
            session_identifier,
        ]
        # The text goes on stdin: handoff payloads are large and may contain
        # anything, and argv is neither the right size nor the right shape.
        collected_stdout_lines, timed_out = self._collect_stdout_lines_reporting_timeout(
            submission_argv,
            submitted_text,
            acknowledgment_timeout_seconds,
            working_directory=self._project_working_directory,
        )
        parse_result = parse_stream_json_event_lines(
            collected_stdout_lines, observe_stream_event=self._observe_stream_event
        )
        acknowledgment_text = (
            parse_result.final_result_text
            if parse_result.final_result_text is not None
            else parse_result.accumulated_assistant_text
        )
        return SessionAcknowledgment(
            acknowledgment_text=acknowledgment_text,
            timed_out=timed_out,
        )

