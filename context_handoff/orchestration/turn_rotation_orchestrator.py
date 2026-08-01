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
        # Recorded before the seed is sent, and marked as being seeded while it
        # is. The session answers the seed, and with a task in that seed the
        # answer is the first turn of real work — so waiting until the call
        # returns would throw that handoff away. Marking it as being seeded is
        # what still keeps the orchestrator's own words out of the prompt log.
        branch_creation_result = self._harness.create_branch_session_from_base_session(
            base_session_identifier=self._base_session_identifier,
            working_directory=self._project_directory,
            branch_seed_prompt_text=branch_seed_prompt_text,
            announce_branch_session_identifier=(
                self._user_facing_session_registry.begin_seeding_user_facing_session
            ),
        )
        self._user_facing_session_registry.finish_seeding_user_facing_session(
            branch_creation_result.session_identifier
        )

        branch_ordinal = next(self._branch_ordinal_counter)
        branch_command_line_argv = self._harness.build_interactive_resume_command_line(
            session_identifier=branch_creation_result.session_identifier,
            display_name=f"context handoff branch {branch_ordinal}",
        )
        self._user_interface_control.run_command_line_in_shared_window(
            self._shared_window_identifier, branch_command_line_argv
        )
        self._current_branch_session_identifier = (
            branch_creation_result.session_identifier
        )
        return branch_creation_result.session_identifier

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
            self._build_rotated_branch_session_preamble_text(pending_package.next_task)
        )

        return TurnRotationOutcome(
            new_branch_session_identifier=new_branch_session_identifier,
            base_session_acknowledgment=base_session_acknowledgment,
            rotated_history_path=rotated_history_path,
            forwarded_user_prompt_count=len(unconsumed_prompt_entries),
        )
