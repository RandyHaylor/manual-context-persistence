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

import os
from dataclasses import dataclass
from typing import Any

from context_handoff.project_state.project_state_directory import ProjectStateDirectory

PROJECT_SETTINGS_FILE_NAME = "settings.local.json"

STOP_HOOK_EVENT_NAME = "Stop"
USER_PROMPT_SUBMIT_HOOK_EVENT_NAME = "UserPromptSubmit"
POST_TOOL_USE_HOOK_EVENT_NAME = "PostToolUse"

STOP_HOOK_SCRIPT_FILE_NAME = "context_to_keep_stop_hook.py"
USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME = "user_prompt_submit_capture_hook.py"
POST_TOOL_USE_HOOK_SCRIPT_FILE_NAME = "post_tool_use_handoff_reminder_hook.py"

# One place naming every hook this system needs, so adding one is a single entry
# here rather than a new field, a new branch, and a new place to forget.
HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME = {
    STOP_HOOK_EVENT_NAME: STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_EVENT_NAME: USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
    POST_TOOL_USE_HOOK_EVENT_NAME: POST_TOOL_USE_HOOK_SCRIPT_FILE_NAME,
}


@dataclass(frozen=True)
class HookRegistrationReport:
    settings_file_exists: bool
    registered_hook_event_names: frozenset
    detail_text: str

    @property
    def missing_hook_event_names(self) -> list[str]:
        return [
            hook_event_name
            for hook_event_name in HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME
            if hook_event_name not in self.registered_hook_event_names
        ]

    @property
    def is_ready_to_run(self) -> bool:
        return not self.missing_hook_event_names


def build_project_settings_path(project_directory: str) -> str:
    return (
        ProjectStateDirectory(project_directory)
        .harness_json_document(PROJECT_SETTINGS_FILE_NAME)
        .file_path
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
    settings_document = ProjectStateDirectory(project_directory).harness_json_document(
        PROJECT_SETTINGS_FILE_NAME
    )
    settings_path = settings_document.file_path
    settings_file_exists = os.path.exists(settings_path)

    if not settings_file_exists:
        return HookRegistrationReport(
            settings_file_exists=False,
            registered_hook_event_names=frozenset(),
            detail_text=(
                f"no {PROJECT_SETTINGS_FILE_NAME} at {settings_path}; the "
                + ", ".join(HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME)
                + " hooks are not registered there"
            ),
        )

    settings_dictionary = settings_document.read_dictionary_or_default({})
    if not settings_dictionary:
        return HookRegistrationReport(
            settings_file_exists=True,
            registered_hook_event_names=frozenset(),
            detail_text=(
                f"could not read usable settings from {PROJECT_SETTINGS_FILE_NAME} at "
                f"{settings_path}"
            ),
        )

    registered_hook_event_names = frozenset(
        hook_event_name
        for hook_event_name, script_file_name in (
            HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME.items()
        )
        if _event_registers_script(
            settings_dictionary, hook_event_name, script_file_name
        )
    )

    report = HookRegistrationReport(
        settings_file_exists=True,
        registered_hook_event_names=registered_hook_event_names,
        detail_text="",
    )
    if report.is_ready_to_run:
        detail_text = f"every hook is registered in {settings_path}"
    else:
        detail_text = (
            f"{PROJECT_SETTINGS_FILE_NAME} at {settings_path} is missing hooks for: "
            + ", ".join(report.missing_hook_event_names)
        )
    return HookRegistrationReport(
        settings_file_exists=True,
        registered_hook_event_names=registered_hook_event_names,
        detail_text=detail_text,
    )
