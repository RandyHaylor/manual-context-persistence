"""Run the hook scripts as real processes, the way Claude Code runs them.

The handler tests cover the logic; these cover the wiring — that the scripts
are executable, find their imports, accept JSON on stdin, print JSON on stdout,
and exit zero even when handed garbage.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore

HOOKS_DIRECTORY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"
)
STOP_HOOK_SCRIPT_PATH = os.path.join(HOOKS_DIRECTORY, "context_to_keep_stop_hook.py")
USER_PROMPT_SUBMIT_HOOK_SCRIPT_PATH = os.path.join(
    HOOKS_DIRECTORY, "user_prompt_submit_capture_hook.py"
)


def run_hook_script(script_path: str, payload_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script_path],
        input=payload_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "script_path", [STOP_HOOK_SCRIPT_PATH, USER_PROMPT_SUBMIT_HOOK_SCRIPT_PATH]
)
def test_hook_script_exists_and_is_executable(script_path: str) -> None:
    assert os.path.exists(script_path)
    assert os.access(script_path, os.X_OK)


@pytest.mark.parametrize(
    "script_path", [STOP_HOOK_SCRIPT_PATH, USER_PROMPT_SUBMIT_HOOK_SCRIPT_PATH]
)
def test_hook_script_prints_json_and_exits_zero_on_empty_input(script_path: str) -> None:
    completed = run_hook_script(script_path, "")
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {}


@pytest.mark.parametrize(
    "script_path", [STOP_HOOK_SCRIPT_PATH, USER_PROMPT_SUBMIT_HOOK_SCRIPT_PATH]
)
def test_hook_script_survives_malformed_input(script_path: str) -> None:
    completed = run_hook_script(script_path, "{ not json at all")
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {}


@pytest.mark.parametrize(
    "script_path", [STOP_HOOK_SCRIPT_PATH, USER_PROMPT_SUBMIT_HOOK_SCRIPT_PATH]
)
def test_hook_script_survives_a_json_value_that_is_not_an_object(
    script_path: str,
) -> None:
    completed = run_hook_script(script_path, "[1, 2, 3]")
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {}


def test_stop_hook_script_writes_the_package_end_to_end(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    package_json = json.dumps(
        {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "summary_of_work_completed_this_turn": "End to end through the script.",
            "context_to_carry_forward": [],
        }
    )
    transcript_path = str(tmp_path / "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        transcript_file.write(
            json.dumps(
                {
                    "type": "assistant",
                    "isSidechain": False,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
                                f"{package_json}\n```",
                            }
                        ],
                    },
                }
            )
            + "\n"
        )

    completed = run_hook_script(
        STOP_HOOK_SCRIPT_PATH,
        json.dumps(
            {
                "cwd": project_directory,
                "session_id": "branch-session",
                "transcript_path": transcript_path,
                "hook_event_name": "Stop",
            }
        ),
    )

    assert completed.returncode == 0
    stored_package = ContextToKeepFileStore(
        project_directory
    ).read_pending_context_to_keep_package()
    assert stored_package is not None
    assert (
        stored_package.summary_of_work_completed_this_turn
        == "End to end through the script."
    )


def test_user_prompt_submit_hook_script_logs_the_prompt_end_to_end(tmp_path) -> None:
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)
    UserFacingSessionRegistry(project_directory).register_user_facing_session(
        "branch-session"
    )

    completed = run_hook_script(
        USER_PROMPT_SUBMIT_HOOK_SCRIPT_PATH,
        json.dumps(
            {
                "cwd": project_directory,
                "session_id": "branch-session",
                "prompt": "exactly these words",
                "hook_event_name": "UserPromptSubmit",
            }
        ),
    )

    assert completed.returncode == 0
    logged_entries = UserPromptLogStore(project_directory).read_entries_for_session(
        "branch-session"
    )
    assert [entry.user_prompt_text for entry in logged_entries] == [
        "exactly these words"
    ]
