"""Decide which base session a run uses: resume a named one, or create one.

Asking the user which they want is a front-end concern and lives outside this
module. What is kept here is the part with consequences — the preamble a new
base session is seeded with, and the refusal to treat a blank identifier as
"no identifier", which would quietly abandon a user's accumulated context and
start over.

Creating one takes a window, which is why this module knows about one at all.
The base session spends the rest of the run being driven with no terminal, but
it cannot be *born* that way: a harness running somewhere for the first time
opens a safety prompt, and non-interactive mode skips that prompt instead of
answering it — leaving it to ambush the first branch launch instead. So the base
is created in the shared window, its prompt is answered there, and it is then
interrupted out of, which is also what leaves the window free for the first
branch.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from context_handoff.interfaces.harness_interface import HarnessInterface
from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)

# The closing sentence exists because of what the seed itself is: a message,
# which the session answers. Without it the session treats the seed as a request
# it cannot find, and replies asking what the user wants.
BASE_SESSION_PREAMBLE_TEXT = (
    "You'll receive a history of user messages and agent work notes. "
    "Factor these in when you work. Stand by to receive."
)


BASE_SESSION_DISPLAY_NAME = "context handoff base"

# Long enough for the harness to have drawn whatever it opens with before a key
# is aimed at it.
WINDOW_STARTUP_GRACE_SECONDS_BEFORE_CONFIRMING = 8.0

DEFAULT_BASE_SESSION_DURABILITY_TIMEOUT_SECONDS = 240.0

# The same two as a branch swap: one cancels the turn, a second leaves.
INTERRUPT_REPEAT_COUNT_TO_LEAVE_BASE_SESSION = 2


class BaseSessionNotDurableError(RuntimeError):
    """The base session never reached disk, so nothing can be forked from it.

    Fatal, unlike the branch equivalent: a branch that is slow to materialize
    still leaves the user a usable window, whereas without a base session there
    is nothing for any branch to inherit and no run to have.
    """


@dataclass(frozen=True)
class ResolvedBaseSession:
    session_identifier: str
    was_newly_created: bool
    shared_window_identifier: str


def resolve_base_session_for_startup(
    harness: HarnessInterface,
    user_interface_control: UserInterfaceControlInterface,
    working_directory: str,
    build_shared_window_identifier: Callable[[str], str],
    base_session_identifier_to_resume: Optional[str],
    base_session_durability_timeout_seconds: float = (
        DEFAULT_BASE_SESSION_DURABILITY_TIMEOUT_SECONDS
    ),
    sleep_for_seconds: Callable[[float], None] = time.sleep,
) -> ResolvedBaseSession:
    """Return the base session to use, creating one only when asked to.

    Raises ``ValueError`` on a blank-but-present identifier rather than falling
    back to creating a new base: that fallback would look like success while
    losing every handoff the user had accumulated.

    The window identifier is built here rather than passed in because the two
    are entangled: a run's window is named after its base session, and creating
    a base session now requires a window to create it in — so whichever of them
    is decided first has to decide the other. ``build_shared_window_identifier``
    keeps the naming rule itself outside this module.

    Resuming opens no window. Only creation needs one.
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
            shared_window_identifier=build_shared_window_identifier(
                base_session_identifier_to_resume
            ),
        )

    base_session_identifier = harness.allocate_base_session_identifier()
    shared_window_identifier = build_shared_window_identifier(base_session_identifier)
    user_interface_control.open_shared_window(shared_window_identifier, working_directory)
    user_interface_control.run_command_line_in_shared_window(
        shared_window_identifier,
        harness.build_interactive_base_session_creation_command_line(
            new_base_session_identifier=base_session_identifier,
            preamble_text=BASE_SESSION_PREAMBLE_TEXT,
            display_name=BASE_SESSION_DISPLAY_NAME,
        ),
    )

    # A key sent at a program that has not finished drawing lands nowhere, so
    # the wait comes first. It is sent whether or not a prompt is open: a
    # session with none discards it.
    sleep_for_seconds(WINDOW_STARTUP_GRACE_SECONDS_BEFORE_CONFIRMING)
    user_interface_control.send_confirmation_keypress_to_shared_window(
        shared_window_identifier
    )

    base_became_durable = harness.wait_until_session_transcript_is_durable(
        session_identifier=base_session_identifier,
        working_directory=working_directory,
        timeout_seconds=base_session_durability_timeout_seconds,
    )
    if not base_became_durable:
        raise BaseSessionNotDurableError(
            f"base session {base_session_identifier} never appeared on disk in "
            f"{base_session_durability_timeout_seconds}s; the window may still be "
            "waiting on a prompt"
        )

    # Interrupted, not left running: from here the base is only ever spoken to
    # without a terminal, and the window is needed for the first branch.
    user_interface_control.send_interrupt_to_shared_window(
        shared_window_identifier,
        interrupt_repeat_count=INTERRUPT_REPEAT_COUNT_TO_LEAVE_BASE_SESSION,
    )
    return ResolvedBaseSession(
        session_identifier=base_session_identifier,
        was_newly_created=True,
        shared_window_identifier=shared_window_identifier,
    )
