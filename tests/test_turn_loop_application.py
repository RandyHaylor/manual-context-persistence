"""Tests for the startup decisions the application makes before looping.

This logic previously lived in the entry-point script and had no tests at all —
the one place the real adapters meet the core was the one place nothing
checked. The decisions here are the consequential ones: never starting without
capture unless that was asked for, never inventing a base session, and never
reading a closed stdin as consent.

Three on-disk states drive the hook flow, and the difference between the first
two is whose file it is. No ``settings.local.json`` at all means nothing of the
operator's exists yet, so it is created without asking. One that is already
there but does not register our hooks is theirs, so writing into it is a
question. One that registers them is the ordinary case.
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
from context_handoff.orchestration.branch_session_preamble import (
    GIT_COMMIT_REQUIREMENT_SENTENCE,
)
from context_handoff.project_state.context_handoff_settings_store import (
    ContextHandoffSettings,
    ContextHandoffSettingsStore,
)
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls
from tests.fakes.fake_user_interface_control_recording_all_calls import (
    FakeUserInterfaceControlRecordingAllCalls,
)

SETTINGS_REGISTERING_OUR_HOOKS = "registers_our_hooks"
SETTINGS_ABSENT = "absent"
SETTINGS_PRESENT_WITHOUT_OUR_HOOKS = "present_without_our_hooks"


def build_hook_event_entry(command_text: str) -> dict:
    return {"hooks": [{"type": "command", "command": command_text}]}


def write_harness_settings(project_directory: str, settings_dictionary: dict) -> str:
    state_directory = os.path.join(project_directory, ".claude")
    os.makedirs(state_directory, exist_ok=True)
    settings_path = os.path.join(state_directory, "settings.local.json")
    with open(settings_path, "w", encoding="utf-8") as settings_file:
        json.dump(settings_dictionary, settings_file)
    return settings_path


def write_settings_registering_both_hooks(project_directory: str) -> str:
    return write_harness_settings(
        project_directory,
        {
            "hooks": {
                "Stop": [
                    build_hook_event_entry("python3 context_to_keep_stop_hook.py")
                ],
                "UserPromptSubmit": [
                    build_hook_event_entry(
                        "python3 user_prompt_submit_capture_hook.py"
                    )
                ],
            }
        },
    )


def write_settings_belonging_to_someone_else(project_directory: str) -> str:
    """A real settings file with the operator's own content and no hooks of ours."""
    return write_harness_settings(
        project_directory,
        {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {"Stop": [build_hook_event_entry("python3 someone_elses_hook.py")]},
        },
    )


class ApplicationTestHarness:
    def __init__(
        self,
        tmp_path,
        harness_settings_state: str = SETTINGS_REGISTERING_OUR_HOOKS,
        **request_overrides,
    ):
        self.project_directory = str(tmp_path / "project")
        os.makedirs(self.project_directory, exist_ok=True)
        # A stand-in repository to copy from, and a stand-in home to copy to,
        # so no test touches the developer's real ~/.claude.
        self.hook_scripts_source_directory = str(tmp_path / "repository" / "hooks")
        os.makedirs(self.hook_scripts_source_directory, exist_ok=True)
        for hook_script_file_name in (
            "context_to_keep_stop_hook.py",
            "user_prompt_submit_capture_hook.py",
        ):
            with open(
                os.path.join(self.hook_scripts_source_directory, hook_script_file_name),
                "w",
                encoding="utf-8",
            ) as hook_script_file:
                hook_script_file.write("# stand-in\n")
        self.deployed_hook_scripts_directory = str(tmp_path / "home" / "hooks")

        self.harness_settings_path = os.path.join(
            self.project_directory, ".claude", "settings.local.json"
        )
        if harness_settings_state == SETTINGS_REGISTERING_OUR_HOOKS:
            write_settings_registering_both_hooks(self.project_directory)
        elif harness_settings_state == SETTINGS_PRESENT_WITHOUT_OUR_HOOKS:
            write_settings_belonging_to_someone_else(self.project_directory)

        self.fake_harness = FakeHarnessRecordingAllCalls()
        self.fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()
        self.written_lines: list[str] = []
        self.orchestrators_given_to_the_loop: list = []

        self.request = TurnLoopApplicationRequest(
            project_directory=self.project_directory,
            hook_scripts_source_directory=self.hook_scripts_source_directory,
            deployed_hook_scripts_directory=self.deployed_hook_scripts_directory,
            **request_overrides,
        )

    def read_harness_settings(self) -> dict:
        with open(self.harness_settings_path, "r", encoding="utf-8") as settings_file:
            return json.load(settings_file)

    def seeded_branch_preamble(self) -> str:
        """The text the first user-facing session was opened with.

        The fake records a session's seed as its first submitted text, keyed by
        the session it went to — never against the base, which a fork must leave
        untouched.
        """
        branch_session_identifier = self.orchestrators_given_to_the_loop[
            0
        ].current_branch_session_identifier
        return self.fake_harness.submitted_texts_by_session_identifier[
            branch_session_identifier
        ][0]

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


def test_no_settings_file_at_all_is_set_up_without_asking(tmp_path) -> None:
    """Nothing of the operator's exists yet, so there is nothing to disturb."""
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_ABSENT,
        create_new_base_session_without_asking=True,
    )

    assert application.run(scripted_answers=[]) == EXIT_CODE_SUCCESS
    installed_hooks = application.read_harness_settings()["hooks"]
    assert set(installed_hooks) == {"Stop", "UserPromptSubmit"}


def test_the_installed_command_points_at_the_deployed_scripts_not_the_repository(
    tmp_path,
) -> None:
    """The whole reason the scripts are deployed.

    A command naming the repository would break the project's settings file the
    moment the repository moved or was renamed.
    """
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_ABSENT,
        create_new_base_session_without_asking=True,
    )

    application.run(scripted_answers=[])

    written_settings_text = json.dumps(application.read_harness_settings())
    assert application.deployed_hook_scripts_directory in written_settings_text
    assert application.hook_scripts_source_directory not in written_settings_text


def test_the_scripts_are_deployed_before_the_command_naming_them_is_written(
    tmp_path,
) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_ABSENT,
        create_new_base_session_without_asking=True,
    )

    application.run(scripted_answers=[])

    for hook_script_file_name in (
        "context_to_keep_stop_hook.py",
        "user_prompt_submit_capture_hook.py",
    ):
        assert os.path.exists(
            os.path.join(
                application.deployed_hook_scripts_directory, hook_script_file_name
            )
        )


def test_the_deployed_scripts_are_rewritten_from_source_on_every_run(tmp_path) -> None:
    """Deployment happens every run, so an edit to a script always takes effect."""
    application = ApplicationTestHarness(
        tmp_path, create_new_base_session_without_asking=True
    )
    application.run()
    deployed_script_path = os.path.join(
        application.deployed_hook_scripts_directory, "context_to_keep_stop_hook.py"
    )
    os.remove(deployed_script_path)
    with open(
        os.path.join(
            application.hook_scripts_source_directory, "user_prompt_submit_capture_hook.py"
        ),
        "w",
        encoding="utf-8",
    ) as source_file:
        source_file.write("# updated in the repository\n")

    application.run()

    assert os.path.exists(deployed_script_path)
    with open(
        os.path.join(
            application.deployed_hook_scripts_directory,
            "user_prompt_submit_capture_hook.py",
        ),
        "r",
        encoding="utf-8",
    ) as deployed_file:
        assert deployed_file.read() == "# updated in the repository\n"


def test_setting_up_also_creates_our_own_settings_file(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_ABSENT,
        create_new_base_session_without_asking=True,
    )

    application.run(scripted_answers=[])

    settings_store = ContextHandoffSettingsStore(application.project_directory)
    assert settings_store.settings_file_exists()
    assert settings_store.read_settings() == ContextHandoffSettings()


def test_an_existing_settings_file_without_our_hooks_asks_first(tmp_path) -> None:
    """It is the operator's file, so writing into it is their decision."""
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_PRESENT_WITHOUT_OUR_HOOKS,
        create_new_base_session_without_asking=True,
    )

    assert application.run(scripted_answers=["install"]) == EXIT_CODE_SUCCESS
    installed_hooks = application.read_harness_settings()["hooks"]
    assert set(installed_hooks) == {"Stop", "UserPromptSubmit"}


def test_installing_preserves_what_was_already_in_the_file(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_PRESENT_WITHOUT_OUR_HOOKS,
        create_new_base_session_without_asking=True,
    )

    application.run(scripted_answers=["install"])

    settings = application.read_harness_settings()
    assert settings["permissions"] == {"allow": ["Bash(ls:*)"]}
    stop_hook_commands = [
        hook_definition["command"]
        for event_entry in settings["hooks"]["Stop"]
        for hook_definition in event_entry["hooks"]
    ]
    assert any("someone_elses_hook.py" in command for command in stop_hook_commands)
    assert any("context_to_keep_stop_hook.py" in command for command in stop_hook_commands)


def test_answering_abort_stops_the_run_and_writes_nothing(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_PRESENT_WITHOUT_OUR_HOOKS,
        create_new_base_session_without_asking=True,
    )

    exit_code = application.run(scripted_answers=["abort"])

    assert exit_code == EXIT_CODE_PREFLIGHT_FAILED
    assert application.fake_harness.created_base_session_preambles == []
    assert "someone_elses_hook.py" in json.dumps(application.read_harness_settings())
    assert "context_to_keep_stop_hook.py" not in json.dumps(
        application.read_harness_settings()
    )


def test_a_closed_stdin_is_not_consent_to_write_the_operators_settings(
    tmp_path,
) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=SETTINGS_PRESENT_WITHOUT_OUR_HOOKS,
        create_new_base_session_without_asking=True,
    )

    exit_code = application.run(scripted_answers=[])

    assert exit_code == EXIT_CODE_PREFLIGHT_FAILED
    assert "context_to_keep_stop_hook.py" not in json.dumps(
        application.read_harness_settings()
    )


def test_there_is_no_way_to_start_without_the_capture_hooks(tmp_path) -> None:
    """Not a degraded run: the loop would rotate turns that hand off nothing.

    An override existed once, and every answer other than installing now stops
    the run instead of starting one that records nothing.
    """
    for refusing_answers in ([], ["abort"], ["no"]):
        application = ApplicationTestHarness(
            tmp_path / str(len(refusing_answers)),
            harness_settings_state=SETTINGS_PRESENT_WITHOUT_OUR_HOOKS,
            create_new_base_session_without_asking=True,
        )

        exit_code = application.run(scripted_answers=refusing_answers)

        assert exit_code == EXIT_CODE_PREFLIGHT_FAILED
        assert application.fake_harness.created_base_session_preambles == []
        assert application.orchestrators_given_to_the_loop == []


def test_no_request_field_can_bypass_the_hooks(tmp_path) -> None:
    """The override is gone from the request, not just from the command line."""
    assert not hasattr(
        TurnLoopApplicationRequest(
            project_directory=str(tmp_path),
            hook_scripts_source_directory=str(tmp_path),
        ),
        "skip_hook_preflight",
    )


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


@pytest.mark.parametrize(
    "harness_settings_state",
    [SETTINGS_REGISTERING_OUR_HOOKS, SETTINGS_ABSENT],
)
def test_the_hook_report_is_always_shown(tmp_path, harness_settings_state: str) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        harness_settings_state=harness_settings_state,
        create_new_base_session_without_asking=True,
    )

    application.run(scripted_answers=[])

    assert any("hooks:" in line for line in application.written_lines)


def test_a_commit_is_not_asked_for_when_the_setting_is_off(tmp_path) -> None:
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)

    application.run()

    seeded_preamble = application.seeded_branch_preamble()
    assert GIT_COMMIT_REQUIREMENT_SENTENCE not in seeded_preamble


def test_the_settings_file_switches_the_commit_requirement_on(tmp_path) -> None:
    application = ApplicationTestHarness(tmp_path, create_new_base_session_without_asking=True)
    ContextHandoffSettingsStore(application.project_directory).write_settings(
        ContextHandoffSettings(require_git_commit=True)
    )

    application.run()

    seeded_preamble = application.seeded_branch_preamble()
    assert GIT_COMMIT_REQUIREMENT_SENTENCE in seeded_preamble


def test_the_command_line_flag_overrides_the_settings_file(tmp_path) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        create_new_base_session_without_asking=True,
        require_git_commit_override=False,
    )
    ContextHandoffSettingsStore(application.project_directory).write_settings(
        ContextHandoffSettings(require_git_commit=True)
    )

    application.run()

    seeded_preamble = application.seeded_branch_preamble()
    assert GIT_COMMIT_REQUIREMENT_SENTENCE not in seeded_preamble


def test_the_command_line_flag_can_switch_it_on_without_a_settings_file(
    tmp_path,
) -> None:
    application = ApplicationTestHarness(
        tmp_path,
        create_new_base_session_without_asking=True,
        require_git_commit_override=True,
    )

    application.run()

    seeded_preamble = application.seeded_branch_preamble()
    assert GIT_COMMIT_REQUIREMENT_SENTENCE in seeded_preamble
