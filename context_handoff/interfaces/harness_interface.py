"""Abstract interface for the AI coding harness that owns sessions and transcripts.

The context-handoff core depends only on this interface. Claude CLI is the first
concrete implementation; another harness may replace it without the core
changing. No method name, argument, or return value here may reference a Claude
CLI flag, subcommand, or on-disk layout.

Authentication assumption (POC scope): the harness is already installed on the
machine and the user is already logged in through the harness's own local OAuth
flow. This interface therefore exposes a read-only availability probe
(``verify_harness_available_and_authorized``) and deliberately exposes NO
login, token, or credential-management operation. Implementations must never
prompt for credentials or write credential state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class HarnessAvailabilityReport:
    """Result of the pre-flight probe run before the turn loop starts.

    ``is_available`` means the harness executable was found and answered a
    trivial version-style query. ``is_authorized`` means the harness reports an
    existing local OAuth login; an implementation that cannot distinguish
    "installed" from "logged in" without side effects must set this to None
    rather than guessing.
    """

    is_available: bool
    is_authorized: Optional[bool]
    detail_text: str


# There is no SessionCreationResult any more. Nothing in this interface creates
# a session: every session is now brought into being by a command run in a
# window, so what a caller gets back is an identifier to watch for rather than a
# finished session to use. Durability is asked about separately, and answered
# with a plain yes or no.


@dataclass(frozen=True)
class SessionAcknowledgment:
    """Reply from a non-interactive submission to a session.

    ``timed_out`` is True when the harness gave no final response inside the
    caller's timeout. ``acknowledgment_text`` then holds whatever partial text
    arrived, so a timeout is diagnosable rather than silent.
    """

    acknowledgment_text: str
    timed_out: bool


class HarnessInterface(ABC):
    """Session lifecycle operations the context-handoff turn loop requires."""

    @abstractmethod
    def verify_harness_available_and_authorized(self) -> HarnessAvailabilityReport:
        """Probe that the harness is installed and already logged in.

        Must be read-only: no login prompt, no credential write, no session
        creation.
        """

    @abstractmethod
    def find_active_session_identifier_for_working_directory(
        self, working_directory: str
    ) -> str:
        """Return the identifier of the session currently running for a directory.

        Raises ``LookupError`` when no session can be attributed to the
        directory.
        """

    @abstractmethod
    def read_session_display_name(
        self, session_identifier: str, working_directory: str
    ) -> Optional[str]:
        """Return the human-facing name shown for a session, or None if unset."""

    @abstractmethod
    def allocate_base_session_identifier(self) -> str:
        """Reserve an identifier for a base session not yet created.

        Same reason as the branch equivalent: the base session is brought into
        being by a command run in a window, so its identifier must exist before
        that command can be built.
        """

    @abstractmethod
    def build_interactive_base_session_creation_command_line(
        self,
        new_base_session_identifier: str,
        preamble_text: str,
        display_name: Optional[str] = None,
    ) -> list[str]:
        """Return the argv that creates the base session interactively.

        The base session is the one session that afterwards runs entirely
        without a terminal — but it is created with one, because a harness whose
        first run in a directory opens a safety prompt can only be answered
        through a window. Creating it non-interactively skips that prompt
        instead of answering it, leaving every later interactive launch to
        stop on it.
        """

    @abstractmethod
    def allocate_branch_session_identifier(self) -> str:
        """Reserve an identifier for a branch that has not been created yet.

        Exists because the branch is brought into being by the command the user
        watches run, so its identifier has to be known before that command is
        built. No session is created and nothing is written by this call.
        """

    @abstractmethod
    def build_interactive_branch_fork_command_line(
        self,
        base_session_identifier: str,
        new_branch_session_identifier: str,
        branch_seed_prompt_text: str,
        display_name: Optional[str] = None,
    ) -> list[str]:
        """Return the argv that forks a branch AND opens it for the user.

        One command, not two: the fork is created by the same invocation the
        user sees running in their window. Splitting creation from opening is
        what produced a branch that had already taken its turn before the user
        could look at it, so implementations must not create the session ahead
        of time.

        Implementations must not run the branch non-interactively. The branch is
        the session the user works in; only the base session is ever driven
        without a terminal.
        """

    @abstractmethod
    def wait_until_session_transcript_is_durable(
        self,
        session_identifier: str,
        working_directory: str,
        timeout_seconds: float,
    ) -> bool:
        """Wait for a session to exist on disk, reporting whether it arrived.

        A forked session is not written to disk until it has content, and the
        content now arrives from an interactive window rather than from a call
        this process controls — so durability can only be observed, never
        awaited inline. Returns False on timeout rather than raising: the window
        is already open and the user can still use it.
        """

    @abstractmethod
    def submit_text_to_session_and_await_acknowledgment(
        self,
        session_identifier: str,
        submitted_text: str,
        acknowledgment_timeout_seconds: float,
    ) -> SessionAcknowledgment:
        """Send text to a session non-interactively and wait for its reply.

        Used to append handoff material to the base session. The caller is
        responsible for instructing the agent to acknowledge only; this method
        does not add such an instruction itself.
        """

    # There is deliberately no "open an existing session interactively" method.
    # Having one is what allowed a branch to be created by one call and opened
    # by a later one; the only way to open a branch is to fork it, above.
