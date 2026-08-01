"""Deploy the hook scripts to one fixed location, on every run.

A project's ``settings.local.json`` names an absolute path to each hook script,
because the harness runs those scripts and the project is not where they live.
Pointing that path at this repository would tie every project's settings file to
wherever the repository sat on the day it was installed, and moving or renaming
the repository would leave the path behind.

So the scripts are deployed to ``~/.claude/manual-context-persistence/hooks``
and referenced there. That path is the same for every project and does not move
with the source.

Deployment overwrites unconditionally rather than filling in what is missing.
Copying only absent files would leave a deployed copy running after the script in
this repository had changed, and the two would drift with nothing to say so.
Overwriting means the deployed scripts are whatever this repository currently
holds, every time the app starts — which also repairs a deleted or half-finished
install without treating that as a separate case.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

from context_handoff.project_state.project_state_directory import (
    user_application_directory_path,
)
from context_handoff.startup.hook_registration_preflight import (
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
)

DEPLOYED_HOOK_SCRIPTS_DIRECTORY_NAME = "hooks"

HOOK_SCRIPT_FILE_NAMES_TO_DEPLOY = (
    STOP_HOOK_SCRIPT_FILE_NAME,
    USER_PROMPT_SUBMIT_HOOK_SCRIPT_FILE_NAME,
)


class HookScriptSourceMissingError(RuntimeError):
    """A hook script is absent from this repository, so it cannot be deployed.

    Raised rather than skipped: continuing would register a command pointing at a
    script that does not exist, and the failure would then surface as a session
    that silently captures nothing.
    """


@dataclass(frozen=True)
class HookScriptDeploymentResult:
    deployed_hook_scripts_directory: str
    deployed_hook_script_file_names: list[str] = field(default_factory=list)

    @property
    def detail_text(self) -> str:
        return (
            f"{', '.join(self.deployed_hook_script_file_names)} deployed to "
            f"{self.deployed_hook_scripts_directory}"
        )


def resolve_deployed_hook_scripts_directory() -> str:
    """``~/.claude/manual-context-persistence/hooks`` — where the harness looks."""
    return os.path.join(
        user_application_directory_path(), DEPLOYED_HOOK_SCRIPTS_DIRECTORY_NAME
    )


def deploy_hook_scripts_overwriting_existing(
    hook_scripts_source_directory: str,
    deployed_hook_scripts_directory: Optional[str] = None,
) -> HookScriptDeploymentResult:
    """Copy every hook script over whatever is deployed, and report what it wrote.

    The destination is injectable so a test can deploy into a temporary directory
    rather than into the developer's own home.
    """
    destination_directory = (
        deployed_hook_scripts_directory or resolve_deployed_hook_scripts_directory()
    )
    os.makedirs(destination_directory, exist_ok=True)

    deployed_hook_script_file_names: list[str] = []
    for hook_script_file_name in HOOK_SCRIPT_FILE_NAMES_TO_DEPLOY:
        source_path = os.path.join(hook_scripts_source_directory, hook_script_file_name)
        if not os.path.exists(source_path):
            raise HookScriptSourceMissingError(
                f"{hook_script_file_name} is not in {hook_scripts_source_directory}"
            )
        # copy2 rather than copy: the mode comes along, so a script that is
        # executable in the repository stays executable once deployed.
        shutil.copy2(
            source_path, os.path.join(destination_directory, hook_script_file_name)
        )
        deployed_hook_script_file_names.append(hook_script_file_name)

    return HookScriptDeploymentResult(
        deployed_hook_scripts_directory=destination_directory,
        deployed_hook_script_file_names=deployed_hook_script_file_names,
    )
