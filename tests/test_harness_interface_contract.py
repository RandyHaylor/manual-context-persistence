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

    def test_allocated_branch_identifier_is_distinct_from_the_base(self) -> None:
        harness = self.build_harness_under_test()
        branch_session_identifier = harness.allocate_branch_session_identifier()
        assert branch_session_identifier
        assert branch_session_identifier != BASE_SESSION_IDENTIFIER_UNDER_TEST

    def test_two_allocated_branch_identifiers_differ(self) -> None:
        harness = self.build_harness_under_test()
        assert (
            harness.allocate_branch_session_identifier()
            != harness.allocate_branch_session_identifier()
        )

    def test_branch_fork_command_line_carries_base_branch_seed_and_name(self) -> None:
        harness = self.build_harness_under_test()
        branch_session_identifier = harness.allocate_branch_session_identifier()
        command_line_argv = harness.build_interactive_branch_fork_command_line(
            base_session_identifier=BASE_SESSION_IDENTIFIER_UNDER_TEST,
            new_branch_session_identifier=branch_session_identifier,
            branch_seed_prompt_text="seed text",
            display_name="a branch",
        )
        assert isinstance(command_line_argv, list)
        assert all(isinstance(argument, str) for argument in command_line_argv)
        assert BASE_SESSION_IDENTIFIER_UNDER_TEST in command_line_argv
        assert branch_session_identifier in command_line_argv
        assert "seed text" in command_line_argv
        assert "a branch" in command_line_argv

    def test_branch_fork_command_line_is_never_non_interactive(self) -> None:
        """The defect this contract exists to prevent.

        A branch run headlessly finishes its turn before the user's window
        exists, so the window they are given is already spent. Only the base
        session may be driven without a terminal.
        """
        harness = self.build_harness_under_test()
        command_line_argv = harness.build_interactive_branch_fork_command_line(
            base_session_identifier=BASE_SESSION_IDENTIFIER_UNDER_TEST,
            new_branch_session_identifier=harness.allocate_branch_session_identifier(),
            branch_seed_prompt_text="seed text",
            display_name="a branch",
        )
        assert "-p" not in command_line_argv
        assert "--print" not in command_line_argv

    def test_allocating_a_branch_identifier_creates_no_session(self) -> None:
        """Allocation must be inert; the fork happens when the window runs."""
        harness = self.build_harness_under_test()
        branch_session_identifier = harness.allocate_branch_session_identifier()
        assert (
            harness.wait_until_session_transcript_is_durable(
                session_identifier=branch_session_identifier,
                working_directory=WORKING_DIRECTORY_UNDER_TEST,
                timeout_seconds=0.0,
            )
            is False
        )

    def test_base_session_creation_command_line_carries_id_and_preamble(self) -> None:
        harness = self.build_harness_under_test()
        base_session_identifier = harness.allocate_base_session_identifier()
        command_line_argv = harness.build_interactive_base_session_creation_command_line(
            new_base_session_identifier=base_session_identifier,
            preamble_text="You are a base session that only accumulates context.",
            display_name="a base",
        )
        assert isinstance(command_line_argv, list)
        assert all(isinstance(argument, str) for argument in command_line_argv)
        assert base_session_identifier in command_line_argv
        assert (
            "You are a base session that only accumulates context."
            in command_line_argv
        )
        assert "a base" in command_line_argv

    def test_base_session_creation_command_line_is_interactive(self) -> None:
        """It has to be: the trust prompt cannot be answered without a terminal."""
        harness = self.build_harness_under_test()
        command_line_argv = harness.build_interactive_base_session_creation_command_line(
            new_base_session_identifier=harness.allocate_base_session_identifier(),
            preamble_text="preamble",
        )
        assert "-p" not in command_line_argv
        assert "--print" not in command_line_argv
        # Nothing exists to resume from; this command is what creates it.
        assert "--resume" not in command_line_argv

    def test_two_base_sessions_get_different_identifiers(self) -> None:
        harness = self.build_harness_under_test()
        assert (
            harness.allocate_base_session_identifier()
            != harness.allocate_base_session_identifier()
        )

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

    def test_interface_exposes_no_way_to_open_a_session_without_forking(self) -> None:
        """Opening and forking must stay one operation.

        Two separate operations are what allowed a branch to be created ahead of
        the window that was supposed to show it being created.
        """
        assert not hasattr(
            self.build_harness_under_test(), "build_interactive_resume_command_line"
        )

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
    branch_session_identifier = harness.allocate_branch_session_identifier()
    harness.build_interactive_branch_fork_command_line(
        base_session_identifier=BASE_SESSION_IDENTIFIER_UNDER_TEST,
        new_branch_session_identifier=branch_session_identifier,
        branch_seed_prompt_text="seed text",
    )
    assert BASE_SESSION_IDENTIFIER_UNDER_TEST not in harness.submitted_texts_by_session_identifier
    assert harness.submitted_texts_by_session_identifier[
        branch_session_identifier
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
