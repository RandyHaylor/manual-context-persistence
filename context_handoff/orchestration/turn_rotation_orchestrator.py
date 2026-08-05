"""The turn loop: branch, capture, hand off to the base, branch again.

This module is the reason the interfaces exist. It coordinates a harness and a
user-interface window without knowing what either one is, so the whole loop can
be exercised in tests with no Claude CLI process and no terminal.

One shape is load-bearing and easy to get wrong: every branch forks the BASE
session, never the previous branch. Chaining branch off branch would carry each
turn's full transcript into the next and undo the compactness the design exists
to provide.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Optional

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.interfaces.harness_interface import (
    HarnessInterface,
    SessionAcknowledgment,
)
from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore

from .branch_session_preamble import (
    FIRST_BRANCH_SESSION_PREAMBLE_TEXT,
    build_rotated_branch_session_preamble_text,
)
from .handoff_message_composer import compose_handoff_message_for_base_session

# One interrupt cancels the agent's current turn; a second exits the session.
INTERRUPT_REPEAT_COUNT_FOR_SESSION_SWAP = 2

SHARED_WINDOW_STATUS_TEXT_WHILE_UPDATING_BASE = "updating base session..."

DEFAULT_BASE_SESSION_ACKNOWLEDGMENT_TIMEOUT_SECONDS = 180.0

# Generous, because what it waits on is a person's session answering its seed in
# a terminal, not a call this process drives. Exceeding it is reported, not
# fatal — see _launch_new_branch_session_in_shared_window.
DEFAULT_BRANCH_DURABILITY_TIMEOUT_SECONDS = 180.0



class NoPendingHandoffError(RuntimeError):
    """Rotation was requested with no context-to-keep waiting.

    Raised rather than rotating anyway: a rotation with nothing to hand off
    would tear down the user's session and give the base session nothing in
    return.
    """


@dataclass(frozen=True)
class TurnRotationOutcome:
    new_branch_session_identifier: str
    base_session_acknowledgment: SessionAcknowledgment
    rotated_history_path: str
    forwarded_user_prompt_count: int


class TurnRotationOrchestrator:
    def __init__(
        self,
        harness: HarnessInterface,
        user_interface_control: UserInterfaceControlInterface,
        context_to_keep_store: ContextToKeepFileStore,
        user_prompt_log_store: UserPromptLogStore,
        project_directory: str,
        base_session_identifier: str,
        shared_window_identifier: str,
        base_session_acknowledgment_timeout_seconds: float = (
            DEFAULT_BASE_SESSION_ACKNOWLEDGMENT_TIMEOUT_SECONDS
        ),
        branch_durability_timeout_seconds: float = (
            DEFAULT_BRANCH_DURABILITY_TIMEOUT_SECONDS
        ),
        first_branch_session_preamble_text: str = FIRST_BRANCH_SESSION_PREAMBLE_TEXT,
        build_rotated_branch_session_preamble_text: Callable[[str], str] = (
            build_rotated_branch_session_preamble_text
        ),
    ) -> None:
        self._harness = harness
        self._user_interface_control = user_interface_control
        self._context_to_keep_store = context_to_keep_store
        self._user_prompt_log_store = user_prompt_log_store
        self._project_directory = project_directory
        self._base_session_identifier = base_session_identifier
        self._shared_window_identifier = shared_window_identifier
        self._base_session_acknowledgment_timeout_seconds = (
            base_session_acknowledgment_timeout_seconds
        )
        self._branch_durability_timeout_seconds = branch_durability_timeout_seconds
        # Injected rather than read here: whether a commit is required is a
        # settings decision, and orchestration only needs the finished text.
        #
        # Two of them, because the first session of a run is the only one opened
        # before the user has said anything. Every later one is opened because
        # they spoke and work was done, so it must not ask for instructions.
        #
        # The rotation one is a builder rather than a string: its text depends on
        # the task named by the session being replaced, so it cannot be settled
        # until the rotation happens.
        self._first_branch_session_preamble_text = first_branch_session_preamble_text
        self._build_rotated_branch_session_preamble_text = (
            build_rotated_branch_session_preamble_text
        )
        self._current_branch_session_identifier: Optional[str] = None
        self._branch_ordinal_counter = itertools.count(1)
        self._user_facing_session_registry = UserFacingSessionRegistry(
            project_directory
        )

    @property
    def current_branch_session_identifier(self) -> Optional[str]:
        return self._current_branch_session_identifier

    @property
    def base_session_identifier(self) -> str:
        return self._base_session_identifier

    def has_pending_handoff(self) -> bool:
        return self._context_to_keep_store.has_pending_context_to_keep()

    def _launch_new_branch_session_in_shared_window(
        self, branch_seed_prompt_text: str
    ) -> str:
        """Fork the branch by opening it, in one command, in the user's window.

        The branch is never created before this runs. An earlier shape created
        it non-interactively and then opened a second command on the result,
        which meant the branch had already spent its turn by the time the user
        could see it — the window was a corpse. Non-interactive mode belongs to
        the base session alone.
        """
        branch_session_identifier = self._harness.allocate_branch_session_identifier()

        # Recorded before the window runs, and marked as being seeded until the
        # branch is on disk. The branch answers the seed, and with a task in
        # that seed the answer is the first turn of real work — so waiting for
        # durability before recording it would throw that handoff away. Marking
        # it as being seeded is what still keeps the orchestrator's own words
        # out of the prompt log.
        self._user_facing_session_registry.begin_seeding_user_facing_session(
            branch_session_identifier
        )

        branch_ordinal = next(self._branch_ordinal_counter)
        branch_command_line_argv = (
            self._harness.build_interactive_branch_fork_command_line(
                base_session_identifier=self._base_session_identifier,
                new_branch_session_identifier=branch_session_identifier,
                branch_seed_prompt_text=branch_seed_prompt_text,
                display_name=f"context handoff branch {branch_ordinal}",
            )
        )
        self._user_interface_control.run_command_line_in_shared_window(
            self._shared_window_identifier, branch_command_line_argv
        )

        # Observed, not awaited, and a timeout is not fatal: the window is
        # already open and usable, so a branch that is slow to write itself to
        # disk is a reporting problem rather than a reason to tear anything
        # down. Rotation needs the transcript, not this call, to have succeeded.
        self._harness.wait_until_session_transcript_is_durable(
            session_identifier=branch_session_identifier,
            working_directory=self._project_directory,
            timeout_seconds=self._branch_durability_timeout_seconds,
        )
        self._user_facing_session_registry.finish_seeding_user_facing_session(
            branch_session_identifier
        )

        self._current_branch_session_identifier = branch_session_identifier
        return branch_session_identifier

    def start_first_branch_session(self) -> str:
        """Open the shared window and run the first branch inside it."""
        self._user_interface_control.open_shared_window(
            self._shared_window_identifier, self._project_directory
        )
        return self._launch_new_branch_session_in_shared_window(
            self._first_branch_session_preamble_text
        )

    def rotate_to_next_branch_session(self) -> TurnRotationOutcome:
        """Perform one full rotation: interrupt, hand off, relaunch.

        The window is never closed and never replaced; the user keeps the same
        window across every turn.

        The session being interrupted here is always idle, and that is worth
        stating because it is not obvious from this method alone. A rotation
        happens only when a context-to-keep is pending; a context-to-keep is
        written only by the Stop hook; and the Stop hook fires only when the
        agent has finished replying. So by the time this runs, the branch is
        sitting at its prompt with nothing in flight, which is the case where a
        single pair of interrupts exits it.

        Two consequences, both easy to get wrong:

        - Nothing here needs to fight a session that is still working. If you
          find yourself designing escalating interrupts or retry loops, check
          first whether you have reproduced a situation the rotation path can
          actually reach. Interrupting on any signal other than Stop — the
          branch's transcript merely appearing on disk, for instance — creates a
          busy session artificially, and that is a property of the test, not of
          this code.
        - The window's own state cannot substitute for the Stop signal. A pane
          reports which program is running, not whether that program is busy;
          an agent generating a reply and an agent waiting for input are the
          same process. Only the Stop hook distinguishes them.
        """
        pending_package = (
            self._context_to_keep_store.read_pending_context_to_keep_package()
        )
        if pending_package is None:
            raise NoPendingHandoffError(
                "rotation requires a pending context-to-keep package at "
                f"{self._context_to_keep_store.context_to_keep_file_path}"
            )

        unconsumed_prompt_entries = (
            self._user_prompt_log_store.read_all_unconsumed_entries()
        )

        # Interrupt before anything is typed: a status line sent into a busy
        # pane is consumed by the running program instead of being shown.
        self._user_interface_control.send_interrupt_to_shared_window(
            self._shared_window_identifier,
            interrupt_repeat_count=INTERRUPT_REPEAT_COUNT_FOR_SESSION_SWAP,
        )
        self._user_interface_control.display_status_line_in_shared_window(
            self._shared_window_identifier,
            SHARED_WINDOW_STATUS_TEXT_WHILE_UPDATING_BASE,
        )

        handoff_message = compose_handoff_message_for_base_session(
            user_prompt_entries=unconsumed_prompt_entries,
            context_to_keep_package=pending_package,
        )
        base_session_acknowledgment = (
            self._harness.submit_text_to_session_and_await_acknowledgment(
                session_identifier=self._base_session_identifier,
                submitted_text=handoff_message,
                acknowledgment_timeout_seconds=(
                    self._base_session_acknowledgment_timeout_seconds
                ),
            )
        )

        # The handoff has been delivered, so the material is retired even when
        # the acknowledgment timed out. Resending it would duplicate context in
        # the base session, which is worse than losing the confirmation.
        self._user_prompt_log_store.mark_entries_consumed(
            entry.entry_identifier for entry in unconsumed_prompt_entries
        )
        rotated_history_path = (
            self._context_to_keep_store.rotate_pending_context_to_keep_into_history()
        )

        # The rotation text, not the first-session text: the user has spoken and
        # work has been done, so this session is given the task the previous one
        # named rather than being told to ask for instructions. The package is
        # still held here, so retiring the file above does not lose the task.
        new_branch_session_identifier = self._launch_new_branch_session_in_shared_window(
            self._build_rotated_branch_session_preamble_text(pending_package.next_action)
        )

        return TurnRotationOutcome(
            new_branch_session_identifier=new_branch_session_identifier,
            base_session_acknowledgment=base_session_acknowledgment,
            rotated_history_path=rotated_history_path,
            forwarded_user_prompt_count=len(unconsumed_prompt_entries),
        )
