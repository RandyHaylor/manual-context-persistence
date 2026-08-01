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

from context_handoff.project_state.project_state_directory import ProjectStateDirectory

USER_FACING_SESSION_REGISTRY_FILE_NAME = "user-facing-sessions.json"
REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME = "user_facing_session_identifiers"


class UserFacingSessionRegistry:
    def __init__(self, project_directory: str) -> None:
        self._registry_document = ProjectStateDirectory(
            project_directory
        ).application_json_document(USER_FACING_SESSION_REGISTRY_FILE_NAME)

    @property
    def registry_file_path(self) -> str:
        return self._registry_document.file_path

    def read_registered_session_identifiers(self) -> list[str]:
        registered_identifiers = self._registry_document.read_dictionary_or_default(
            {}
        ).get(REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME)
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
        self._registry_document.write_dictionary(
            {
                REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME: (
                    already_registered_identifiers + [session_identifier]
                )
            }
        )
