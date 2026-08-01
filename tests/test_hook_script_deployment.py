"""Tests for deploying the hook scripts to one fixed location.

A project's settings file names an absolute path to each hook script. Pointing
that path into this repository would tie every project to wherever the
repository sat on the day it was installed, so the scripts are copied to
``~/.claude/manual-context-persistence/hooks`` and referenced there instead.

Deployment overwrites every run. That is what keeps the deployed copies equal to
what this repository currently holds, and it makes a deleted or edited copy the
same case as a fresh install rather than a separate one.

Every test injects a destination. None of them writes to the developer's home.
"""
from __future__ import annotations

import os
import stat

import pytest

from context_handoff.project_state.project_state_directory import (
    user_application_directory_path,
)
from context_handoff.startup.hook_registration_preflight import (
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
)
from context_handoff.startup.hook_script_deployment import (
    HookScriptSourceMissingError,
    deploy_hook_scripts_overwriting_existing,
    resolve_deployed_hook_scripts_directory,
)

BOTH_HOOK_SCRIPT_FILE_NAMES = {
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
}


def build_source_directory_holding_both_scripts(tmp_path, script_body_text="# v1\n") -> str:
    source_directory = tmp_path / "repository" / "hooks"
    source_directory.mkdir(parents=True, exist_ok=True)
    for script_file_name in BOTH_HOOK_SCRIPT_FILE_NAMES:
        (source_directory / script_file_name).write_text(
            script_body_text, encoding="utf-8"
        )
    return str(source_directory)


def read_deployed_script(destination_directory: str, script_file_name: str) -> str:
    with open(
        os.path.join(destination_directory, script_file_name), "r", encoding="utf-8"
    ) as deployed_file:
        return deployed_file.read()


def test_the_deployed_location_is_under_the_users_home_not_the_project() -> None:
    deployed_directory = resolve_deployed_hook_scripts_directory()
    assert deployed_directory == os.path.join(user_application_directory_path(), "hooks")
    assert deployed_directory.startswith(os.path.expanduser("~"))


def test_both_scripts_are_deployed_when_nothing_is_there_yet(tmp_path) -> None:
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    destination_directory = str(tmp_path / "home" / "hooks")

    result = deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    assert set(result.deployed_hook_script_file_names) == BOTH_HOOK_SCRIPT_FILE_NAMES
    assert set(os.listdir(destination_directory)) == BOTH_HOOK_SCRIPT_FILE_NAMES


def test_the_destination_directory_is_created_if_absent(tmp_path) -> None:
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    destination_directory = str(tmp_path / "not" / "there" / "yet")

    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    assert os.path.isdir(destination_directory)


def test_an_updated_script_replaces_the_deployed_copy(tmp_path) -> None:
    """The reason this overwrites: otherwise the two drift with nothing to say so."""
    destination_directory = str(tmp_path / "home" / "hooks")
    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=build_source_directory_holding_both_scripts(
            tmp_path, script_body_text="# v1\n"
        ),
        deployed_hook_scripts_directory=destination_directory,
    )

    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=build_source_directory_holding_both_scripts(
            tmp_path, script_body_text="# v2\n"
        ),
        deployed_hook_scripts_directory=destination_directory,
    )

    assert read_deployed_script(destination_directory, STOP_HOOK_SCRIPT_FILE_NAME) == (
        "# v2\n"
    )


def test_a_locally_edited_deployed_script_is_replaced(tmp_path) -> None:
    """Deployed copies are outputs, not files to edit by hand."""
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    destination_directory = str(tmp_path / "home" / "hooks")
    os.makedirs(destination_directory)
    with open(
        os.path.join(destination_directory, STOP_HOOK_SCRIPT_FILE_NAME),
        "w",
        encoding="utf-8",
    ) as deployed_file:
        deployed_file.write("# edited in place\n")

    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    assert read_deployed_script(destination_directory, STOP_HOOK_SCRIPT_FILE_NAME) == (
        "# v1\n"
    )


def test_a_deleted_deployed_script_comes_back(tmp_path) -> None:
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    destination_directory = str(tmp_path / "home" / "hooks")
    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )
    os.remove(os.path.join(destination_directory, STOP_HOOK_SCRIPT_FILE_NAME))

    result = deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    assert set(result.deployed_hook_script_file_names) == BOTH_HOOK_SCRIPT_FILE_NAMES
    assert set(os.listdir(destination_directory)) == BOTH_HOOK_SCRIPT_FILE_NAMES


def test_every_run_reports_both_scripts_rather_than_only_changes(tmp_path) -> None:
    """It writes both every time, so the report says both every time."""
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    destination_directory = str(tmp_path / "home" / "hooks")
    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    second_result = deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    assert set(second_result.deployed_hook_script_file_names) == (
        BOTH_HOOK_SCRIPT_FILE_NAMES
    )
    assert destination_directory in second_result.detail_text


@pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "an executable bit is a POSIX concept; on Windows executability comes from "
        "the file extension, os.chmod only toggles the read-only flag, and the mode "
        "never reports execute — so there is nothing here to preserve or assert"
    ),
)
def test_an_executable_script_stays_executable_once_deployed(tmp_path) -> None:
    """Preserved where it exists. The harness runs these as `python3 "<path>"`,
    so nothing depends on it — this only keeps the deployed copy from being
    gratuitously different from the source.
    """
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    source_path = os.path.join(source_directory, STOP_HOOK_SCRIPT_FILE_NAME)
    os.chmod(source_path, os.stat(source_path).st_mode | stat.S_IXUSR)
    destination_directory = str(tmp_path / "home" / "hooks")

    deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=source_directory,
        deployed_hook_scripts_directory=destination_directory,
    )

    deployed_path = os.path.join(destination_directory, STOP_HOOK_SCRIPT_FILE_NAME)
    assert os.stat(deployed_path).st_mode & stat.S_IXUSR


def test_a_missing_source_script_raises_rather_than_being_skipped(tmp_path) -> None:
    """Skipping would register a command pointing at a script that is not there.

    The run would then look healthy and capture nothing, which is the failure
    this whole preflight exists to prevent.
    """
    source_directory = build_source_directory_holding_both_scripts(tmp_path)
    os.remove(os.path.join(source_directory, STOP_HOOK_SCRIPT_FILE_NAME))

    with pytest.raises(HookScriptSourceMissingError) as raised:
        deploy_hook_scripts_overwriting_existing(
            hook_scripts_source_directory=source_directory,
            deployed_hook_scripts_directory=str(tmp_path / "home" / "hooks"),
        )

    assert STOP_HOOK_SCRIPT_FILE_NAME in str(raised.value)


def test_the_real_repository_holds_both_scripts_to_deploy(tmp_path) -> None:
    """Guards the deployment against a rename in this repository's hooks folder."""
    import pathlib

    repository_hooks_directory = (
        pathlib.Path(__file__).resolve().parent.parent / "hooks"
    )

    result = deploy_hook_scripts_overwriting_existing(
        hook_scripts_source_directory=str(repository_hooks_directory),
        deployed_hook_scripts_directory=str(tmp_path / "home" / "hooks"),
    )

    assert set(result.deployed_hook_script_file_names) == BOTH_HOOK_SCRIPT_FILE_NAMES
