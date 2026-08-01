"""The startup sequence: check, resolve, open, then hand off to the loop.

This lives here rather than in the entry-point script because it makes real
decisions — whether to refuse a run, whether to create a base session, what to
call the window — and decisions need tests. The script above it now only parses
arguments and builds the concrete adapters.

Collaborators arrive as arguments rather than being constructed here, so the
whole sequence runs in a test with no Claude CLI, no tmux, and no terminal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.interfaces.harness_interface import HarnessInterface
from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)
from context_handoff.orchestration.turn_rotation_orchestrator import (
    TurnRotationOrchestrator,
)
from context_handoff.startup.base_session_choice_prompt import (
    ask_whether_to_create_or_resume_base_session,
)
from context_handoff.startup.base_session_resolver import (
    resolve_base_session_for_startup,
)
from context_handoff.startup.hook_registration_preflight import (
    inspect_hook_registration_for_project,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore

EXIT_CODE_SUCCESS = 0
EXIT_CODE_PREFLIGHT_FAILED = 2

SHARED_WINDOW_NAME_PREFIX = "context-handoff-"
SHARED_WINDOW_NAME_SESSION_CHARACTERS = 8


@dataclass(frozen=True)
class TurnLoopApplicationRequest:
    """What the operator asked for, independent of how they asked."""

    project_directory: str
    base_session_identifier_to_resume: Optional[str] = None
    create_new_base_session_without_asking: bool = False
    shared_window_identifier: Optional[str] = None
    skip_hook_preflight: bool = False


def build_shared_window_identifier_for_base_session(base_session_identifier: str) -> str:
    """Name the window after the base session, as the spec asks.

    Tying the two together is what stops a second run from driving the first
    run's window.
    """
    return (
        SHARED_WINDOW_NAME_PREFIX
        + base_session_identifier[:SHARED_WINDOW_NAME_SESSION_CHARACTERS]
    )


def run_turn_loop_application(
    request: TurnLoopApplicationRequest,
    harness: HarnessInterface,
    user_interface_control: UserInterfaceControlInterface,
    run_turn_loop_with: Callable[[TurnRotationOrchestrator], int],
    read_answer: Callable[[str], str],
    write_line: Callable[[str], None],
) -> int:
    availability_report = harness.verify_harness_available_and_authorized()
    if not availability_report.is_available:
        write_line(f"harness unavailable: {availability_report.detail_text}")
        return EXIT_CODE_PREFLIGHT_FAILED
    write_line(f"harness: {availability_report.detail_text}")

    # Warn rather than refuse. Somebody can answer the harness's approval
    # prompt in the window once it appears, and refusing would block that
    # perfectly reasonable way of working.
    if (
        harness.read_whether_project_is_approved_for_automation(request.project_directory)
        is False
    ):
        write_line(
            "note: this project has not been approved in the harness yet, so the "
            "first branch will wait for approval in the shared window and nothing "
            "is captured until it is given"
        )

    hook_report = inspect_hook_registration_for_project(request.project_directory)
    write_line(f"hooks: {hook_report.detail_text}")
    if not hook_report.is_ready_to_run and not request.skip_hook_preflight:
        # Refuses rather than warns: a run without capture looks healthy and
        # records nothing, which is the worst of both.
        write_line(
            "refusing to start without the capture hooks; pass --skip-hook-preflight "
            "to override"
        )
        return EXIT_CODE_PREFLIGHT_FAILED

    base_session_identifier_to_resume = request.base_session_identifier_to_resume
    if (
        base_session_identifier_to_resume is None
        and not request.create_new_base_session_without_asking
    ):
        try:
            base_session_choice = ask_whether_to_create_or_resume_base_session(
                read_answer=read_answer, write_line=write_line
            )
        except EOFError:
            write_line("no answer available on stdin; pass --new-base or --resume-base")
            return EXIT_CODE_PREFLIGHT_FAILED
        base_session_identifier_to_resume = (
            base_session_choice.base_session_identifier_to_resume
        )

    resolved_base_session = resolve_base_session_for_startup(
        harness=harness,
        working_directory=request.project_directory,
        base_session_identifier_to_resume=base_session_identifier_to_resume,
    )
    write_line(
        f"base session: {resolved_base_session.session_identifier} "
        f"({'created' if resolved_base_session.was_newly_created else 'resumed'})"
    )

    shared_window_identifier = (
        request.shared_window_identifier
        or build_shared_window_identifier_for_base_session(
            resolved_base_session.session_identifier
        )
    )

    orchestrator = TurnRotationOrchestrator(
        harness=harness,
        user_interface_control=user_interface_control,
        context_to_keep_store=ContextToKeepFileStore(request.project_directory),
        user_prompt_log_store=UserPromptLogStore(request.project_directory),
        project_directory=request.project_directory,
        base_session_identifier=resolved_base_session.session_identifier,
        shared_window_identifier=shared_window_identifier,
    )

    first_branch_session_identifier = orchestrator.start_first_branch_session()
    write_line(f"shared window: {shared_window_identifier}")
    write_line(f"first branch: {first_branch_session_identifier}")
    write_line("watching for completed turns; press Ctrl-C here to stop")

    try:
        completed_rotation_count = run_turn_loop_with(orchestrator)
    except KeyboardInterrupt:
        # The window stays open on purpose: the user may be mid-conversation in
        # it, and closing it would discard their turn.
        write_line("stopped; the shared window is still open")
        return EXIT_CODE_SUCCESS
    write_line(f"completed {completed_rotation_count} rotations")
    return EXIT_CODE_SUCCESS
