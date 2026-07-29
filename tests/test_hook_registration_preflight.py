"""Tests for the startup check that both hooks are registered for a project.

Without the hooks nothing is captured and the turn loop silently hands off
empty turns forever, so this check runs before the loop starts and reports
precisely what is missing rather than just failing.
"""
from __future__ import annotations

import json
import os

from context_handoff.startup.hook_registration_preflight import (
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
    inspect_hook_registration_for_project,
)


def write_settings(project_directory: str, settings_dictionary: dict) -> str:
    claude_directory = os.path.join(project_directory, ".claude")
    os.makedirs(claude_directory, exist_ok=True)
    settings_path = os.path.join(claude_directory, "settings.local.json")
    with open(settings_path, "w", encoding="utf-8") as settings_file:
        json.dump(settings_dictionary, settings_file, indent=2)
    return settings_path


def build_settings_with_hooks(
    include_stop_hook: bool = True, include_user_prompt_submit_hook: bool = True
) -> dict:
    hooks_dictionary: dict = {}
    if include_stop_hook:
        hooks_dictionary["Stop"] = [
            {
                "matcher": "*",
                "hooks": [
                    {"type": "command", "command": f"python3 /x/{STOP_HOOK_SCRIPT_FILE_NAME}"}
                ],
            }
        ]
    if include_user_prompt_submit_hook:
        hooks_dictionary["UserPromptSubmit"] = [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            f"python3 /x/{USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME}"
                        ),
                    }
                ],
            }
        ]
    return {"hooks": hooks_dictionary}


def test_a_project_with_no_settings_file_is_missing_both_hooks(tmp_path) -> None:
    report = inspect_hook_registration_for_project(str(tmp_path))
    assert report.settings_file_exists is False
    assert report.stop_hook_is_registered is False
    assert report.user_prompt_submit_hook_is_registered is False
    assert report.is_ready_to_run is False


def test_a_fully_registered_project_is_ready(tmp_path) -> None:
    write_settings(str(tmp_path), build_settings_with_hooks())
    report = inspect_hook_registration_for_project(str(tmp_path))
    assert report.is_ready_to_run is True
    assert report.missing_hook_event_names == []


def test_a_missing_stop_hook_is_named_in_the_report(tmp_path) -> None:
    write_settings(str(tmp_path), build_settings_with_hooks(include_stop_hook=False))
    report = inspect_hook_registration_for_project(str(tmp_path))
    assert report.stop_hook_is_registered is False
    assert report.user_prompt_submit_hook_is_registered is True
    assert report.missing_hook_event_names == ["Stop"]
    assert report.is_ready_to_run is False


def test_a_missing_prompt_hook_is_named_in_the_report(tmp_path) -> None:
    write_settings(
        str(tmp_path), build_settings_with_hooks(include_user_prompt_submit_hook=False)
    )
    report = inspect_hook_registration_for_project(str(tmp_path))
    assert report.missing_hook_event_names == ["UserPromptSubmit"]


def test_a_hook_registered_for_the_wrong_script_does_not_count(tmp_path) -> None:
    """Another project's Stop hook is not this project's Stop hook."""
    write_settings(
        str(tmp_path),
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {"type": "command", "command": "python3 /x/some_other_hook.py"}
                        ],
                    }
                ]
            }
        },
    )
    report = inspect_hook_registration_for_project(str(tmp_path))
    assert report.stop_hook_is_registered is False


def test_this_projects_hook_is_found_alongside_unrelated_hooks(tmp_path) -> None:
    """Hooks coexist; the check must not require sole ownership of the event."""
    settings_dictionary = build_settings_with_hooks()
    settings_dictionary["hooks"]["Stop"].insert(
        0,
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "python3 /x/unrelated_hook.py"}],
        },
    )
    write_settings(str(tmp_path), settings_dictionary)
    assert inspect_hook_registration_for_project(str(tmp_path)).is_ready_to_run is True


def test_a_malformed_settings_file_reports_not_ready_rather_than_raising(
    tmp_path,
) -> None:
    claude_directory = os.path.join(str(tmp_path), ".claude")
    os.makedirs(claude_directory)
    with open(
        os.path.join(claude_directory, "settings.local.json"), "w", encoding="utf-8"
    ) as settings_file:
        settings_file.write("{ not json")

    report = inspect_hook_registration_for_project(str(tmp_path))

    assert report.settings_file_exists is True
    assert report.is_ready_to_run is False
    assert report.detail_text


def test_the_report_explains_what_to_do_when_something_is_missing(tmp_path) -> None:
    report = inspect_hook_registration_for_project(str(tmp_path))
    assert "settings.local.json" in report.detail_text
