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

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
)
from context_handoff.interfaces.harness_interface import HarnessInterface

BASE_SESSION_PREAMBLE_TEXT = (
    "This session carries a project's context across short-lived sessions.\n\n"
    "When you are resumed to receive a handoff, acknowledge it in one short "
    "sentence and do nothing else.\n\n"
    "When you are forked to work with the user, do the work they ask for, then "
    "end the turn with one block:\n\n"
    f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
    "{\n"
    f'  "context_to_keep_version": {CONTEXT_TO_KEEP_PACKAGE_VERSION},\n'
    '  "summary_of_work_completed_this_turn": "What this turn did.",\n'
    '  "context_to_carry_forward": ["Something the next session needs."]\n'
    "}\n"
    "```\n\n"
    "Carry decisions and constraints. Do not carry anything the next session "
    "could get by reading the files, do not restate what a check confirmed, and "
    "do not mention what was not asked for. An empty list is usually right.\n\n"
    "Acknowledge this in one short sentence."
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
