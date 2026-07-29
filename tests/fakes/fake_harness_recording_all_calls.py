"""In-memory HarnessInterface that records every call and invents no I/O.

Lets the turn loop be tested with no Claude CLI process, no subprocess, and no
filesystem. Session state is a dictionary of session identifier to the list of
texts submitted to that session, which is enough to assert that the base
session accumulated handoffs and that branch sessions stayed separate.
"""
from __future__ import annotations

import itertools
from typing import Optional

from context_handoff.interfaces.harness_interface import (
    BranchSessionCreationResult,
    HarnessAvailabilityReport,
    HarnessInterface,
    SessionAcknowledgment,
)


class FakeHarnessRecordingAllCalls(HarnessInterface):
    def __init__(
        self,
        active_session_identifier_by_working_directory: Optional[dict[str, str]] = None,
        is_available: bool = True,
        is_authorized: Optional[bool] = True,
        acknowledgment_text: str = "acknowledged",
        should_time_out_on_submission: bool = False,
    ) -> None:
        self._active_session_identifier_by_working_directory = dict(
            active_session_identifier_by_working_directory or {}
        )
        self._is_available = is_available
        self._is_authorized = is_authorized
        self._acknowledgment_text = acknowledgment_text
        self._should_time_out_on_submission = should_time_out_on_submission
        self._branch_identifier_counter = itertools.count(1)

        self.display_name_by_session_identifier: dict[str, str] = {}
        self.submitted_texts_by_session_identifier: dict[str, list[str]] = {}
        self.created_branch_parent_identifiers: list[str] = []
        self.availability_probe_count: int = 0

    def verify_harness_available_and_authorized(self) -> HarnessAvailabilityReport:
        self.availability_probe_count += 1
        return HarnessAvailabilityReport(
            is_available=self._is_available,
            is_authorized=self._is_authorized,
            detail_text="fake harness",
        )

    def find_active_session_identifier_for_working_directory(
        self, working_directory: str
    ) -> str:
        try:
            return self._active_session_identifier_by_working_directory[working_directory]
        except KeyError:
            raise LookupError(
                f"no fake session registered for working directory {working_directory!r}"
            ) from None

    def read_session_display_name(
        self, session_identifier: str, working_directory: str
    ) -> Optional[str]:
        return self.display_name_by_session_identifier.get(session_identifier)

    def create_branch_session_from_base_session(
        self,
        base_session_identifier: str,
        working_directory: str,
        branch_seed_prompt_text: str,
    ) -> BranchSessionCreationResult:
        self.created_branch_parent_identifiers.append(base_session_identifier)
        branch_session_identifier = (
            f"fake-branch-{next(self._branch_identifier_counter)}-of-{base_session_identifier}"
        )
        # The seed is recorded against the branch, never against the base: the
        # base session must be left unmodified by a fork.
        self.submitted_texts_by_session_identifier[branch_session_identifier] = [
            branch_seed_prompt_text
        ]
        return BranchSessionCreationResult(
            branch_session_identifier=branch_session_identifier,
            transcript_path=f"/fake/transcripts/{branch_session_identifier}",
        )

    def submit_text_to_session_and_await_acknowledgment(
        self,
        session_identifier: str,
        submitted_text: str,
        acknowledgment_timeout_seconds: float,
    ) -> SessionAcknowledgment:
        self.submitted_texts_by_session_identifier.setdefault(
            session_identifier, []
        ).append(submitted_text)
        if self._should_time_out_on_submission:
            return SessionAcknowledgment(acknowledgment_text="", timed_out=True)
        return SessionAcknowledgment(
            acknowledgment_text=self._acknowledgment_text, timed_out=False
        )

    def build_interactive_resume_command_line(
        self, session_identifier: str, display_name: Optional[str] = None
    ) -> list[str]:
        command_line_argv = ["fake-harness", "--resume", session_identifier]
        if display_name is not None:
            command_line_argv += ["--name", display_name]
        return command_line_argv
