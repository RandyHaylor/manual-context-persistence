"""Process-launch seam used by the Claude CLI adapter.

Kept behind an interface for one reason: it is the only part of the adapter
that cannot run in a unit test. Everything above it — argv construction, stream
parsing, durability checking — is testable against a fake launcher.

The real implementation streams stdout line by line with a wall-clock deadline
and drains stderr on a background thread, because a child whose stderr pipe
fills will deadlock rather than exit.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Iterator, Optional

STREAM_EVENT_KIND_SUBPROCESS_LAUNCH = "SUBPROCESS_LAUNCH"
STREAM_EVENT_KIND_STDERR_LINE = "STDERR_LINE"
STREAM_EVENT_KIND_TIMEOUT = "TIMEOUT"


class NonInteractiveProcessTimedOutError(Exception):
    """Raised mid-iteration when a launched process outlived its deadline.

    The process is killed before this is raised. Lines already yielded remain
    valid, so a caller that buffers as it iterates keeps the partial output.
    """


class NonInteractiveProcessLauncherInterface(ABC):
    @abstractmethod
    def stream_stdout_lines_until_exit(
        self,
        command_argv: list[str],
        stdin_text: str,
        timeout_seconds: float,
        working_directory: Optional[str] = None,
    ) -> Iterator[str]:
        """Run a process and yield its stdout lines as they arrive.

        ``working_directory`` is where the process runs. It matters because the
        harness keys a session's transcript to the directory it was launched
        from, so a caller that asks about one directory while the child runs in
        another will not find the transcript it just created.

        Raises ``NonInteractiveProcessTimedOutError`` if the process has not
        exited by the deadline.
        """


class SubprocessNonInteractiveProcessLauncher(NonInteractiveProcessLauncherInterface):
    def __init__(
        self,
        observe_stream_event: Optional[Callable[[str, str], None]] = None,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self._observe_stream_event = observe_stream_event
        self._poll_interval_seconds = poll_interval_seconds

    def _emit_observed_event(self, event_kind: str, event_body_text: str) -> None:
        if self._observe_stream_event is None:
            return
        try:
            self._observe_stream_event(event_kind, event_body_text)
        except Exception:
            pass

    def _drain_stderr_into_observer_until_eof(self, stderr_handle) -> None:
        if stderr_handle is None:
            return
        try:
            for line in iter(stderr_handle.readline, ""):
                stripped_line = line.rstrip("\n")
                if stripped_line:
                    self._emit_observed_event(
                        STREAM_EVENT_KIND_STDERR_LINE, stripped_line
                    )
        except Exception:
            pass

    def stream_stdout_lines_until_exit(
        self,
        command_argv: list[str],
        stdin_text: str,
        timeout_seconds: float,
        working_directory: Optional[str] = None,
    ) -> Iterator[str]:
        self._emit_observed_event(
            STREAM_EVENT_KIND_SUBPROCESS_LAUNCH,
            f"argv={command_argv} stdin_chars={len(stdin_text)} "
            f"timeout_seconds={timeout_seconds} working_directory={working_directory}",
        )
        process_handle = subprocess.Popen(
            command_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=working_directory,
        )

        try:
            assert process_handle.stdin is not None
            process_handle.stdin.write(stdin_text)
            process_handle.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        stderr_drainer_thread = threading.Thread(
            target=self._drain_stderr_into_observer_until_eof,
            args=(process_handle.stderr,),
            daemon=True,
        )
        stderr_drainer_thread.start()

        # A reader thread plus a polled queue, rather than a blocking read, so
        # the deadline is enforced even when the child goes silent. select() on
        # pipes would not be portable to Windows.
        stdout_line_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        STDOUT_EXHAUSTED_SENTINEL = None

        def read_stdout_lines_into_queue() -> None:
            try:
                assert process_handle.stdout is not None
                for line in iter(process_handle.stdout.readline, ""):
                    stdout_line_queue.put(line)
            finally:
                stdout_line_queue.put(STDOUT_EXHAUSTED_SENTINEL)

        stdout_reader_thread = threading.Thread(
            target=read_stdout_lines_into_queue, daemon=True
        )
        stdout_reader_thread.start()

        deadline_monotonic_seconds = time.monotonic() + timeout_seconds
        try:
            while True:
                if time.monotonic() > deadline_monotonic_seconds:
                    self._emit_observed_event(
                        STREAM_EVENT_KIND_TIMEOUT,
                        f"killing process after {timeout_seconds}s: {command_argv}",
                    )
                    process_handle.kill()
                    raise NonInteractiveProcessTimedOutError(
                        f"process exceeded {timeout_seconds}s: {command_argv}"
                    )
                try:
                    queued_line = stdout_line_queue.get(
                        timeout=self._poll_interval_seconds
                    )
                except queue.Empty:
                    continue
                if queued_line is STDOUT_EXHAUSTED_SENTINEL:
                    break
                yield queued_line
        finally:
            if process_handle.poll() is None:
                try:
                    process_handle.kill()
                except OSError:
                    pass
            stderr_drainer_thread.join(timeout=2.0)
            stdout_reader_thread.join(timeout=2.0)
