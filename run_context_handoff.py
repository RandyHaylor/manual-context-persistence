#!/usr/bin/env python3
"""Launch the context-handoff turn loop for a project.

This is the only place the real Claude CLI and real tmux adapters are wired to
the core. Everything it calls has been tested independently; this file is
composition and command-line handling.

    ./run_context_handoff.py                      # new base session
    ./run_context_handoff.py --resume-base <id>   # continue an existing one

Assumes the Claude CLI is installed and already logged in through its own local
OAuth flow. Nothing here prompts for or stores credentials.
"""
from __future__ import annotations

import argparse
import os
import sys

REPOSITORY_ROOT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if REPOSITORY_ROOT_DIRECTORY not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT_DIRECTORY)

from context_handoff.adapters.claude_cli.claude_cli_harness_adapter import (  # noqa: E402
    ClaudeCliHarnessAdapter,
)
from context_handoff.adapters.claude_cli.non_interactive_process_launcher import (  # noqa: E402
    SubprocessNonInteractiveProcessLauncher,
)
from context_handoff.adapters.tmux.tmux_command_runner import (  # noqa: E402
    SubprocessTmuxCommandRunner,
)
from context_handoff.adapters.tmux.tmux_user_interface_control_adapter import (  # noqa: E402
    TmuxUserInterfaceControlAdapter,
)
from context_handoff.context_to_keep.context_to_keep_file_store import (  # noqa: E402
    ContextToKeepFileStore,
)
from context_handoff.orchestration.turn_loop_runner import (  # noqa: E402
    run_turn_loop_until_stopped,
)
from context_handoff.orchestration.turn_rotation_orchestrator import (  # noqa: E402
    TurnRotationOrchestrator,
)
from context_handoff.startup.base_session_resolver import (  # noqa: E402
    resolve_base_session_for_startup,
)
from context_handoff.startup.hook_registration_preflight import (  # noqa: E402
    inspect_hook_registration_for_project,
)
from context_handoff.user_prompt_log.user_prompt_log_store import (  # noqa: E402
    UserPromptLogStore,
)

EXIT_CODE_SUCCESS = 0
EXIT_CODE_PREFLIGHT_FAILED = 2


def parse_command_line_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-directory",
        default=os.getcwd(),
        help="project root; defaults to the current directory",
    )
    parser.add_argument(
        "--resume-base",
        dest="base_session_identifier_to_resume",
        default=None,
        help="identifier of an existing base session to continue",
    )
    parser.add_argument(
        "--window-name",
        dest="shared_window_identifier",
        default=None,
        help="name for the shared window; defaults to a generated one",
    )
    parser.add_argument(
        "--skip-hook-preflight",
        action="store_true",
        help="start even if the project's hooks are not registered",
    )
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    arguments = parse_command_line_arguments(argv)
    project_directory = os.path.abspath(arguments.project_directory)

    harness = ClaudeCliHarnessAdapter(
        process_launcher=SubprocessNonInteractiveProcessLauncher(),
        project_working_directory=project_directory,
    )

    availability_report = harness.verify_harness_available_and_authorized()
    if not availability_report.is_available:
        print(f"harness unavailable: {availability_report.detail_text}", file=sys.stderr)
        return EXIT_CODE_PREFLIGHT_FAILED
    print(f"harness: {availability_report.detail_text}")

    hook_report = inspect_hook_registration_for_project(project_directory)
    print(f"hooks: {hook_report.detail_text}")
    if not hook_report.is_ready_to_run and not arguments.skip_hook_preflight:
        # Starting without hooks looks fine and captures nothing, so this stops
        # rather than warns.
        print(
            "refusing to start without the capture hooks; pass --skip-hook-preflight "
            "to override",
            file=sys.stderr,
        )
        return EXIT_CODE_PREFLIGHT_FAILED

    resolved_base_session = resolve_base_session_for_startup(
        harness=harness,
        working_directory=project_directory,
        base_session_identifier_to_resume=arguments.base_session_identifier_to_resume,
    )
    print(
        f"base session: {resolved_base_session.session_identifier} "
        f"({'created' if resolved_base_session.was_newly_created else 'resumed'})"
    )

    shared_window_identifier = (
        arguments.shared_window_identifier
        or f"context-handoff-{resolved_base_session.session_identifier[:8]}"
    )

    orchestrator = TurnRotationOrchestrator(
        harness=harness,
        user_interface_control=TmuxUserInterfaceControlAdapter(
            tmux_command_runner=SubprocessTmuxCommandRunner()
        ),
        context_to_keep_store=ContextToKeepFileStore(project_directory),
        user_prompt_log_store=UserPromptLogStore(project_directory),
        project_directory=project_directory,
        base_session_identifier=resolved_base_session.session_identifier,
        shared_window_identifier=shared_window_identifier,
    )

    first_branch_session_identifier = orchestrator.start_first_branch_session()
    print(f"shared window: {shared_window_identifier}")
    print(f"first branch: {first_branch_session_identifier}")
    print("watching for completed turns; press Ctrl-C here to stop")

    try:
        completed_rotation_count = run_turn_loop_until_stopped(
            orchestrator=orchestrator,
            should_continue_running=lambda: True,
            report_rotation_error=lambda rotation_error: print(
                f"rotation failed, continuing: {rotation_error}", file=sys.stderr
            ),
        )
    except KeyboardInterrupt:
        # The shared window is deliberately left open: the user may still be
        # mid-conversation in it, and closing it would discard their turn.
        print("\nstopped; the shared window is still open")
        return EXIT_CODE_SUCCESS
    print(f"completed {completed_rotation_count} rotations")
    return EXIT_CODE_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv))
