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

pytestmark = [
    pytest.mark.skipif(
        os.environ.get(LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME) != "1",
        reason=(
            f"live Claude CLI tests are opt-in; set "
            f"{LIVE_TEST_OPT_IN_ENVIRONMENT_VARIABLE_NAME}=1 to run them"
        ),
    ),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed"),
]


def count_transcript_lines(session_identifier: str, working_directory: str) -> int:
    transcript_path = build_transcript_file_path(
        session_identifier, working_directory, DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY
    )
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as transcript_file:
        return sum(1 for _ in transcript_file)


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
    """Startup's create-a-new-base path, end to end against the real CLI."""
    from context_handoff.startup.base_session_resolver import (
        resolve_base_session_for_startup,
    )

    resolved_base = resolve_base_session_for_startup(
        harness=live_adapter,
        working_directory=live_working_directory,
        base_session_identifier_to_resume=None,
    )
    assert resolved_base.was_newly_created is True

    branch = live_adapter.create_branch_session_from_base_session(
        resolved_base.session_identifier,
        live_working_directory,
        "[context-handoff branch seed] (process seed, ignore this)",
    )
    assert os.path.exists(branch.transcript_path)


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
    """The claim the whole design rests on: a fork exists on disk immediately."""
    branch = live_adapter.create_branch_session_from_base_session(
        base_session_identifier=live_base_session_identifier,
        working_directory=live_working_directory,
        branch_seed_prompt_text=(
            "[context-handoff branch seed] (process seed, ignore this)"
        ),
    )
    assert branch.session_identifier != live_base_session_identifier
    assert os.path.exists(branch.transcript_path)


def test_live_branch_inherits_the_base_session_context(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    """A fork that did not carry the base's context would make the design moot."""
    branch = live_adapter.create_branch_session_from_base_session(
        live_base_session_identifier,
        live_working_directory,
        "[context-handoff branch seed] (process seed, ignore this)",
    )

    answer = live_adapter.submit_text_to_session_and_await_acknowledgment(
        session_identifier=branch.session_identifier,
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

    live_adapter.create_branch_session_from_base_session(
        live_base_session_identifier,
        live_working_directory,
        "[context-handoff branch seed] (process seed, ignore this)",
    )

    assert (
        count_transcript_lines(live_base_session_identifier, live_working_directory)
        == line_count_before_fork
    )


def test_live_two_branches_of_one_base_are_independent(
    live_adapter, live_base_session_identifier, live_working_directory
) -> None:
    """Each turn forks the base afresh, so branches must not share state."""
    first_branch = live_adapter.create_branch_session_from_base_session(
        live_base_session_identifier,
        live_working_directory,
        "[context-handoff branch seed] (process seed, ignore this)",
    )
    live_adapter.submit_text_to_session_and_await_acknowledgment(
        first_branch.session_identifier,
        "Remember a second codeword: NARWHAL-3311. Reply with only the word acknowledged.",
        LIVE_SESSION_TIMEOUT_SECONDS,
    )

    second_branch = live_adapter.create_branch_session_from_base_session(
        live_base_session_identifier,
        live_working_directory,
        "[context-handoff branch seed] (process seed, ignore this)",
    )
    answer = live_adapter.submit_text_to_session_and_await_acknowledgment(
        second_branch.session_identifier,
        "Do you know a codeword containing the word NARWHAL? Answer only yes or no.",
        LIVE_SESSION_TIMEOUT_SECONDS,
    )

    assert "NO" in answer.acknowledgment_text.upper()
