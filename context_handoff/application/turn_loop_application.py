"""The startup sequence: check, resolve, open, then hand off to the loop.

This lives here rather than in the entry-point script because it makes real
decisions — whether to refuse a run, whether to create a base session, what to
call the window — and decisions need tests. The script above it now only parses
arguments and builds the concrete adapters.

Collaborators arrive as arguments rather than being constructed here, so the
whole sequence runs in a test with no Claude CLI, no tmux, and no terminal.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Callable, Optional

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.interfaces.harness_interface import HarnessInterface
from context_handoff.interfaces.user_interface_control_interface import (
    UserInterfaceControlInterface,
)
from context_handoff.orchestration.branch_session_preamble import (
    build_first_branch_session_preamble_text,
    build_rotated_branch_session_preamble_text,
)
from context_handoff.orchestration.turn_rotation_orchestrator import (
    TurnRotationOrchestrator,
)
from context_handoff.project_state.context_handoff_settings_store import (
    ContextHandoffSettingsStore,
)
from context_handoff.startup.base_session_choice_prompt import (
    ask_whether_to_create_or_resume_base_session,
)
from context_handoff.startup.base_session_resolver import (
    resolve_base_session_for_startup,
)
from context_handoff.startup.hook_installation_choice_prompt import (
    ask_whether_to_install_missing_hooks,
)
from context_handoff.startup.hook_registration_installer import (
    install_context_handoff_hooks_into_project_settings,
)
from context_handoff.startup.hook_registration_preflight import (
    build_project_settings_path,
    inspect_hook_registration_for_project,
)
from context_handoff.startup.hook_runtime_deployment import (
    deploy_hook_runtime_overwriting_existing,
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
    # Where the hook runtime is read from, which is this repository: both the
    # scripts and the package they import are copied to one fixed place under the
    # user's home before being referenced, so a project's settings file never
    # points into the repository itself.
    repository_root_directory: str
    base_session_identifier_to_resume: Optional[str] = None
    # Injectable so a test deploys into a temporary directory rather than into
    # the developer's own home.
    deployed_runtime_directory: Optional[str] = None
    create_new_base_session_without_asking: bool = False
    shared_window_identifier: Optional[str] = None
    # None means the operator did not pass the flag, which is not the same as
    # passing it as false; only a stated value overrides the settings file.
    require_git_commit_override: Optional[bool] = None


def build_shared_window_identifier_for_base_session(base_session_identifier: str) -> str:
    """Name the window after the base session, as the spec asks.

    Tying the two together is what stops a second run from driving the first
    run's window.
    """
    return (
        SHARED_WINDOW_NAME_PREFIX
        + base_session_identifier[:SHARED_WINDOW_NAME_SESSION_CHARACTERS]
    )


def prepare_project_state_and_hooks(
    request: TurnLoopApplicationRequest,
    read_answer: Callable[[str], str],
    write_line: Callable[[str], None],
) -> bool:
    """Set up what is missing, ask before touching what is not, or refuse.

    Three cases, and the difference between the first two is whose file it is.
    No ``settings.local.json`` at all means nothing of the operator's exists yet,
    so both it and our own folder are created without asking. A file that is
    already there but does not register our hooks is theirs, so writing into it
    is a question. Hooks already registered is the ordinary case.

    There is no path that starts the loop without the hooks, because each hook is
    the only writer of a file the loop depends on, and losing either is an error
    state rather than a degraded run:

    - No Stop hook: nothing ever writes ``context-to-keep.json``, so the loop's
      poll never sees a pending handoff and it idles for as long as the session
      is used. It does not rotate and it does not fail — it silently does
      nothing.
    - No UserPromptSubmit hook: rotation still happens, but the prompt log is
      never written, so every handoff reaches the base session carrying the
      agent's context and none of what the user asked for.

    So the only answers are to install them or to stop.

    Returns False when the run must not continue.
    """
    settings_store = ContextHandoffSettingsStore(request.project_directory)
    if settings_store.write_default_settings_if_absent():
        write_line(f"settings: created {settings_store.settings_file_path}")
    else:
        write_line(f"settings: {settings_store.settings_file_path}")

    # Before anything looks at or writes a command naming these scripts, make
    # sure what sits at that path is the runtime this repository currently holds —
    # the scripts and the package they import, or they die before any handler runs.
    deployment_result = deploy_hook_runtime_overwriting_existing(
        repository_root_directory=request.repository_root_directory,
        deployed_runtime_directory=request.deployed_runtime_directory,
    )
    write_line(f"hook runtime: {deployment_result.detail_text}")

    hook_report = inspect_hook_registration_for_project(request.project_directory)
    if hook_report.is_ready_to_run:
        write_line(f"hooks: {hook_report.detail_text}")
        return True

    if not hook_report.settings_file_exists:
        installation_result = install_context_handoff_hooks_into_project_settings(
            project_directory=request.project_directory,
            hook_scripts_directory=deployment_result.deployed_hook_scripts_directory,
        )
        write_line(f"hooks: {installation_result.detail_text}")
        return True

    write_line(f"hooks: {hook_report.detail_text}")
    try:
        should_install = ask_whether_to_install_missing_hooks(
            read_answer=read_answer,
            write_line=write_line,
            missing_hook_event_names=hook_report.missing_hook_event_names,
            settings_file_path=build_project_settings_path(request.project_directory),
        )
    except EOFError:
        write_line(
            "no answer available on stdin; register the capture hooks and start again"
        )
        return False

    if not should_install:
        # A run without capture looks healthy and records nothing, which is the
        # worst of both, so aborting is the answer rather than continuing.
        write_line("aborting without installing the capture hooks")
        return False

    installation_result = install_context_handoff_hooks_into_project_settings(
        project_directory=request.project_directory,
        hook_scripts_directory=deployment_result.deployed_hook_scripts_directory,
    )
    write_line(f"hooks: {installation_result.detail_text}")
    return True


def run_turn_loop_application(
    request: TurnLoopApplicationRequest,
    harness: HarnessInterface,
    user_interface_control: UserInterfaceControlInterface,
    run_turn_loop_with: Callable[[TurnRotationOrchestrator], int],
    read_answer: Callable[[str], str],
    write_line: Callable[[str], None],
    sleep_for_seconds: Callable[[float], None] = time.sleep,
) -> int:
    """``sleep_for_seconds`` is injected only so tests need not really wait.

    Startup waits for a real terminal to finish drawing before it aims a
    keypress at it, which is seconds of genuine wall clock in production and
    pure dead time in a test.
    """
    availability_report = harness.verify_harness_available_and_authorized()
    if not availability_report.is_available:
        write_line(f"harness unavailable: {availability_report.detail_text}")
        return EXIT_CODE_PREFLIGHT_FAILED
    write_line(f"harness: {availability_report.detail_text}")

    if not prepare_project_state_and_hooks(
        request=request, read_answer=read_answer, write_line=write_line
    ):
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

    # Naming stays here, but the resolver applies it: creating a base session
    # now needs the window it will be created in, and that window is named after
    # the base session, so the two have to be settled together.
    resolved_base_session = resolve_base_session_for_startup(
        harness=harness,
        user_interface_control=user_interface_control,
        working_directory=request.project_directory,
        build_shared_window_identifier=(
            lambda base_session_identifier: request.shared_window_identifier
            or build_shared_window_identifier_for_base_session(base_session_identifier)
        ),
        base_session_identifier_to_resume=base_session_identifier_to_resume,
        sleep_for_seconds=sleep_for_seconds,
    )
    write_line(
        f"base session: {resolved_base_session.session_identifier} "
        f"({'created' if resolved_base_session.was_newly_created else 'resumed'})"
    )

    shared_window_identifier = resolved_base_session.shared_window_identifier

    effective_settings = (
        ContextHandoffSettingsStore(request.project_directory)
        .read_settings()
        .with_require_git_commit_override(request.require_git_commit_override)
    )
    write_line(
        "git commit before handing off: "
        f"{'required' if effective_settings.require_git_commit else 'not required'}"
    )

    orchestrator = TurnRotationOrchestrator(
        harness=harness,
        user_interface_control=user_interface_control,
        context_to_keep_store=ContextToKeepFileStore(request.project_directory),
        user_prompt_log_store=UserPromptLogStore(request.project_directory),
        project_directory=request.project_directory,
        base_session_identifier=resolved_base_session.session_identifier,
        shared_window_identifier=shared_window_identifier,
        first_branch_session_preamble_text=build_first_branch_session_preamble_text(
            require_git_commit=effective_settings.require_git_commit
        ),
        # A partial rather than a finished string: the rotation text depends on
        # the task the session being replaced named, which is not known yet.
        build_rotated_branch_session_preamble_text=functools.partial(
            build_rotated_branch_session_preamble_text,
            require_git_commit=effective_settings.require_git_commit,
        ),
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
