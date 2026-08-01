"""Write this system's two hooks into a project's ``settings.local.json``.

Installation merges rather than replaces. That file belongs to the harness and
may already carry an operator's own settings, permissions, and hooks for other
tools, so this adds our two entries and leaves every other key and every other
hook exactly as it found them. Hooks for the same event coexist, so an existing
Stop hook belonging to something else is preserved alongside ours.

Registration is by absolute path to the script in this repository, because the
project being worked in is a different directory from the one this system is
installed in. The path is passed in rather than derived here so that the entry
point owns the question of where it lives.

Installing twice is a no-op: an event that already registers our script by name
is left alone, so a re-run cannot accumulate duplicate entries.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from context_handoff.project_state.project_state_directory import ProjectStateDirectory
from context_handoff.startup.hook_registration_preflight import (
    PROJECT_SETTINGS_FILE_NAME,
    STOP_HOOK_EVENT_NAME,
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_EVENT_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
)

HOOKS_SECTION_FIELD_NAME = "hooks"
HOOK_COMMAND_TYPE_NAME = "command"

HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME = {
    STOP_HOOK_EVENT_NAME: STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_EVENT_NAME: USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
}


@dataclass(frozen=True)
class HookInstallationResult:
    settings_file_path: str
    installed_hook_event_names: list[str]
    already_registered_hook_event_names: list[str]

    @property
    def detail_text(self) -> str:
        if not self.installed_hook_event_names:
            return f"hooks were already registered in {self.settings_file_path}"
        return (
            f"registered {', '.join(self.installed_hook_event_names)} in "
            f"{self.settings_file_path}"
        )


def build_hook_command_text(hook_scripts_directory: str, script_file_name: str) -> str:
    """The command the harness will run for one hook.

    Absolute, and quoted, so a path containing a space still runs.
    """
    script_path = os.path.join(os.path.abspath(hook_scripts_directory), script_file_name)
    return f'python3 "{script_path}"'


def _event_already_registers_script(
    event_entries: Any, script_file_name: str
) -> bool:
    if not isinstance(event_entries, list):
        return False
    for event_entry in event_entries:
        if not isinstance(event_entry, dict):
            continue
        for hook_definition in event_entry.get(HOOKS_SECTION_FIELD_NAME, []) or []:
            if not isinstance(hook_definition, dict):
                continue
            command_text = hook_definition.get(HOOK_COMMAND_TYPE_NAME)
            if isinstance(command_text, str) and script_file_name in command_text:
                return True
    return False


def install_context_handoff_hooks_into_project_settings(
    project_directory: str, hook_scripts_directory: str
) -> HookInstallationResult:
    """Add any of our hooks that are missing, preserving everything else."""
    settings_document = ProjectStateDirectory(project_directory).harness_json_document(
        PROJECT_SETTINGS_FILE_NAME
    )
    settings_dictionary = settings_document.read_dictionary_or_default({})

    hooks_section = settings_dictionary.get(HOOKS_SECTION_FIELD_NAME)
    if not isinstance(hooks_section, dict):
        hooks_section = {}

    installed_hook_event_names: list[str] = []
    already_registered_hook_event_names: list[str] = []

    for hook_event_name, script_file_name in HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME.items():
        existing_event_entries = hooks_section.get(hook_event_name)
        if _event_already_registers_script(existing_event_entries, script_file_name):
            already_registered_hook_event_names.append(hook_event_name)
            continue
        event_entries = (
            list(existing_event_entries)
            if isinstance(existing_event_entries, list)
            else []
        )
        event_entries.append(
            {
                HOOKS_SECTION_FIELD_NAME: [
                    {
                        "type": HOOK_COMMAND_TYPE_NAME,
                        HOOK_COMMAND_TYPE_NAME: build_hook_command_text(
                            hook_scripts_directory, script_file_name
                        ),
                    }
                ]
            }
        )
        hooks_section[hook_event_name] = event_entries
        installed_hook_event_names.append(hook_event_name)

    if installed_hook_event_names:
        settings_dictionary[HOOKS_SECTION_FIELD_NAME] = hooks_section
        settings_document.write_dictionary(settings_dictionary)

    return HookInstallationResult(
        settings_file_path=settings_document.file_path,
        installed_hook_event_names=installed_hook_event_names,
        already_registered_hook_event_names=already_registered_hook_event_names,
    )
