"""Tests for the Claude CLI harness adapter, driven entirely by a fake launcher.

Two jobs here. First, the adapter must satisfy the same contract suite the fake
harness satisfies — that is the whole point of having a contract suite. Second,
the adapter must build the exact argv the CLI expects, which is asserted
directly because a wrong flag is the failure mode a fake cannot otherwise
reveal.
"""
from __future__ import annotations

import json
import os

import pytest

from context_handoff.adapters.claude_cli.claude_cli_harness_adapter import (
    ClaudeCliHarnessAdapter,
)
from context_handoff.adapters.claude_cli.claude_cli_transcript_locator import (
    build_transcript_file_path,
)
from context_handoff.interfaces.harness_interface import HarnessInterface
from tests.fakes.fake_non_interactive_process_launcher import (
    FakeNonInteractiveProcessLauncher,
)
from tests.test_harness_interface_contract import (
    BASE_SESSION_IDENTIFIER_UNDER_TEST,
    WORKING_DIRECTORY_UNDER_TEST,
    HarnessInterfaceContractTestSuite,
)


def build_result_event_line(result_text: str) -> str:
    return json.dumps({"type": "result", "result": result_text, "is_error": False})


def make_transcript_appear_on_launch(projects_root_directory: str):
    """Side effect that writes the transcript the CLI would have written.

    Reads the session identifier out of the argv the adapter built, so the test
    double stays honest: if the adapter stops passing --session-id, the file
    lands nowhere and the durability check fails, which is correct.
    """

    def write_transcript_for_recorded_launch(recorded_launch) -> None:
        command_argv = recorded_launch.command_argv
        if "--session-id" not in command_argv:
            return
        session_identifier = command_argv[command_argv.index("--session-id") + 1]
        transcript_path = build_transcript_file_path(
            session_identifier, WORKING_DIRECTORY_UNDER_TEST, projects_root_directory
        )
        os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
        with open(transcript_path, "w", encoding="utf-8") as transcript_file:
            transcript_file.write(json.dumps({"type": "user"}) + "\n")

    return write_transcript_for_recorded_launch


def build_adapter_whose_branches_become_durable(
    projects_root_directory: str,
) -> ClaudeCliHarnessAdapter:
    return ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(
            stdout_lines_to_yield=[build_result_event_line("acknowledged")],
            on_launch_side_effect=make_transcript_appear_on_launch(
                projects_root_directory
            ),
        ),
        claude_projects_root_directory=projects_root_directory,
    )


class TestClaudeCliHarnessAdapterSatisfiesHarnessInterfaceContract(
    HarnessInterfaceContractTestSuite
):
    @pytest.fixture(autouse=True)
    def _bind_temporary_projects_root(self, tmp_path) -> None:
        self._projects_root_directory = str(tmp_path)
        transcript_path = build_transcript_file_path(
            BASE_SESSION_IDENTIFIER_UNDER_TEST,
            WORKING_DIRECTORY_UNDER_TEST,
            self._projects_root_directory,
        )
        os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
        with open(transcript_path, "w", encoding="utf-8") as transcript_file:
            transcript_file.write(json.dumps({"type": "user"}) + "\n")

    def build_harness_under_test(self) -> HarnessInterface:
        return build_adapter_whose_branches_become_durable(self._projects_root_directory)


def test_submission_argv_resumes_the_session_and_streams_json(tmp_path) -> None:
    process_launcher = FakeNonInteractiveProcessLauncher(
        stdout_lines_to_yield=[build_result_event_line("acknowledged")]
    )
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
    )

    acknowledgment = adapter.submit_text_to_session_and_await_acknowledgment(
        session_identifier="base-session",
        submitted_text="handoff payload",
        acknowledgment_timeout_seconds=45.0,
    )

    assert acknowledgment.acknowledgment_text == "acknowledged"
    assert acknowledgment.timed_out is False

    recorded_launch = process_launcher.recorded_launches[0]
    assert recorded_launch.command_argv[0] == "claude"
    assert "-p" in recorded_launch.command_argv
    assert "--resume" in recorded_launch.command_argv
    assert "base-session" in recorded_launch.command_argv
    assert "--output-format" in recorded_launch.command_argv
    assert "stream-json" in recorded_launch.command_argv
    # stream-json is rejected by the CLI without --verbose.
    assert "--verbose" in recorded_launch.command_argv
    assert recorded_launch.timeout_seconds == 45.0


def test_submitted_text_travels_on_stdin_not_in_argv(tmp_path) -> None:
    """Handoff payloads are large and arbitrary; argv is the wrong channel."""
    process_launcher = FakeNonInteractiveProcessLauncher(
        stdout_lines_to_yield=[build_result_event_line("ok")]
    )
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
    )
    submitted_text = "handoff payload with 'quotes' and\nnewlines"

    adapter.submit_text_to_session_and_await_acknowledgment(
        "base-session", submitted_text, 30.0
    )

    recorded_launch = process_launcher.recorded_launches[0]
    assert recorded_launch.stdin_text == submitted_text
    assert submitted_text not in recorded_launch.command_argv


def test_submission_timeout_is_reported_with_partial_text(tmp_path) -> None:
    process_launcher = FakeNonInteractiveProcessLauncher(
        stdout_lines_to_yield=[
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "partial ack"}]},
                }
            )
        ],
        should_time_out_after_yielding=True,
    )
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
    )

    acknowledgment = adapter.submit_text_to_session_and_await_acknowledgment(
        "base-session", "handoff", 0.5
    )

    assert acknowledgment.timed_out is True
    assert "partial ack" in acknowledgment.acknowledgment_text


def test_branch_fork_command_line_forks_the_base_into_a_new_session(tmp_path) -> None:
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )

    branch_session_identifier = adapter.allocate_branch_session_identifier()
    command_argv = adapter.build_interactive_branch_fork_command_line(
        base_session_identifier="base-session",
        new_branch_session_identifier=branch_session_identifier,
        branch_seed_prompt_text="[branch seed]",
        display_name="context branch",
    )

    assert command_argv == [
        "claude",
        "--resume",
        "base-session",
        "--fork-session",
        "--session-id",
        branch_session_identifier,
        "--name",
        "context branch",
        "[branch seed]",
    ]
    assert branch_session_identifier != "base-session"


def test_branch_fork_command_line_launches_no_process_of_its_own(tmp_path) -> None:
    """Building the branch command must not create the branch.

    The window the user watches is what runs this argv. An adapter that also
    ran it here would produce the very thing this design removed: a branch that
    has already taken its turn before anybody can see it.
    """
    process_launcher = FakeNonInteractiveProcessLauncher()
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
    )

    adapter.build_interactive_branch_fork_command_line(
        base_session_identifier="base-session",
        new_branch_session_identifier=adapter.allocate_branch_session_identifier(),
        branch_seed_prompt_text="[branch seed]",
    )

    assert process_launcher.recorded_launches == []


def test_branch_fork_command_line_is_never_headless(tmp_path) -> None:
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )

    command_argv = adapter.build_interactive_branch_fork_command_line(
        base_session_identifier="base-session",
        new_branch_session_identifier=adapter.allocate_branch_session_identifier(),
        branch_seed_prompt_text="[branch seed]",
    )

    assert "-p" not in command_argv
    assert "--print" not in command_argv


def test_branch_fork_command_line_omits_the_name_flag_when_unnamed(tmp_path) -> None:
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )

    command_argv = adapter.build_interactive_branch_fork_command_line(
        base_session_identifier="base-session",
        new_branch_session_identifier="branch-session",
        branch_seed_prompt_text="[branch seed]",
    )

    assert command_argv == [
        "claude",
        "--resume",
        "base-session",
        "--fork-session",
        "--session-id",
        "branch-session",
        "[branch seed]",
    ]


def test_branch_seed_is_the_last_argument_so_it_cannot_be_read_as_a_flag_value(
    tmp_path,
) -> None:
    """A seed that begins with a dash must still be the prompt, not an option."""
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )

    command_argv = adapter.build_interactive_branch_fork_command_line(
        base_session_identifier="base-session",
        new_branch_session_identifier="branch-session",
        branch_seed_prompt_text="next_action: do the thing",
        display_name="context branch",
    )

    assert command_argv[-1] == "next_action: do the thing"


def test_durability_wait_reports_false_when_the_transcript_never_appears(
    tmp_path,
) -> None:
    """A slow branch is reported, not fatal: its window is already open."""
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )

    assert (
        adapter.wait_until_session_transcript_is_durable(
            session_identifier="branch-session",
            working_directory=WORKING_DIRECTORY_UNDER_TEST,
            timeout_seconds=0.0,
        )
        is False
    )


def test_durability_wait_reports_true_once_the_transcript_exists(tmp_path) -> None:
    projects_root_directory = str(tmp_path)
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=projects_root_directory,
    )
    transcript_path = build_transcript_file_path(
        "branch-session", WORKING_DIRECTORY_UNDER_TEST, projects_root_directory
    )
    os.makedirs(os.path.dirname(transcript_path), exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        transcript_file.write("{}\n")

    assert (
        adapter.wait_until_session_transcript_is_durable(
            session_identifier="branch-session",
            working_directory=WORKING_DIRECTORY_UNDER_TEST,
            timeout_seconds=0.0,
        )
        is True
    )


def test_submission_runs_in_the_projects_working_directory(tmp_path) -> None:
    """Resuming has no directory argument, so the adapter supplies its own."""
    process_launcher = FakeNonInteractiveProcessLauncher(
        stdout_lines_to_yield=[build_result_event_line("ok")]
    )
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
        project_working_directory=WORKING_DIRECTORY_UNDER_TEST,
    )

    adapter.submit_text_to_session_and_await_acknowledgment("base-session", "text", 30.0)

    assert (
        process_launcher.recorded_launches[0].working_directory
        == WORKING_DIRECTORY_UNDER_TEST
    )


def test_availability_probe_reports_available_when_the_cli_answers(tmp_path) -> None:
    process_launcher = FakeNonInteractiveProcessLauncher(
        stdout_lines_to_yield=["1.2.3 (Claude Code)"]
    )
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
    )

    report = adapter.verify_harness_available_and_authorized()

    assert report.is_available is True
    # Authorization cannot be determined without a billable call, so the
    # adapter must decline to guess rather than claim success.
    assert report.is_authorized is None
    assert "--version" in process_launcher.recorded_launches[0].command_argv


def test_availability_probe_reports_unavailable_when_the_cli_is_missing(tmp_path) -> None:
    class MissingExecutableProcessLauncher(FakeNonInteractiveProcessLauncher):
        def stream_stdout_lines_until_exit(
            self, command_argv, stdin_text, timeout_seconds, working_directory=None
        ):
            raise FileNotFoundError("claude")
            yield  # pragma: no cover - makes this a generator function

    adapter = ClaudeCliHarnessAdapter(
        process_launcher=MissingExecutableProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )

    report = adapter.verify_harness_available_and_authorized()

    assert report.is_available is False
    assert report.is_authorized is None


def test_the_only_non_interactive_launch_is_the_base_session_update(tmp_path) -> None:
    """Where `-p` is allowed to appear, stated as an assertion rather than a comment.

    Updating the base session is the one thing nobody watches, so it is the one
    thing that may run without a terminal. Everything a user works in must come
    up as a real session, which is what this pins: if a future change reaches
    for `-p` again to make some other step tidier, this fails.
    """
    process_launcher = FakeNonInteractiveProcessLauncher(
        stdout_lines_to_yield=[build_result_event_line("ok")]
    )
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=process_launcher,
        claude_projects_root_directory=str(tmp_path),
        project_working_directory=WORKING_DIRECTORY_UNDER_TEST,
    )

    adapter.build_interactive_base_session_creation_command_line(
        new_base_session_identifier="base-session", preamble_text="preamble"
    )
    adapter.build_interactive_branch_fork_command_line(
        base_session_identifier="base-session",
        new_branch_session_identifier="branch-session",
        branch_seed_prompt_text="seed",
    )
    adapter.verify_harness_available_and_authorized()
    # Neither builder launches anything, so only the probe has run so far.
    assert all(
        "-p" not in launch.command_argv
        for launch in process_launcher.recorded_launches
    )

    adapter.submit_text_to_session_and_await_acknowledgment(
        "base-session", "handoff", 30.0
    )

    assert "-p" in process_launcher.recorded_launches[-1].command_argv


def test_adapter_offers_no_way_to_open_a_session_without_forking(tmp_path) -> None:
    adapter = ClaudeCliHarnessAdapter(
        process_launcher=FakeNonInteractiveProcessLauncher(),
        claude_projects_root_directory=str(tmp_path),
    )
    assert not hasattr(adapter, "build_interactive_resume_command_line")
