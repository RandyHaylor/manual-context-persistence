#!/usr/bin/env python3
"""Launch the context-handoff turn loop for a project.

    ./run_context_handoff.py                      # asks: new base session, or resume?
    ./run_context_handoff.py --new-base           # skip the question, create one
    ./run_context_handoff.py --resume-base <id>   # skip the question, resume one

This file parses arguments and builds the concrete Claude CLI and tmux
adapters. Every decision it used to make now lives in
``context_handoff.application.turn_loop_application``, where it is tested.

Assumes the Claude CLI is installed and already logged in through its own local
OAuth flow. Nothing here prompts for or stores credentials.
"""
from __future__ import annotations

import argparse
import functools
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
from context_handoff.application.turn_loop_application import (  # noqa: E402
    TurnLoopApplicationRequest,
    run_turn_loop_application,
)
from context_handoff.orchestration.turn_loop_runner import (  # noqa: E402
    run_turn_loop_until_stopped,
)


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
        help="identifier of an existing base session to continue, skipping the prompt",
    )
    parser.add_argument(
        "--new-base",
        dest="create_new_base_session_without_asking",
        action="store_true",
        help="create a new base session without asking",
    )
    parser.add_argument(
        "--window-name",
        dest="shared_window_identifier",
        default=None,
        help="name for the shared window; defaults to one derived from the base session",
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

    return run_turn_loop_application(
        request=TurnLoopApplicationRequest(
            project_directory=project_directory,
            base_session_identifier_to_resume=(
                arguments.base_session_identifier_to_resume
            ),
            create_new_base_session_without_asking=(
                arguments.create_new_base_session_without_asking
            ),
            shared_window_identifier=arguments.shared_window_identifier,
            skip_hook_preflight=arguments.skip_hook_preflight,
        ),
        harness=ClaudeCliHarnessAdapter(
            process_launcher=SubprocessNonInteractiveProcessLauncher(),
            project_working_directory=project_directory,
        ),
        user_interface_control=TmuxUserInterfaceControlAdapter(
            tmux_command_runner=SubprocessTmuxCommandRunner()
        ),
        run_turn_loop_with=functools.partial(
            run_turn_loop_until_stopped,
            should_continue_running=lambda: True,
            report_rotation_error=lambda rotation_error: print(
                f"rotation failed, continuing: {rotation_error}", file=sys.stderr
            ),
        ),
        read_answer=input,
        write_line=print,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
