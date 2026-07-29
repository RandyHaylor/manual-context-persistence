"""Contract every HarnessInterface implementation must satisfy.

``HarnessInterfaceContractTestSuite`` is written against the interface only.
Each implementation — the fake here, the Claude CLI adapter later — subclasses
it and supplies a factory, so a real adapter cannot quietly diverge from the
behaviour the turn loop relies on.
"""
from __future__ import annotations

import inspect

import pytest

from context_handoff.interfaces.harness_interface import (
    SessionCreationResult,
    HarnessAvailabilityReport,
    HarnessInterface,
    SessionAcknowledgment,
)
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls


WORKING_DIRECTORY_UNDER_TEST = "/fake/project"
BASE_SESSION_IDENTIFIER_UNDER_TEST = "base-session"


class HarnessInterfaceContractTestSuite:
    """Subclass and override ``build_harness_under_test``."""

    def build_harness_under_test(self) -> HarnessInterface:
        raise NotImplementedError

    def test_availability_probe_returns_a_report(self) -> None:
        report = self.build_harness_under_test().verify_harness_available_and_authorized()
        assert isinstance(report, HarnessAvailabilityReport)
        assert isinstance(report.is_available, bool)
        assert report.is_authorized is None or isinstance(report.is_authorized, bool)
        assert isinstance(report.detail_text, str)

    def test_unknown_working_directory_raises_lookup_error(self) -> None:
        harness = self.build_harness_under_test()
        with pytest.raises(LookupError):
            harness.find_active_session_identifier_for_working_directory(
                "/directory/with/no/session"
            )

    def test_branch_creation_returns_a_distinct_durable_identifier(self) -> None:
        harness = self.build_harness_under_test()
        result = harness.create_branch_session_from_base_session(
            base_session_identifier=BASE_SESSION_IDENTIFIER_UNDER_TEST,
            working_directory=WORKING_DIRECTORY_UNDER_TEST,
            branch_seed_prompt_text="seed",
        )
        assert isinstance(result, SessionCreationResult)
        assert result.session_identifier
        assert result.session_identifier != BASE_SESSION_IDENTIFIER_UNDER_TEST
        assert result.transcript_path

    def test_two_branches_of_one_base_get_different_identifiers(self) -> None:
        harness = self.build_harness_under_test()
        first_branch = harness.create_branch_session_from_base_session(
            BASE_SESSION_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST, "seed"
        )
        second_branch = harness.create_branch_session_from_base_session(
            BASE_SESSION_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST, "seed"
        )
        assert (
            first_branch.session_identifier
            != second_branch.session_identifier
        )

    def test_base_session_creation_returns_a_durable_session(self) -> None:
        harness = self.build_harness_under_test()
        result = harness.create_base_session_with_preamble(
            working_directory=WORKING_DIRECTORY_UNDER_TEST,
            preamble_text="You are a base session that only accumulates context.",
        )
        assert isinstance(result, SessionCreationResult)
        assert result.session_identifier
        assert result.transcript_path

    def test_two_base_sessions_get_different_identifiers(self) -> None:
        harness = self.build_harness_under_test()
        first_base = harness.create_base_session_with_preamble(
            WORKING_DIRECTORY_UNDER_TEST, "preamble"
        )
        second_base = harness.create_base_session_with_preamble(
            WORKING_DIRECTORY_UNDER_TEST, "preamble"
        )
        assert first_base.session_identifier != second_base.session_identifier

    def test_submission_returns_an_acknowledgment(self) -> None:
        harness = self.build_harness_under_test()
        acknowledgment = harness.submit_text_to_session_and_await_acknowledgment(
            session_identifier=BASE_SESSION_IDENTIFIER_UNDER_TEST,
            submitted_text="handoff payload",
            acknowledgment_timeout_seconds=30.0,
        )
        assert isinstance(acknowledgment, SessionAcknowledgment)
        assert isinstance(acknowledgment.acknowledgment_text, str)
        assert isinstance(acknowledgment.timed_out, bool)

    def test_interactive_command_line_is_argv_containing_the_session(self) -> None:
        command_line_argv = self.build_harness_under_test().build_interactive_resume_command_line(
            session_identifier=BASE_SESSION_IDENTIFIER_UNDER_TEST,
            display_name="a branch",
        )
        assert isinstance(command_line_argv, list)
        assert all(isinstance(argument, str) for argument in command_line_argv)
        assert BASE_SESSION_IDENTIFIER_UNDER_TEST in command_line_argv
        assert "a branch" in command_line_argv

    def test_interface_exposes_no_credential_management_operation(self) -> None:
        """The POC assumes an existing local OAuth login; nothing may manage it."""
        forbidden_name_fragments = ("login", "logout", "token", "credential", "api_key")
        public_method_names = [
            name
            for name, _ in inspect.getmembers(HarnessInterface, inspect.isfunction)
            if not name.startswith("_")
        ]
        for method_name in public_method_names:
            for fragment in forbidden_name_fragments:
                assert fragment not in method_name.lower(), (
                    f"{method_name} suggests credential management, which is out of scope"
                )


class TestFakeHarnessSatisfiesHarnessInterfaceContract(HarnessInterfaceContractTestSuite):
    def build_harness_under_test(self) -> HarnessInterface:
        return FakeHarnessRecordingAllCalls(
            active_session_identifier_by_working_directory={
                WORKING_DIRECTORY_UNDER_TEST: BASE_SESSION_IDENTIFIER_UNDER_TEST
            }
        )


def test_fake_harness_leaves_the_base_session_untouched_when_branching() -> None:
    harness = FakeHarnessRecordingAllCalls()
    branch = harness.create_branch_session_from_base_session(
        BASE_SESSION_IDENTIFIER_UNDER_TEST, WORKING_DIRECTORY_UNDER_TEST, "seed text"
    )
    assert BASE_SESSION_IDENTIFIER_UNDER_TEST not in harness.submitted_texts_by_session_identifier
    assert harness.submitted_texts_by_session_identifier[
        branch.session_identifier
    ] == ["seed text"]


def test_fake_harness_accumulates_submissions_on_the_base_session() -> None:
    harness = FakeHarnessRecordingAllCalls()
    harness.submit_text_to_session_and_await_acknowledgment(
        BASE_SESSION_IDENTIFIER_UNDER_TEST, "first handoff", 30.0
    )
    harness.submit_text_to_session_and_await_acknowledgment(
        BASE_SESSION_IDENTIFIER_UNDER_TEST, "second handoff", 30.0
    )
    assert harness.submitted_texts_by_session_identifier[
        BASE_SESSION_IDENTIFIER_UNDER_TEST
    ] == ["first handoff", "second handoff"]


def test_fake_harness_reports_timeout_without_raising() -> None:
    harness = FakeHarnessRecordingAllCalls(should_time_out_on_submission=True)
    acknowledgment = harness.submit_text_to_session_and_await_acknowledgment(
        BASE_SESSION_IDENTIFIER_UNDER_TEST, "handoff", 0.1
    )
    assert acknowledgment.timed_out is True
