"""Decide which base session a run uses: resume a named one, or create one.

Asking the user which they want is a front-end concern and lives outside this
module. What is kept here is the part with consequences — the preamble a new
base session is seeded with, and the refusal to treat a blank identifier as
"no identifier", which would quietly abandon a user's accumulated context and
start over.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from context_handoff.interfaces.harness_interface import HarnessInterface

BASE_SESSION_PREAMBLE_TEXT = (
    "You are the base session for a context-handoff project. You will receive "
    "handoff messages describing work done in short-lived branch sessions, each "
    "containing the user's verbatim words and a summary of what was done.\n\n"
    "Your only job is to accumulate that context. For every handoff, acknowledge "
    "receipt in one short sentence. Do not act on handoffs, do not use tools, and "
    "do not answer the user prompts they quote — that work has already been done "
    "elsewhere.\n\n"
    "Acknowledge this preamble in one short sentence."
)


@dataclass(frozen=True)
class ResolvedBaseSession:
    session_identifier: str
    was_newly_created: bool


def resolve_base_session_for_startup(
    harness: HarnessInterface,
    working_directory: str,
    base_session_identifier_to_resume: Optional[str],
) -> ResolvedBaseSession:
    """Return the base session to use, creating one only when asked to.

    Raises ``ValueError`` on a blank-but-present identifier rather than falling
    back to creating a new base: that fallback would look like success while
    losing every handoff the user had accumulated.
    """
    if base_session_identifier_to_resume is not None:
        if not base_session_identifier_to_resume.strip():
            raise ValueError(
                "base_session_identifier_to_resume was blank; pass None to create a "
                "new base session, or a real identifier to resume one"
            )
        return ResolvedBaseSession(
            session_identifier=base_session_identifier_to_resume,
            was_newly_created=False,
        )

    creation_result = harness.create_base_session_with_preamble(
        working_directory=working_directory,
        preamble_text=BASE_SESSION_PREAMBLE_TEXT,
    )
    return ResolvedBaseSession(
        session_identifier=creation_result.session_identifier,
        was_newly_created=True,
    )
