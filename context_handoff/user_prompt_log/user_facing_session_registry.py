"""Which sessions is the user actually typing into?

The orchestrator drives several sessions the user never sees: the base session,
and the short-lived non-interactive calls that seed a branch or deliver a
handoff. Every one of them fires the prompt-submit hook, so without a gate the
orchestrator's own words end up in the log presented as the user's — which
destroys the one property the log exists to provide.

The gate is membership, mirroring the implementation the spec names as the
reference. The orchestrator registers a branch only after its seeding call has
finished, so the seed is not logged but everything the user subsequently types
into that branch is.

Default deny, in both directions: an unknown session is not user-facing, and a
registry that cannot be read denies too. Failing open would quietly readmit
exactly the content this exists to keep out.
"""
from __future__ import annotations

import json
import os
from typing import Any

CLAUDE_PROJECT_SUBDIRECTORY_NAME = ".claude"
USER_FACING_SESSION_REGISTRY_FILE_NAME = "context-handoff-user-facing-sessions.json"
REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME = "user_facing_session_identifiers"


class UserFacingSessionRegistry:
    def __init__(self, project_directory: str) -> None:
        self._project_directory = project_directory

    @property
    def claude_directory(self) -> str:
        return os.path.join(self._project_directory, CLAUDE_PROJECT_SUBDIRECTORY_NAME)

    @property
    def registry_file_path(self) -> str:
        return os.path.join(
            self.claude_directory, USER_FACING_SESSION_REGISTRY_FILE_NAME
        )

    def read_registered_session_identifiers(self) -> list[str]:
        if not os.path.exists(self.registry_file_path):
            return []
        try:
            with open(self.registry_file_path, "r", encoding="utf-8") as registry_file:
                registry_content: Any = json.load(registry_file)
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(registry_content, dict):
            return []
        registered_identifiers = registry_content.get(
            REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME
        )
        if not isinstance(registered_identifiers, list):
            return []
        return [
            identifier
            for identifier in registered_identifiers
            if isinstance(identifier, str) and identifier.strip()
        ]

    def is_user_facing_session(self, session_identifier: str) -> bool:
        return session_identifier in self.read_registered_session_identifiers()

    def register_user_facing_session(self, session_identifier: str) -> None:
        if not session_identifier or not session_identifier.strip():
            return
        already_registered_identifiers = self.read_registered_session_identifiers()
        if session_identifier in already_registered_identifiers:
            return
        os.makedirs(self.claude_directory, exist_ok=True)
        with open(self.registry_file_path, "w", encoding="utf-8") as registry_file:
            json.dump(
                {
                    REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME: (
                        already_registered_identifiers + [session_identifier]
                    )
                },
                registry_file,
                indent=2,
            )
            registry_file.write("\n")
