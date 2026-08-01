"""Deploy everything the hooks need to run, to one fixed location, on every run.

A project's ``settings.local.json`` names an absolute path to each hook script,
because the harness runs those scripts and the project is not where they live.
Pointing that path at this repository would tie every project's settings file to
wherever the repository sat on the day it was installed, and moving or renaming
the repository would leave the path behind.

So the deployed location is ``~/.claude/manual-context-persistence``, and it holds
both the scripts and the package they import:

    ~/.claude/manual-context-persistence/
        hooks/                 the two scripts the harness runs
        context_handoff/       the package those scripts import

The package has to be there, not only the scripts. Each script puts its own
parent's parent on ``sys.path`` and imports ``context_handoff`` from it, so a
deployment of scripts alone leaves them pointing at a directory with no package
in it — they die at import, before any handler code, and the harness reports a
non-blocking hook error while the session carries on looking healthy. That is how
this was first shipped, and the run that found it captured nothing at all.

Deployment overwrites unconditionally rather than filling in what is missing.
Copying only absent files would leave a deployed copy running after the source had
changed, and the two would drift with nothing to say so.
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
    HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME,
)

DEPLOYED_HOOK_SCRIPTS_DIRECTORY_NAME = "hooks"
DEPLOYED_PACKAGE_DIRECTORY_NAME = "context_handoff"

# Deploying exactly what gets registered, from the one list that names them, so a
# script can never be registered without also being deployed.
HOOK_SCRIPT_FILE_NAMES_TO_DEPLOY = tuple(HOOK_SCRIPT_FILE_NAMES_BY_EVENT_NAME.values())

# Compiled bytecode belongs to the interpreter that wrote it, not to a copy.
COPY_IGNORE_PATTERNS = shutil.ignore_patterns("__pycache__", "*.pyc")


class HookRuntimeSourceMissingError(RuntimeError):
    """Part of the hook runtime is absent from the source, so it cannot deploy.

    Raised rather than skipped: continuing would register a command pointing at a
    runtime that cannot start, and the failure would then surface as a session
    that silently captures nothing.
    """


@dataclass(frozen=True)
class HookRuntimeDeploymentResult:
    deployed_runtime_directory: str
    deployed_hook_scripts_directory: str
    deployed_hook_script_file_names: list[str] = field(default_factory=list)

    @property
    def detail_text(self) -> str:
        return (
            f"{', '.join(self.deployed_hook_script_file_names)} and "
            f"{DEPLOYED_PACKAGE_DIRECTORY_NAME} deployed to "
            f"{self.deployed_runtime_directory}"
        )


def resolve_deployed_runtime_directory() -> str:
    """``~/.claude/manual-context-persistence`` — what the hooks run out of."""
    return user_application_directory_path()


def build_deployed_hook_scripts_directory(deployed_runtime_directory: str) -> str:
    return os.path.join(
        deployed_runtime_directory, DEPLOYED_HOOK_SCRIPTS_DIRECTORY_NAME
    )


def deploy_hook_runtime_overwriting_existing(
    repository_root_directory: str,
    deployed_runtime_directory: Optional[str] = None,
) -> HookRuntimeDeploymentResult:
    """Copy the scripts and the package they import over whatever is deployed.

    The destination is injectable so a test can deploy into a temporary directory
    rather than into the developer's own home.
    """
    destination_runtime_directory = (
        deployed_runtime_directory or resolve_deployed_runtime_directory()
    )
    destination_hook_scripts_directory = build_deployed_hook_scripts_directory(
        destination_runtime_directory
    )
    os.makedirs(destination_hook_scripts_directory, exist_ok=True)

    source_package_directory = os.path.join(
        repository_root_directory, DEPLOYED_PACKAGE_DIRECTORY_NAME
    )
    if not os.path.isdir(source_package_directory):
        raise HookRuntimeSourceMissingError(
            f"{DEPLOYED_PACKAGE_DIRECTORY_NAME} is not in {repository_root_directory}"
        )
    shutil.copytree(
        source_package_directory,
        os.path.join(destination_runtime_directory, DEPLOYED_PACKAGE_DIRECTORY_NAME),
        ignore=COPY_IGNORE_PATTERNS,
        dirs_exist_ok=True,
    )

    source_hook_scripts_directory = os.path.join(
        repository_root_directory, DEPLOYED_HOOK_SCRIPTS_DIRECTORY_NAME
    )
    deployed_hook_script_file_names: list[str] = []
    for hook_script_file_name in HOOK_SCRIPT_FILE_NAMES_TO_DEPLOY:
        source_path = os.path.join(source_hook_scripts_directory, hook_script_file_name)
        if not os.path.exists(source_path):
            raise HookRuntimeSourceMissingError(
                f"{hook_script_file_name} is not in {source_hook_scripts_directory}"
            )
        # copy2 rather than copy: the mode comes along, so a script that is
        # executable in the source stays executable once deployed.
        shutil.copy2(
            source_path,
            os.path.join(destination_hook_scripts_directory, hook_script_file_name),
        )
        deployed_hook_script_file_names.append(hook_script_file_name)

    return HookRuntimeDeploymentResult(
        deployed_runtime_directory=destination_runtime_directory,
        deployed_hook_scripts_directory=destination_hook_scripts_directory,
        deployed_hook_script_file_names=deployed_hook_script_file_names,
    )
