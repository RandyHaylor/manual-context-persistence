"""Live integration tests against a real, installed, logged-in Claude CLI.

These are the only tests in the suite that make billable calls, so they are
opt-in: set CONTEXT_HANDOFF_RUN_LIVE_CLAUDE_TESTS=1 to run them. Everything else
in the suite runs against fakes.

They exist to answer the questions no fake can: does the CLI actually accept
the flags the adapter builds, does a forked session really inherit the base's
context, and is the base really left unmodified by a fork.

Each test runs in its own temporary working directory so live sessions land in
their own transcript folder and never pollute a real project's history.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
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

LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME = "CONTEXT_HANDOFF_RUN_LIVE_CLAUDE_TESTS"
LIVE_SESSION_TIMEOUT_SECONDS = 240.0

# Long enough for the CLI to have drawn whichever prompt it opens on before a
# keypress is sent at it; a key delivered to a pane that is still starting up
# lands nowhere.
TERMINAL_STARTUP_GRACE_SECONDS = 8.0

pytestmark = [
    pytest.mark.skipif(
        os.environ.get(LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME) != "1",
        reason=(
            f"live Claude CLI tests are opt-in; set "
            f"{LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME}=1 to run them"
        ),
    ),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed"),
    # A branch is only ever forked inside a terminal now, so these tests need one.
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed"),
]


def count_transcript_lines(session_identifier: str, working_directory: str) -> int:
    transcript_path = build_transcript_file_path(
        session_identifier, working_directory, DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY
    )
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as transcript_file:
        return sum(1 for _ in transcript_file)


def fork_branch_through_a_real_terminal(
    live_adapter, base_session_identifier: str, working_directory: str, seed_text: str
) -> str:
    """Fork a branch the only way the product does: in a real terminal.

    A branch is never created headlessly, so a live test cannot create one with
    a plain subprocess either — it has to run the adapter's argv inside a
    terminal, exactly as the shared window does. The workspace-trust dialog is
    answered here because an interactive launch in a directory the CLI has not
    seen before opens on that prompt and would otherwise wait forever; `-p`
    used to skip the dialog silently, which is precisely the behaviour this
    design gave up.

    Returns the branch's session identifier once its transcript is on disk.
    """
    branch_session_identifier = live_adapter.allocate_branch_session_identifier()
    command_argv = live_adapter.build_interactive_branch_fork_command_line(
        base_session_identifier=base_session_identifier,
        new_branch_session_identifier=branch_session_identifier,
        branch_seed_prompt_text=seed_text,
    )
    tmux_session_name = f"live-fork-{branch_session_identifier[:8]}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", tmux_session_name, "-c", working_directory]
        + command_argv,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        # Blind, and deliberately so: the prompt's default option is the
        # trusting one, and a directory already trusted simply receives an
        # Enter its prompt box discards.
        time.sleep(TERMINAL_STARTUP_GRACE_SECONDS)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{tmux_session_name}:0", "Enter"],
            check=True,
            capture_output=True,
            text=True,
        )
        became_durable = live_adapter.wait_until_session_transcript_is_durable(
            session_identifier=branch_session_identifier,
            working_directory=working_directory,
            timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
        )
        assert became_durable, (
            f"branch {branch_session_identifier} never appeared on disk; "
            f"pane text was:\n"
            + subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", f"{tmux_session_name}:0"],
                capture_output=True,
                text=True,
            ).stdout
        )
    finally:
        subprocess.run(
            ["tmux", "kill-session", "-t", tmux_session_name],
            capture_output=True,
            text=True,
        )
    return branch_session_identifier


@pytest.fixture
def live_working_directory(tmp_path) -> str:
    """An empty directory so live sessions get their own transcript folder."""
    live_directory = tmp_path / "live-project"
    live_directory.mkdir()
    return str(live_directory)


@pytest.fixture
def live_adapter(live_working_directory) -> ClaudeCliHarnessAdapter:
    return ClaudeCliHarnessAdapter(
        process_launcher=SubprocessNonInteractiveProcessLauncher(),
        project_working_directory=live_working_directory,
    )


@pytest.fixture
def live_base_session_identifier(live_working_directory) -> str:
    """Create a base session holding one distinctive, checkable fact.

    Built with the launcher directly rather than through the adapter: creating
    a brand-new session is a test-setup concern, not something the turn loop
    ever does.
    """
    base_session_identifier = str(uuid.uuid4())
    launcher = SubprocessNonInteractiveProcessLauncher()
    list(
        launcher.stream_stdout_lines_until_exit(
            command_argv=[
                "claude",
                "-p",
                "--session-id",
                base_session_identifier,
                "Remember this project codeword and nothing else: PLATYPUS-7714. "
                "Reply with only the word acknowledged.",
            ],
            stdin_text="",
            timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
            working_directory=live_working_directory,
        )
    )
    return base_session_identifier


def test_live_availability_probe_finds_the_installed_cli(live_adapter) -> None:
    report = live_adapter.verify_harness_available_and_authorized()
    assert report.is_available is True
    # Login state is assumed from the existing local OAuth session, never probed.
    assert report.is_authorized is None
    assert report.detail_text


def test_live_base_session_created_from_the_preamble_is_durable_and_forkable(
    live_adapter, live_working_directory
) -> None:
    """Startup's create-a-new-base path, end to end against the real CLI.

    Creation runs in a real tmux window because that is now the only way it
    runs: the base session is created interactively so its workspace-trust
    prompt can be answered, and only afterwards is it spoken to headlessly.
    """
    from context_handoff.adapters.tmux.tmux_command_runner import (
        SubprocessTmuxCommandRunner,
    )
    from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (
        TmuxUserInterfaceControlAdapter,
    )
    from context_handoff.startup.base_session_resolver import (
        resolve_base_session_for_startup,
    )

    live_window_identifier = f"live-base-{uuid.uuid4().hex[:8]}"
    user_interface_control = TmuxUserInterfaceControlAdapter(
        tmux_command_runner=SubprocessTmuxCommandRunner(),
        pane_output_log_directory=os.path.join(live_working_directory, "pane-logs"),
        # No window on screen: this runs unattended.
        attach_terminal_emulator=lambda _window_identifier: None,
    )
    try:
        resolved_base = resolve_base_session_for_startup(
            harness=live_adapter,
            user_interface_control=user_interface_control,
            working_directory=live_working_directory,
            build_shared_window_identifier=lambda _base: live_window_identifier,
            base_session_identifier_to_resume=None,
        )
        assert resolved_base.was_newly_created is True
        assert resolved_base.shared_window_identifier == live_window_identifier
    finally:
        user_interface_control.close_shared_window(live_window_identifier)

    branch_session_identifier = fork_branch_through_a_real_terminal(
        live_adapter,
        resolved_base.session_identifier,
        live_working_directory,
        "Reply with only the word acknowledged.",
    )
    assert os.path.exists(
        build_transcript_file_path(
            branch_session_identifier,
            live_working_directory,
            DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
        )
    )


def test_live_base_session_transcript_exists_after_creation(
    live_base_session_identifier, live_working_directory
) -> None:
    transcript_path = build_transcript_file_path(
        live_base_session_identifier,
        live_working_directory,
        DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
    )
    assert os.path.exists(transcript_path)


def test_live_submission_to_a_session_returns_an_acknowledgment(
    live_adapter, live_base_session_identifier
) -> None:
    acknowledgment = live_adapter.submit_text_to_session_and_await_acknowledgment(
        session_identifier=live_base_session_identifier,
        submitted_text=(
            "Handoff: the user asked for adapter boundaries. "
            "Acknowledge receipt in one short sentence and do nothing else."
        ),
        acknowledgment_timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
    )
    assert acknowledgment.timed_out is False
    assert acknowledgment.acknowledgment_text.strip()


def test_live_successive_submissions_accumulate_in_the_base_transcript(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    line_count_before = count_transcript_lines(
        live_base_session_identifier, live_working_directory
    )

    live_adapter.submit_text_to_session_and_await_acknowledgment(
        live_base_session_identifier,
        "Handoff one. Acknowledge in one short sentence and do nothing else.",
        LIVE_SESSION_TIMEOUT_SECONDS,
    )
    line_count_after_first = count_transcript_lines(
        live_base_session_identifier, live_working_directory
    )
    live_adapter.submit_text_to_session_and_await_acknowledgment(
        live_base_session_identifier,
        "Handoff two. Acknowledge in one short sentence and do nothing else.",
        LIVE_SESSION_TIMEOUT_SECONDS,
    )
    line_count_after_second = count_transcript_lines(
        live_base_session_identifier, live_working_directory
    )

    assert line_count_before < line_count_after_first < line_count_after_second


def test_live_branch_creation_produces_a_durable_transcript(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    """A fork reaches disk once its own visible turn has answered the seed."""
    branch_session_identifier = fork_branch_through_a_real_terminal(
        live_adapter,
        live_base_session_identifier,
        live_working_directory,
        "Reply with only the word acknowledged.",
    )
    assert branch_session_identifier != live_base_session_identifier
    assert os.path.exists(
        build_transcript_file_path(
            branch_session_identifier,
            live_working_directory,
            DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
        )
    )


def test_live_branch_inherits_the_base_session_context(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    """A fork that did not carry the base's context would make the design moot."""
    branch_session_identifier = fork_branch_through_a_real_terminal(
        live_adapter,
        live_base_session_identifier,
        live_working_directory,
        "Reply with only the word acknowledged.",
    )

    answer = live_adapter.submit_text_to_session_and_await_acknowledgment(
        session_identifier=branch_session_identifier,
        submitted_text=(
            "What is the project codeword you were told to remember? "
            "Reply with only the codeword."
        ),
        acknowledgment_timeout_seconds=LIVE_SESSION_TIMEOUT_SECONDS,
    )

    assert "PLATYPUS-7714" in answer.acknowledgment_text.upper()


def test_live_forking_leaves_the_base_session_unmodified(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    """If a fork appended to the base, the base would grow with every turn."""
    line_count_before_fork = count_transcript_lines(
        live_base_session_identifier, live_working_directory
    )

    fork_branch_through_a_real_terminal(
        live_adapter,
        live_base_session_identifier,
        live_working_directory,
        "Reply with only the word acknowledged.",
    )

    assert (
        count_transcript_lines(live_base_session_identifier, live_working_directory)
        == line_count_before_fork
    )


def test_live_two_branches_of_one_base_are_independent(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    """Each turn forks the base afresh, so branches must not share state."""
    first_branch_session_identifier = fork_branch_through_a_real_terminal(
        live_adapter,
        live_base_session_identifier,
        live_working_directory,
        "Reply with only the word acknowledged.",
    )
    live_adapter.submit_text_to_session_and_await_acknowledgment(
        first_branch_session_identifier,
        "Remember a second codeword: NARWHAL-3311. Reply with only the word acknowledged.",
        LIVE_SESSION_TIMEOUT_SECONDS,
    )

    second_branch_session_identifier = fork_branch_through_a_real_terminal(
        live_adapter,
        live_base_session_identifier,
        live_working_directory,
        "Reply with only the word acknowledged.",
    )
    answer = live_adapter.submit_text_to_session_and_await_acknowledgment(
        second_branch_session_identifier,
        "Do you know a codeword containing the word NARWHAL? Answer only yes or no.",
        LIVE_SESSION_TIMEOUT_SECONDS,
    )

    assert "NO" in answer.acknowledgment_text.upper()
