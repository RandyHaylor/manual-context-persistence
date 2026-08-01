"""Tests for writing this system's two hooks into a project's settings.

The file being written belongs to the harness and may already carry an
operator's own settings, permissions, and hooks for other tools. So the
substance here is what installation must *not* disturb, and that running it
twice cannot accumulate duplicates.

The installer and the checker are held to each other on purpose: whatever is
written must be what the preflight recognises, or the run would install hooks and
then report them missing.
"""
from __future__ import annotations

import json
import os

from context_handoff.startup.hook_registration_installer import (
    build_hook_command_text,
    install_context_handoff_hooks_into_project_settings,
)
from context_handoff.startup.hook_registration_preflight import (
    HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME,
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
    inspect_hook_registration_for_project,
)

EVERY_HOOK_EVENT_NAME = set(HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME)

HOOK_SCRIPTS_DIRECTORY = "/opt/manual-context-persistence/hooks"


def settings_path_for(project_directory: str) -> str:
    return os.path.join(project_directory, ".claude", "settings.local.json")


def write_settings(project_directory: str, settings_dictionary: dict) -> str:
    settings_path = settings_path_for(project_directory)
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as settings_file:
        json.dump(settings_dictionary, settings_file)
    return settings_path


def read_settings(project_directory: str) -> dict:
    with open(settings_path_for(project_directory), "r", encoding="utf-8") as file:
        return json.load(file)


def install_into(project_directory: str):
    return install_context_handoff_hooks_into_project_settings(
        project_directory=project_directory,
        hook_scripts_directory=HOOK_SCRIPTS_DIRECTORY,
    )


def commands_registered_for_event(project_directory: str, event_name: str) -> list[str]:
    return [
        hook_definition["command"]
        for event_entry in read_settings(project_directory)["hooks"][event_name]
        for hook_definition in event_entry["hooks"]
    ]


def test_installing_into_nothing_registers_every_hook(tmp_path) -> None:
    project_directory = str(tmp_path)

    result = install_into(project_directory)

    assert set(result.installed_hook_event_names) == EVERY_HOOK_EVENT_NAME
    assert set(read_settings(project_directory)["hooks"]) == EVERY_HOOK_EVENT_NAME


def test_what_is_installed_is_what_the_preflight_recognises(tmp_path) -> None:
    """Otherwise the run would install hooks and then report them missing."""
    project_directory = str(tmp_path)

    install_into(project_directory)

    assert inspect_hook_registration_for_project(project_directory).is_ready_to_run


def test_the_command_points_at_this_repository_by_absolute_path(tmp_path) -> None:
    """The project being worked in is a different directory from this one."""
    project_directory = str(tmp_path)

    install_into(project_directory)

    stop_hook_commands = commands_registered_for_event(project_directory, "Stop")
    assert len(stop_hook_commands) == 1
    assert STOP_HOOK_SCRIPT_FILE_NAME in stop_hook_commands[0]
    assert HOOK_SCRIPTS_DIRECTORY in stop_hook_commands[0]


def test_a_path_containing_a_space_is_quoted() -> None:
    command_text = build_hook_command_text(
        "/home/someone/my projects/hooks", STOP_HOOK_SCRIPT_FILE_NAME
    )
    assert f'"{os.path.join("/home/someone/my projects/hooks", STOP_HOOK_SCRIPT_FILE_NAME)}"' in (
        command_text
    )


def test_a_relative_scripts_directory_is_made_absolute() -> None:
    """A relative path would resolve against whatever directory the harness runs in."""
    command_text = build_hook_command_text("hooks", STOP_HOOK_SCRIPT_FILE_NAME)
    assert os.path.abspath("hooks") in command_text


def test_installing_preserves_unrelated_settings(tmp_path) -> None:
    project_directory = str(tmp_path)
    write_settings(
        project_directory,
        {"permissions": {"allow": ["Bash(ls:*)"]}, "model": "opus"},
    )

    install_into(project_directory)

    settings = read_settings(project_directory)
    assert settings["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert settings["model"] == "opus"


def test_installing_preserves_another_tools_hook_on_the_same_event(tmp_path) -> None:
    """Hooks coexist, so someone else's Stop hook is not a conflict."""
    project_directory = str(tmp_path)
    write_settings(
        project_directory,
        {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "python3 someone_elses.py"}
                        ]
                    }
                ]
            }
        },
    )

    install_into(project_directory)

    stop_hook_commands = commands_registered_for_event(project_directory, "Stop")
    assert any("someone_elses.py" in command for command in stop_hook_commands)
    assert any(STOP_HOOK_SCRIPT_FILE_NAME in command for command in stop_hook_commands)


def test_installing_twice_adds_nothing_the_second_time(tmp_path) -> None:
    project_directory = str(tmp_path)
    install_into(project_directory)

    second_result = install_into(project_directory)

    assert second_result.installed_hook_event_names == []
    assert set(second_result.already_registered_hook_event_names) == (
        EVERY_HOOK_EVENT_NAME
    )
    assert len(commands_registered_for_event(project_directory, "Stop")) == 1


def test_only_the_missing_hook_is_added(tmp_path) -> None:
    project_directory = str(tmp_path)
    write_settings(
        project_directory,
        {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 /elsewhere/{STOP_HOOK_SCRIPT_FILE_NAME}",
                            }
                        ]
                    }
                ]
            }
        },
    )

    result = install_into(project_directory)

    assert "Stop" not in result.installed_hook_event_names
    assert result.already_registered_hook_event_names == ["Stop"]
    assert set(result.installed_hook_event_names) == EVERY_HOOK_EVENT_NAME - {"Stop"}
    assert len(commands_registered_for_event(project_directory, "Stop")) == 1


def test_an_unreadable_settings_file_is_replaced_rather_than_crashing(tmp_path) -> None:
    """Startup only reaches installation for an absent file or on an explicit yes.

    Either way, refusing to write because the existing bytes are unparsable
    would leave the run with no capture and nothing the operator can do from
    inside the app.
    """
    project_directory = str(tmp_path)
    settings_path = settings_path_for(project_directory)
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as settings_file:
        settings_file.write("{ not json")

    install_into(project_directory)

    assert inspect_hook_registration_for_project(project_directory).is_ready_to_run


def test_a_hooks_key_of_the_wrong_type_is_replaced(tmp_path) -> None:
    project_directory = str(tmp_path)
    write_settings(project_directory, {"hooks": "not a mapping"})

    install_into(project_directory)

    assert inspect_hook_registration_for_project(project_directory).is_ready_to_run


def test_nothing_is_written_when_both_hooks_are_already_there(tmp_path) -> None:
    project_directory = str(tmp_path)
    install_into(project_directory)
    settings_path = settings_path_for(project_directory)
    modification_time_before = os.path.getmtime(settings_path)

    install_into(project_directory)

    assert os.path.getmtime(settings_path) == modification_time_before


def test_the_result_names_the_file_it_wrote(tmp_path) -> None:
    project_directory = str(tmp_path)

    result = install_into(project_directory)

    assert result.settings_file_path == settings_path_for(project_directory)
    assert USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME in json.dumps(
        read_settings(project_directory)
    )
