"""Live end-to-end: the real orchestrator, the real CLI, a real tmux window.

Every other test in the suite substitutes something. This one substitutes
nothing except the terminal emulator, which is replaced with a no-op so the
test can run unattended without windows appearing on screen. The tmux session
is real, the Claude sessions are real, and the rotation is the same code path
the product runs.

Opt-in through CONTEXT_HANDOFF_RUN_LIVE_CLAUDE_TESTS=1, because these make
billable calls.
"""
from __future__ import annotations

import os
import shutil
import uuid

import pytest

from context_handoff.adapters.claude_cli.claude_cli_harness_adapter import (
    ClaudeCliHarnessAdapter,
)
from context_handoff.adapters.claude_cli.claude_cli_transcript_locator import (
    DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
    build_transcript_file_path,
)
from context_handoff.adapters.claude_cli.non_interactive_process_launcher import (
    SubprocessNonInteractiveProcessLauncher,
)
from context_handoff.adapters.tmux.tmux_command_runner import SubprocessTmuxCommandRunner
from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
    TmuxUserInterfaceControlAdapter,
)
from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import ContextToKeepPackage
from context_handoff.orchestration.turn_rotation_orchestrator import (
    TurnRotationOrchestrator,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore

LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME = "CONTEXT_HANDOFF_RUN_LIVE_CLAUDE_TESTS"
LIVE_SESSION_TIMEOUT_SECONDS = 240.0

pytestmark = [
    pytest.mark.skipif(
        os.environ.get(LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME) != "1",
        reason=(
            f"live tests are opt-in; set "
            f"{LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME}=1 to run them"
        ),
    ),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed"),
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed"),
]


def count_transcript_lines(session_identifier: str, working_directory: str) -> int:
    transcript_path = build_transcript_file_path(
        session_identifier, working_directory, DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY
    )
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as transcript_file:
        return sum(1 for _ in transcript_file)


class LiveTurnLoopFixture:
    def __init__(self, project_directory: str, window_identifier: str):
        self.project_directory = project_directory
        self.window_identifier = window_identifier
        self.harness = ClaudeCliHarnessAdapter(
            process_launcher=SubprocessNonInteractiveProcessLauncher(),
            project_working_directory=project_directory,
        )
        self.user_interface_control = TmuxUserInterfaceControlAdapter(
            tmux_command_runner=SubprocessTmuxCommandRunner(),
            pane_output_log_directory=os.path.join(project_directory, "pane-logs"),
            attach_terminal_emulator=lambda _window_identifier: None,
        )
        self.context_to_keep_store = ContextToKeepFileStore(project_directory)
        self.user_prompt_log_store = UserPromptLogStore(project_directory)
        self.base_session_identifier = self._create_base_session()
        self.orchestrator = TurnRotationOrchestrator(
            harness=self.harness,
            user_interface_control=self.user_interface_control,
            context_to_keep_store=self.context_to_keep_store,
            user_prompt_log_store=self.user_prompt_log_store,
            project_directory=project_directory,
            base_session_identifier=self.base_session_identifier,
            shared_window_identifier=window_identifier,
            base_session_acknowledgment_timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
        )

    def _create_base_session(self) -> str:
        base_session_identifier = str(uuid.uuid4())
        list(
            SubprocessNonInteractiveProcessLauncher().stream_stdout_lines_until_exit(
                command_argv=[
                    "claude",
                    "-p",
                    "--session-id",
                    base_session_identifier,
                    "You are a base session that only accumulates project context. "
                    "Reply with only the word acknowledged.",
                ],
                stdin_text="",
                timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
                working_directory=self.project_directory,
            )
        )
        return base_session_identifier

    def stage_completed_turn(self, branch_session_identifier: str, prompt_text: str):
        self.user_prompt_log_store.append_user_prompt_entry(
            branch_session_identifier, prompt_text
        )
        self.context_to_keep_store.write_pending_context_to_keep_package(
            ContextToKeepPackage(
                context_to_keep=["The project codeword is WOMBAT-8842."]
            )
        )


@pytest.fixture
def live_turn_loop(tmp_path):
    project_directory = str(tmp_path / "live-project")
    os.makedirs(project_directory)
    window_identifier = f"context-handoff-live-{uuid.uuid4().hex[:8]}"
    fixture = LiveTurnLoopFixture(project_directory, window_identifier)
    try:
        yield fixture
    finally:
        fixture.user_interface_control.close_shared_window(window_identifier)


def test_live_first_branch_opens_a_real_window_and_a_real_branch(live_turn_loop) -> None:
    branch_session_identifier = live_turn_loop.orchestrator.start_first_branch_session()

    assert live_turn_loop.user_interface_control.is_shared_window_alive(
        live_turn_loop.window_identifier
    )
    assert os.path.exists(
        build_transcript_file_path(
            branch_session_identifier,
            live_turn_loop.project_directory,
            DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
        )
    )


def test_live_one_full_rotation_updates_the_base_and_reuses_the_window(
    live_turn_loop,
) -> None:
    """The whole design, exercised once against real everything."""
    first_branch = live_turn_loop.orchestrator.start_first_branch_session()
    live_turn_loop.stage_completed_turn(first_branch, "remember the codeword")
    base_line_count_before = count_transcript_lines(
        live_turn_loop.base_session_identifier, live_turn_loop.project_directory
    )

    outcome = live_turn_loop.orchestrator.rotate_to_next_branch_session()

    assert outcome.base_session_acknowledgment.timed_out is False
    assert count_transcript_lines(
        live_turn_loop.base_session_identifier, live_turn_loop.project_directory
    ) > base_line_count_before
    assert outcome.new_branch_session_identifier != first_branch
    assert live_turn_loop.user_interface_control.is_shared_window_alive(
        live_turn_loop.window_identifier
    )
    assert os.path.exists(outcome.rotated_history_path)
    assert live_turn_loop.context_to_keep_store.has_pending_context_to_keep() is False


def test_live_the_new_branch_knows_what_the_previous_turn_handed_off(
    live_turn_loop,
) -> None:
    """The claim the POC is built to prove: context survives the branch swap."""
    first_branch = live_turn_loop.orchestrator.start_first_branch_session()
    live_turn_loop.stage_completed_turn(first_branch, "remember the codeword")

    outcome = live_turn_loop.orchestrator.rotate_to_next_branch_session()

    answer = live_turn_loop.harness.submit_text_to_session_and_await_acknowledgment(
        session_identifier=outcome.new_branch_session_identifier,
        submitted_text="What is the project codeword? Reply with only the codeword.",
        acknowledgment_timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
    )

    assert "WOMBAT-8842" in answer.acknowledgment_text.upper()
