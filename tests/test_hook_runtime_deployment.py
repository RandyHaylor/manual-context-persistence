"""Tests for deploying the runtime the hooks need, to one fixed location.

A project's settings file names an absolute path to each hook script. Pointing
that path into this repository would tie every project to wherever the repository
sat on the day it was installed, so the runtime is copied to
``~/.claude/manual-context-persistence`` and referenced there instead.

The test that matters most here runs a *deployed* script as a real process and
checks it does its job. An earlier version of this deployment copied the scripts
and not the package they import, so every deployed hook died at import: the
harness reported a non-blocking error, the session looked healthy, and nothing was
ever captured. Every test below passed at the time, because they all only checked
that files had arrived.

Every test injects a destination. None of them writes to the developer's home.
"""
from __future__ import annotations

import json
import os
import stat
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
from context_handoff.project_state.project_state_directory import (
    user_application_directory_path,
)
from context_handoff.startup.hook_registration_preflight import (
    HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME,
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
)
from context_handoff.startup.hook_runtime_deployment import (
    HookRuntimeSourceMissingError,
    deploy_hook_runtime_overwriting_existing,
    resolve_deployed_runtime_directory,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)

REPOSITORY_ROOT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVERY_HOOK_SCRIPT_FILE_NAME = set(HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME.values())


def deploy_the_real_runtime_into(tmp_path):
    return deploy_hook_runtime_overwriting_existing(
        repository_root_directory=REPOSITORY_ROOT_DIRECTORY,
        deployed_runtime_directory=str(tmp_path / "home-claude" / "mcp-app"),
    )


def test_the_deployed_location_is_under_the_users_home_not_the_project() -> None:
    assert resolve_deployed_runtime_directory() == user_application_directory_path()
    assert resolve_deployed_runtime_directory().startswith(os.path.expanduser("~"))


def test_both_the_scripts_and_the_package_they_import_are_deployed(tmp_path) -> None:
    """Scripts alone are not a runtime: each one imports the package by path."""
    result = deploy_the_real_runtime_into(tmp_path)

    assert set(result.deployed_hook_script_file_names) == EVERY_HOOK_SCRIPT_FILE_NAME
    assert set(os.listdir(result.deployed_hook_scripts_directory)) == (
        EVERY_HOOK_SCRIPT_FILE_NAME
    )
    assert os.path.isdir(
        os.path.join(result.deployed_runtime_directory, "context_handoff")
    )


def test_the_package_lands_where_the_scripts_look_for_it(tmp_path) -> None:
    """Each script puts its parent's parent on sys.path and imports from there."""
    result = deploy_the_real_runtime_into(tmp_path)

    directory_a_script_will_search = os.path.dirname(
        result.deployed_hook_scripts_directory
    )
    assert os.path.isdir(
        os.path.join(directory_a_script_will_search, "context_handoff")
    )


def test_a_deployed_stop_hook_captures_a_package_as_a_real_process(tmp_path) -> None:
    """The test the first deployment needed and did not have.

    Runs the deployed script the way the harness does — as a separate process,
    payload on stdin — and checks the handoff actually reached disk. A deployment
    that cannot import its package fails here and nowhere else.
    """
    result = deploy_the_real_runtime_into(tmp_path)
    project_directory = str(tmp_path / "project")
    os.makedirs(project_directory)

    session_identifier = "a-user-facing-session"
    UserFacingSessionRegistry(project_directory).register_user_facing_session(
        session_identifier
    )
    package_json = json.dumps(
        {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "context_to_keep": ["The codeword is WOMBAT-8842."],
            "next_task": "Tell the user the codeword.",
        }
    )

    completed_process = subprocess.run(
        [
            sys.executable,
            os.path.join(
                result.deployed_hook_scripts_directory, STOP_HOOK_SCRIPT_FILE_NAME
            ),
        ],
        # The payload shape the platform actually sends: the final assistant text
        # arrives in last_assistant_message.
        input=json.dumps(
            {
                "cwd": project_directory,
                "session_id": session_identifier,
                "transcript_path": str(tmp_path / "transcript.jsonl"),
                "hook_event_name": "Stop",
                "last_assistant_message": (
                    f"Did the work.\n\n```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
                    f"{package_json}\n```"
                ),
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed_process.returncode == 0, completed_process.stderr
    assert "ModuleNotFoundError" not in completed_process.stderr
    captured_package = ContextToKeepFileStore(
        project_directory
    ).read_pending_context_to_keep_package()
    assert captured_package is not None, completed_process.stderr
    assert captured_package.next_task == "Tell the user the codeword."


@pytest.mark.parametrize(
    "hook_script_file_name", sorted(EVERY_HOOK_SCRIPT_FILE_NAME)
)
def test_a_deployed_hook_starts_without_an_import_error(
    tmp_path, hook_script_file_name: str
) -> None:
    """Both scripts, minimally: handed empty input, they must still start."""
    result = deploy_the_real_runtime_into(tmp_path)

    completed_process = subprocess.run(
        [
            sys.executable,
            os.path.join(result.deployed_hook_scripts_directory, hook_script_file_name),
        ],
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed_process.returncode == 0, completed_process.stderr
    assert "ModuleNotFoundError" not in completed_process.stderr


def test_the_destination_is_created_if_absent(tmp_path) -> None:
    result = deploy_hook_runtime_overwriting_existing(
        repository_root_directory=REPOSITORY_ROOT_DIRECTORY,
        deployed_runtime_directory=str(tmp_path / "not" / "there" / "yet"),
    )
    assert os.path.isdir(result.deployed_hook_scripts_directory)


def test_an_updated_script_replaces_the_deployed_copy(tmp_path) -> None:
    """The reason this overwrites: otherwise the two drift with nothing to say so."""
    destination_runtime_directory = str(tmp_path / "home-claude" / "mcp-app")
    deploy_hook_runtime_overwriting_existing(
        repository_root_directory=REPOSITORY_ROOT_DIRECTORY,
        deployed_runtime_directory=destination_runtime_directory,
    )
    deployed_script_path = os.path.join(
        destination_runtime_directory, "hooks", STOP_HOOK_SCRIPT_FILE_NAME
    )
    with open(deployed_script_path, "w", encoding="utf-8") as deployed_file:
        deployed_file.write("# edited in place\n")

    deploy_hook_runtime_overwriting_existing(
        repository_root_directory=REPOSITORY_ROOT_DIRECTORY,
        deployed_runtime_directory=destination_runtime_directory,
    )

    with open(deployed_script_path, "r", encoding="utf-8") as deployed_file:
        assert deployed_file.read() != "# edited in place\n"


def test_a_deleted_deployed_script_comes_back(tmp_path) -> None:
    destination_runtime_directory = str(tmp_path / "home-claude" / "mcp-app")
    deploy_hook_runtime_overwriting_existing(
        repository_root_directory=REPOSITORY_ROOT_DIRECTORY,
        deployed_runtime_directory=destination_runtime_directory,
    )
    os.remove(
        os.path.join(destination_runtime_directory, "hooks", STOP_HOOK_SCRIPT_FILE_NAME)
    )

    result = deploy_hook_runtime_overwriting_existing(
        repository_root_directory=REPOSITORY_ROOT_DIRECTORY,
        deployed_runtime_directory=destination_runtime_directory,
    )

    assert set(os.listdir(result.deployed_hook_scripts_directory)) == (
        EVERY_HOOK_SCRIPT_FILE_NAME
    )


def test_compiled_bytecode_is_not_deployed(tmp_path) -> None:
    """It belongs to the interpreter that wrote it, not to a copy of the source."""
    result = deploy_the_real_runtime_into(tmp_path)

    for directory_path, directory_names, _file_names in os.walk(
        result.deployed_runtime_directory
    ):
        assert "__pycache__" not in directory_names, directory_path


@pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "an executable bit is a POSIX concept; on Windows executability comes from "
        "the file extension and the mode never reports execute"
    ),
)
def test_an_executable_script_stays_executable_once_deployed(tmp_path) -> None:
    result = deploy_the_real_runtime_into(tmp_path)

    deployed_script_path = os.path.join(
        result.deployed_hook_scripts_directory, STOP_HOOK_SCRIPT_FILE_NAME
    )
    assert os.stat(deployed_script_path).st_mode & stat.S_IXUSR


def test_a_missing_source_package_raises_rather_than_deploying_scripts_alone(
    tmp_path,
) -> None:
    """Scripts without the package are the exact failure this module now prevents."""
    source_without_a_package = tmp_path / "broken-source"
    (source_without_a_package / "hooks").mkdir(parents=True)
    for hook_script_file_name in EVERY_HOOK_SCRIPT_FILE_NAME:
        (source_without_a_package / "hooks" / hook_script_file_name).write_text(
            "# stand-in\n", encoding="utf-8"
        )

    with pytest.raises(HookRuntimeSourceMissingError) as raised:
        deploy_hook_runtime_overwriting_existing(
            repository_root_directory=str(source_without_a_package),
            deployed_runtime_directory=str(tmp_path / "home-claude" / "mcp-app"),
        )

    assert "context_handoff" in str(raised.value)


def test_a_missing_source_script_raises_rather_than_being_skipped(tmp_path) -> None:
    source_without_a_script = tmp_path / "partial-source"
    (source_without_a_script / "hooks").mkdir(parents=True)
    (source_without_a_script / "context_handoff").mkdir()
    (
        source_without_a_script / "hooks" / USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME
    ).write_text("# stand-in\n", encoding="utf-8")

    with pytest.raises(HookRuntimeSourceMissingError) as raised:
        deploy_hook_runtime_overwriting_existing(
            repository_root_directory=str(source_without_a_script),
            deployed_runtime_directory=str(tmp_path / "home-claude" / "mcp-app"),
        )

    assert STOP_HOOK_SCRIPT_FILE_NAME in str(raised.value)
