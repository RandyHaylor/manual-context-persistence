"""Ask the user whether to start a new base session or resume an existing one.

Reading and writing are injected rather than calling input() and print()
directly, which is what lets the conversation be tested with scripted answers
instead of a terminal.

Two refusals are deliberate. A blank identifier is re-asked rather than treated
as "no identifier", because falling through to creating a new base would look
like success while stranding everything the user had accumulated. And an
unrecognised answer is re-asked rather than defaulted, because guessing wrong
here is destructive in one direction and merely annoying in the other.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

CREATE_NEW_ANSWERS = frozenset({"new", "n", "create"})
RESUME_ANSWERS = frozenset({"resume", "r", "existing"})


@dataclass(frozen=True)
class BaseSessionChoice:
    should_create_new_base_session: bool
    base_session_identifier_to_resume: Optional[str]


def ask_whether_to_create_or_resume_base_session(
    read_answer: Callable[[str], str],
    write_line: Callable[[str], None],
    known_base_session_identifiers: Sequence[str] = (),
) -> BaseSessionChoice:
    """Ask until the answer is unambiguous, then return the decision.

    Propagates ``EOFError`` from ``read_answer``: a closed input stream is not
    an answer, and must never be read as consent to create a new base session.
    """
    while True:
        answer = read_answer(
            "Start a [new] base session, or [resume] an existing one? "
        ).strip().lower()
        if answer in CREATE_NEW_ANSWERS:
            return BaseSessionChoice(
                should_create_new_base_session=True,
                base_session_identifier_to_resume=None,
            )
        if answer in RESUME_ANSWERS:
            return BaseSessionChoice(
                should_create_new_base_session=False,
                base_session_identifier_to_resume=_ask_which_base_session_to_resume(
                    read_answer, write_line, known_base_session_identifiers
                ),
            )
        write_line("Please answer 'new' or 'resume'.")


def _ask_which_base_session_to_resume(
    read_answer: Callable[[str], str],
    write_line: Callable[[str], None],
    known_base_session_identifiers: Sequence[str],
) -> str:
    if known_base_session_identifiers:
        write_line("Known base sessions:")
        for offered_position, known_identifier in enumerate(
            known_base_session_identifiers, start=1
        ):
            write_line(f"  {offered_position}. {known_identifier}")

    while True:
        answer = read_answer(
            "Base session to resume (number from the list, or an identifier): "
        ).strip()
        if not answer:
            write_line("A base session identifier is required to resume.")
            continue
        # A number selects from the list, but only when it is actually in
        # range: a session identifier is opaque and could legitimately be
        # digits, so an out-of-range number is taken literally.
        if answer.isdigit():
            selected_position = int(answer)
            if 1 <= selected_position <= len(known_base_session_identifiers):
                return known_base_session_identifiers[selected_position - 1]
        return answer
