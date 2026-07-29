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
import uuid
from typing import Callable, Optional

from context_handoff.interfaces.harness_interface import (
    BranchSessionCreationResult,
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


class BranchSessionNotDurableError(RuntimeError):
    """A branch was requested but its transcript never appeared on disk.

    Raised rather than returning the identifier anyway: a branch that is not
    durable fails later, in the next turn, where the cause is far harder to
    see.
    """


class ClaudeCliHarnessAdapter(HarnessInterface):
    def __init__(
        self,
        process_launcher: Optional[NonInteractiveProcessLauncherInterface] = None,
        claude_projects_root_directory: str = DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
        claude_executable_name: str = DEFAULT_CLAUDE_EXECUTABLE_NAME,
        observe_stream_event: Optional[Callable[[str, str], None]] = None,
        generate_branch_session_identifier: Optional[Callable[[], str]] = None,
    ) -> None:
        self._process_launcher = process_launcher or SubprocessNonInteractiveProcessLauncher(
            observe_stream_event=observe_stream_event
        )
        self._claude_projects_root_directory = claude_projects_root_directory
        self._claude_executable_name = claude_executable_name
        self._observe_stream_event = observe_stream_event
        self._generate_branch_session_identifier = (
            generate_branch_session_identifier or (lambda: str(uuid.uuid4()))
        )

    def _collect_stdout_lines_reporting_timeout(
        self, command_argv: list[str], stdin_text: str, timeout_seconds: float
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

    def create_branch_session_from_base_session(
        self,
        base_session_identifier: str,
        working_directory: str,
        branch_seed_prompt_text: str,
    ) -> BranchSessionCreationResult:
        branch_session_identifier = self._generate_branch_session_identifier()
        branch_creation_argv = [
            self._claude_executable_name,
            "--resume",
            base_session_identifier,
            "--fork-session",
            "--session-id",
            branch_session_identifier,
            # The seed is what forces the fork's transcript to materialize; a
            # forked session with no content is not written to disk, so a
            # seedless fork could not be resumed afterwards.
            "-p",
            branch_seed_prompt_text,
        ]
        self._collect_stdout_lines_reporting_timeout(
            branch_creation_argv, "", DEFAULT_BRANCH_SEED_TIMEOUT_SECONDS
        )

        branch_transcript_path = build_transcript_file_path(
            branch_session_identifier,
            working_directory,
            self._claude_projects_root_directory,
        )
        if not os.path.exists(branch_transcript_path):
            raise BranchSessionNotDurableError(
                f"branch {branch_session_identifier} was requested from "
                f"{base_session_identifier} but no transcript appeared at "
                f"{branch_transcript_path}"
            )
        return BranchSessionCreationResult(
            branch_session_identifier=branch_session_identifier,
            transcript_path=branch_transcript_path,
        )

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
            submission_argv, submitted_text, acknowledgment_timeout_seconds
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

    def build_interactive_resume_command_line(
        self, session_identifier: str, display_name: Optional[str] = None
    ) -> list[str]:
        command_argv = [
            self._claude_executable_name,
            "--resume",
            session_identifier,
        ]
        if display_name is not None:
            command_argv += ["--name", display_name]
        return command_argv
