"""Tests for the startup decisions the application makes before looping.

This logic previously lived in the entry-point script and had no tests at all —
the one place the real adapters meet the core was the one place nothing
checked. The decisions here are the consequential ones: refusing to start
without capture, never inventing a base session, and never reading a closed
stdin as consent.
"""
from __future__ import annotations

import json
import os

import pytest

from context_handoff.application.turn_loop_application import (
    EXIT_CODE_PREFLIGHT_FAILED,
    EXIT_CODE_SUCCESS,
    TurnLoopApplicationRequest,
    run_turn_loop_application,
)
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls
from tests.fakes.fake_user_interface_control_recording_all_calls import (
    FakeUserInterfaceControlRecordingAllCalls,
)


def write_settings_registering_both_hooks(project_directory: str) -> None:
    state_directory = os.path.join(project_directory, ".claude")
    os.makedirs(state_directory, exist_ok=True)
    with open(
        os.path.join(state_directory, "settings.local.json"), "w", encoding="utf-8"
    ) as settings_file:
        json.dump(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 context_to_keep_stop_hook.py",
                                }
                            ]
                        }
                    ],
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "python3 user_prompt_submit_capture_hook.py"
                                    ),
                                }
                            ]
                        }
                    ],
                }
            },
            settings_file,
        )


class ApplicationTestHarness:
    def __init__(self, tmp_path, register_hooks: bool = True, **request_overrides):
        self.project_directory = str(tmp_path / "project")
        os.makedirs(self.project_directory, exist_ok=True)
        if register_hooks:
            write_settings_registering_both_hooks(self.project_directory)

        self.fake_harness = FakeHarnessRecordingAllCalls()
        self.fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()
        self.written_lines: list[str] = []
        self.orchestrators_given_to_the_loop: list = []

        self.request = TurnLoopApplicationRequest(
            project_directory=self.project_directory,
            **request_overrides,
        )

    def record_turn_loop_invocation(self, orchestrator) -> int:
        self.orchestrators_given_to_the_loop.append(orchestrator)
        return 0

    def run(self, scripted_answers=None) -> int:
        remaining_answers = list(scripted_answers or [])

        def read_answer(_prompt_text: str) -> str:
            if not remaining_answers:
                raise EOFError
            return remaining_answers.pop(0)

        return run_turn_loop_application(
            request=self.request,
            harness=self.fake_harness,
            user_interface_control=self.fake_user_interface_control,
            run_turn_loop_with=self.record_turn_loop_invocation,
            read_answer=read_answer,
            write_line=self.written_lines.append,
        )


def test_an_unavailable_harness_stops_before_anything_is_created(tmp_path) -> None:
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)
    application.fake_harness = FakeHarnessRecordingAllCalls(is_available=False)

    exit_code = application.run()

    assert exit_code == EXIT_CODE_PREFLIGHT_FAILED
    assert application.fake_harness.created_base_session_preambles == []
    assert application.orchestrators_given_to_the_loop == []


def test_missing_capture_hooks_refuse_the_run(tmp_path) -> None:
    """Starting without capture looks fine and records nothing."""
    application = ApplicationTestHarness(
        tmp_path, register_hooks=False, create_new_base_session_without_asking=True
    )

    exit_code = application.run()

    assert exit_code == EXIT_CODE_PREFLIGHT_FAILED
    assert application.fake_harness.created_base_session_preambles == []


def test_missing_hooks_can_be_overridden_deliberately(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        register_hooks=False,
        create_new_base_session_without_asking=True,
        skip_hook_preflight=True,
    )

    assert application.run() == EXIT_CODE_SUCCESS
    assert len(application.fake_harness.created_base_session_preambles) == 1


def test_the_new_base_flag_creates_one_without_asking(tmp_path) -> None:
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)

    assert application.run() == EXIT_CODE_SUCCESS
    assert len(application.fake_harness.created_base_session_preambles) == 1


def test_the_resume_flag_creates_nothing(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path, base_session_identifier_to_resume="an-existing-base"
    )

    assert application.run() == EXIT_CODE_SUCCESS
    assert application.fake_harness.created_base_session_preambles == []


def test_with_no_flag_the_user_is_asked(tmp_path) -> None:
    application = ApplicationTestHarness(tmp_path)

    assert application.run(scripted_answers=["new"]) == EXIT_CODE_SUCCESS
    assert len(application.fake_harness.created_base_session_preambles) == 1


def test_answering_resume_uses_the_named_base(tmp_path) -> None:
    application = ApplicationTestHarness(tmp_path)

    exit_code = application.run(scripted_answers=["resume", "an-existing-base"])

    assert exit_code == EXIT_CODE_SUCCESS
    assert application.fake_harness.created_base_session_preambles == []


def test_a_closed_stdin_is_not_consent_to_create_a_base(tmp_path) -> None:
    """Defaulting here would silently strand a user's accumulated context."""
    application = ApplicationTestHarness(tmp_path)

    exit_code = application.run(scripted_answers=[])

    assert exit_code == EXIT_CODE_PREFLIGHT_FAILED
    assert application.fake_harness.created_base_session_preambles == []


def test_the_window_name_is_derived_from_the_base_session_when_unset(tmp_path) -> None:
    """The spec asks for a window id derived from the base session id."""
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)

    application.run()

    opened_window_identifiers = list(
        application.fake_user_interface_control.event_log_by_window_identifier.keys()
    )
    assert len(opened_window_identifiers) == 1
    base_session_identifier = application.orchestrators_given_to_the_loop[
        0
    ].base_session_identifier
    assert base_session_identifier[:8] in opened_window_identifiers[0]


def test_an_explicit_window_name_is_honoured(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        create_new_base_session_without_asking=True,
        shared_window_identifier="my-window",
    )

    application.run()

    assert list(
        application.fake_user_interface_control.event_log_by_window_identifier.keys()
    ) == ["my-window"]


def test_the_loop_receives_an_orchestrator_with_a_branch_already_running(
    tmp_path,
) -> None:
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)

    application.run()

    assert len(application.orchestrators_given_to_the_loop) == 1
    assert application.orchestrators_given_to_the_loop[0].current_branch_session_identifier


def test_an_interrupted_loop_leaves_the_window_open(tmp_path) -> None:
    """The user may be mid-conversation; closing would discard their turn."""
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)

    def raise_keyboard_interrupt(_orchestrator) -> int:
        raise KeyboardInterrupt

    application.record_turn_loop_invocation = raise_keyboard_interrupt

    assert application.run() == EXIT_CODE_SUCCESS
    assert application.fake_user_interface_control.closed_window_identifiers == []


@pytest.mark.parametrize("register_hooks", [True, False])
def test_the_hook_report_is_always_shown(tmp_path, register_hooks: bool) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        register_hooks=register_hooks,
        create_new_base_session_without_asking=True,
        skip_hook_preflight=True,
    )

    application.run()

    assert any("hooks:" in line for line in application.written_lines)
