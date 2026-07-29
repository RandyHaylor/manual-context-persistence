"""Check that both context-handoff hooks are registered for a project.

Without them nothing is captured, and the failure is silent: the loop would
keep rotating turns that hand off nothing at all. So this runs before the loop
starts and names exactly what is missing.

The check looks for this project's own hook scripts by filename. Registration
for the same event by some other tool does not count, and does not conflict
either — hooks coexist, so finding an unrelated Stop hook alongside ours is
fine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

CLAUDE_PROJECT_SUBDIRECTORY_NAME = ".claude"
PROJECT_SETTINGS_FILE_NAME = "settings.local.json"

STOP_HOOK_EVENT_NAME = "Stop"
USER_PROMPT_SUBMIT_HOOK_EVENT_NAME = "UserPromptSubmit"

STOP_HOOK_SCRIPT_FILE_NAME = "context_to_keep_stop_hook.py"
USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME = "user_prompt_submit_capture_hook.py"


@dataclass(frozen=True)
class HookRegistrationReport:
    settings_file_exists: bool
    stop_hook_is_registered: bool
    user_prompt_submit_hook_is_registered: bool
    detail_text: str

    @property
    def missing_hook_event_names(self) -> list[str]:
        missing_event_names: list[str] = []
        if not self.stop_hook_is_registered:
            missing_event_names.append(STOP_HOOK_EVENT_NAME)
        if not self.user_prompt_submit_hook_is_registered:
            missing_event_names.append(USER_PROMPT_SUBMIT_HOOK_EVENT_NAME)
        return missing_event_names

    @property
    def is_ready_to_run(self) -> bool:
        return not self.missing_hook_event_names


def build_project_settings_path(project_directory: str) -> str:
    return os.path.join(
        project_directory, CLAUDE_PROJECT_SUBDIRECTORY_NAME, PROJECT_SETTINGS_FILE_NAME
    )


def _event_registers_script(
    settings_dictionary: dict[str, Any], hook_event_name: str, script_file_name: str
) -> bool:
    hooks_section = settings_dictionary.get("hooks")
    if not isinstance(hooks_section, dict):
        return False
    event_entries = hooks_section.get(hook_event_name)
    if not isinstance(event_entries, list):
        return False
    for event_entry in event_entries:
        if not isinstance(event_entry, dict):
            continue
        for hook_definition in event_entry.get("hooks", []) or []:
            if not isinstance(hook_definition, dict):
                continue
            command_text = hook_definition.get("command")
            if isinstance(command_text, str) and script_file_name in command_text:
                return True
    return False


def inspect_hook_registration_for_project(
    project_directory: str,
) -> HookRegistrationReport:
    settings_path = build_project_settings_path(project_directory)

    if not os.path.exists(settings_path):
        return HookRegistrationReport(
            settings_file_exists=False,
            stop_hook_is_registered=False,
            user_prompt_submit_hook_is_registered=False,
            detail_text=(
                f"no {PROJECT_SETTINGS_FILE_NAME} at {settings_path}; register the "
                f"{STOP_HOOK_EVENT_NAME} and {USER_PROMPT_SUBMIT_HOOK_EVENT_NAME} hooks "
                "there before starting the turn loop"
            ),
        )

    try:
        with open(settings_path, "r", encoding="utf-8") as settings_file:
            settings_dictionary = json.load(settings_file)
    except (json.JSONDecodeError, OSError) as read_error:
        return HookRegistrationReport(
            settings_file_exists=True,
            stop_hook_is_registered=False,
            user_prompt_submit_hook_is_registered=False,
            detail_text=(
                f"could not read {PROJECT_SETTINGS_FILE_NAME} at {settings_path}: "
                f"{read_error}"
            ),
        )
    if not isinstance(settings_dictionary, dict):
        return HookRegistrationReport(
            settings_file_exists=True,
            stop_hook_is_registered=False,
            user_prompt_submit_hook_is_registered=False,
            detail_text=(
                f"{PROJECT_SETTINGS_FILE_NAME} at {settings_path} is not a JSON object"
            ),
        )

    stop_hook_is_registered = _event_registers_script(
        settings_dictionary, STOP_HOOK_EVENT_NAME, STOP_HOOK_SCRIPT_FILE_NAME
    )
    user_prompt_submit_hook_is_registered = _event_registers_script(
        settings_dictionary,
        USER_PROMPT_SUBMIT_HOOK_EVENT_NAME,
        USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
    )

    report = HookRegistrationReport(
        settings_file_exists=True,
        stop_hook_is_registered=stop_hook_is_registered,
        user_prompt_submit_hook_is_registered=user_prompt_submit_hook_is_registered,
        detail_text="",
    )
    if report.is_ready_to_run:
        detail_text = f"both hooks are registered in {settings_path}"
    else:
        detail_text = (
            f"{PROJECT_SETTINGS_FILE_NAME} at {settings_path} is missing hooks for: "
            + ", ".join(report.missing_hook_event_names)
        )
    return HookRegistrationReport(
        settings_file_exists=True,
        stop_hook_is_registered=stop_hook_is_registered,
        user_prompt_submit_hook_is_registered=user_prompt_submit_hook_is_registered,
        detail_text=detail_text,
    )
