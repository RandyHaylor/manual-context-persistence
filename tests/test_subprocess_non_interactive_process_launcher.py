"""Tests for the real subprocess launcher, using trivial local processes.

These spawn python3, never the Claude CLI, so they are fast and hermetic while
still exercising the parts a fake cannot: real pipes, a real deadline, and the
stderr drain that stops a chatty child from deadlocking.
"""
from __future__ import annotations

import sys

import pytest

from context_handoff.adapters.claude_cli.non_interactive_process_launcher import (
    NonInteractiveProcessTimedOutError,
    SubprocessNonInteractiveProcessLauncher,
)

PYTHON_EXECUTABLE_PATH = sys.executable


def test_stdout_lines_are_yielded_in_order() -> None:
    launcher = SubprocessNonInteractiveProcessLauncher()
    yielded_lines = list(
        launcher.stream_stdout_lines_until_exit(
            command_argv=[
                PYTHON_EXECUTABLE_PATH,
                "-c",
                "print('first'); print('second')",
            ],
            stdin_text="",
            timeout_seconds=30.0,
        )
    )
    assert [line.rstrip("\n") for line in yielded_lines] == ["first", "second"]


def test_stdin_text_reaches_the_process() -> None:
    launcher = SubprocessNonInteractiveProcessLauncher()
    yielded_lines = list(
        launcher.stream_stdout_lines_until_exit(
            command_argv=[
                PYTHON_EXECUTABLE_PATH,
                "-c",
                "import sys; sys.stdout.write(sys.stdin.read().upper())",
            ],
            stdin_text="payload from stdin",
            timeout_seconds=30.0,
        )
    )
    assert "".join(yielded_lines) == "PAYLOAD FROM STDIN"


def test_a_process_that_never_exits_raises_a_timeout() -> None:
    launcher = SubprocessNonInteractiveProcessLauncher(poll_interval_seconds=0.05)
    with pytest.raises(NonInteractiveProcessTimedOutError):
        list(
            launcher.stream_stdout_lines_until_exit(
                command_argv=[PYTHON_EXECUTABLE_PATH, "-c", "import time; time.sleep(30)"],
                stdin_text="",
                timeout_seconds=1.0,
            )
        )


def test_lines_emitted_before_a_timeout_are_still_delivered() -> None:
    launcher = SubprocessNonInteractiveProcessLauncher(poll_interval_seconds=0.05)
    lines_received_before_timeout: list[str] = []
    with pytest.raises(NonInteractiveProcessTimedOutError):
        for line in launcher.stream_stdout_lines_until_exit(
            command_argv=[
                PYTHON_EXECUTABLE_PATH,
                "-c",
                "import sys, time; print('early'); sys.stdout.flush(); time.sleep(30)",
            ],
            stdin_text="",
            timeout_seconds=1.5,
        ):
            lines_received_before_timeout.append(line)
    assert [line.rstrip("\n") for line in lines_received_before_timeout] == ["early"]


def test_stderr_output_reaches_the_observer_and_does_not_deadlock() -> None:
    observed_events: list[tuple[str, str]] = []
    launcher = SubprocessNonInteractiveProcessLauncher(
        observe_stream_event=lambda kind, body: observed_events.append((kind, body))
    )
    # Write far more to stderr than a pipe buffer holds; a launcher that did
    # not drain stderr concurrently would hang here rather than finish.
    yielded_lines = list(
        launcher.stream_stdout_lines_until_exit(
            command_argv=[
                PYTHON_EXECUTABLE_PATH,
                "-c",
                "import sys\n"
                "for index in range(4000): sys.stderr.write('noise line %d\\n' % index)\n"
                "print('done')",
            ],
            stdin_text="",
            timeout_seconds=60.0,
        )
    )
    assert [line.rstrip("\n") for line in yielded_lines] == ["done"]
    observed_stderr_bodies = [
        body for kind, body in observed_events if kind == "STDERR_LINE"
    ]
    assert len(observed_stderr_bodies) > 1000


def test_the_launch_is_announced_to_the_observer() -> None:
    observed_events: list[tuple[str, str]] = []
    launcher = SubprocessNonInteractiveProcessLauncher(
        observe_stream_event=lambda kind, body: observed_events.append((kind, body))
    )
    list(
        launcher.stream_stdout_lines_until_exit(
            command_argv=[PYTHON_EXECUTABLE_PATH, "-c", "pass"],
            stdin_text="",
            timeout_seconds=30.0,
        )
    )
    assert any(kind == "SUBPROCESS_LAUNCH" for kind, _ in observed_events)


def test_a_missing_executable_raises_file_not_found() -> None:
    launcher = SubprocessNonInteractiveProcessLauncher()
    with pytest.raises(FileNotFoundError):
        list(
            launcher.stream_stdout_lines_until_exit(
                command_argv=["definitely-not-an-installed-executable-name"],
                stdin_text="",
                timeout_seconds=5.0,
            )
        )
