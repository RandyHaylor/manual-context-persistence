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


@dataclass(frozen=True)
class SessionCreationResult:
    """A session that is guaranteed durable on disk when returned.

    Returned by every operation that brings a session into existence — a base
    session created from a preamble, or a branch forked from a base — because
    callers need the same two things from all of them.

    ``transcript_path`` is an opaque location owned by the harness; the core
    treats it as a token to hand back to the harness, never as something to
    parse.
    """

    session_identifier: str
    transcript_path: str


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
    def create_base_session_with_preamble(
        self, working_directory: str, preamble_text: str
    ) -> SessionCreationResult:
        """Create a brand-new session seeded with the base-session preamble.

        Used once at startup when the user is not resuming an existing base.
        The returned session must be fully durable on disk before this method
        returns, so a branch can immediately be forked from it.
        """

    @abstractmethod
    def create_branch_session_from_base_session(
        self,
        base_session_identifier: str,
        working_directory: str,
        branch_seed_prompt_text: str,
        announce_branch_session_identifier: Optional[Callable[[str], None]] = None,
    ) -> SessionCreationResult:
        """Fork a new branch session that inherits the base session's context.

        The base session must be left unmodified. The returned branch must be
        fully durable on disk before this method returns, so a caller may
        immediately resume it or fork from it.

        ``announce_branch_session_identifier`` is called with the new session's
        identifier before the seed is sent, and must be honoured by every
        implementation. The seeded session answers the seed, and that reply is
        the first turn of real work — so a caller that can only learn the
        identifier from the return value learns it one turn too late.
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

    @abstractmethod
    def build_interactive_resume_command_line(
        self, session_identifier: str, display_name: Optional[str] = None
    ) -> list[str]:
        """Return the argv that opens a session interactively for the user.

        This is the seam that keeps the user-interface layer harness-agnostic:
        the harness knows how to phrase the command, the user-interface control
        layer only knows how to run an opaque argv inside a window.
        """
