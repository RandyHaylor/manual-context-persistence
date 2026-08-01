"""Which sessions is the user typing into, and which are mid-seeding?

The orchestrator drives several sessions the user never sees: the base session,
and the short-lived non-interactive calls that deliver a handoff. Every one of
them fires the prompt-submit hook, so without a gate the orchestrator's own words
end up in the log presented as the user's — which destroys the one property the
log exists to provide.

Two questions are recorded here, not one, because they stopped having the same
answer. "Are this session's replies handoffs?" is true for a user-facing session
from the moment it exists. "Is text arriving in it something the user typed?" is
false for as long as the orchestrator is still seeding it.

They used to be answered by a single membership check, with the branch registered
only after its seeding call returned. That worked while the seed was an output
contract the session merely acknowledged. Once the seed carried the next action, the
session's first act became the work itself — and its handoff was discarded,
because the session it came from had not been written down yet.

Default deny, in both directions: an unknown session is not user-facing, and a
registry that cannot be read denies too. Failing open would quietly readmit
exactly the content this exists to keep out.
"""
from __future__ import annotations

from context_handoff.project_state.project_state_directory import ProjectStateDirectory

USER_FACING_SESSION_REGISTRY_FILE_NAME = "user-facing-sessions.json"
REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME = "user_facing_session_identifiers"
SESSIONS_BEING_SEEDED_FIELD_NAME = "session_identifiers_being_seeded"


class UserFacingSessionRegistry:
    def __init__(self, project_directory: str) -> None:
        self._registry_document = ProjectStateDirectory(
            project_directory
        ).application_json_document(USER_FACING_SESSION_REGISTRY_FILE_NAME)

    @property
    def registry_file_path(self) -> str:
        return self._registry_document.file_path

    def _read_identifier_list(self, field_name: str) -> list[str]:
        stored_identifiers = self._registry_document.read_dictionary_or_default({}).get(
            field_name
        )
        if not isinstance(stored_identifiers, list):
            return []
        return [
            identifier
            for identifier in stored_identifiers
            if isinstance(identifier, str) and identifier.strip()
        ]

    def _write_both_lists(
        self,
        registered_session_identifiers: list[str],
        session_identifiers_being_seeded: list[str],
    ) -> None:
        self._registry_document.write_dictionary(
            {
                REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME: registered_session_identifiers,
                SESSIONS_BEING_SEEDED_FIELD_NAME: session_identifiers_being_seeded,
            }
        )

    def read_registered_session_identifiers(self) -> list[str]:
        return self._read_identifier_list(REGISTERED_SESSION_IDENTIFIERS_FIELD_NAME)

    def read_session_identifiers_being_seeded(self) -> list[str]:
        return self._read_identifier_list(SESSIONS_BEING_SEEDED_FIELD_NAME)

    def is_user_facing_session(self, session_identifier: str) -> bool:
        """Are this session's replies handoffs? True from the moment it exists."""
        return session_identifier in self.read_registered_session_identifiers()

    def is_session_accepting_user_prompts(self, session_identifier: str) -> bool:
        """Is text arriving in this session something the user typed?

        False while the orchestrator is still seeding it, because the seed
        travels the same path a typed prompt does.
        """
        return self.is_user_facing_session(
            session_identifier
        ) and session_identifier not in self.read_session_identifiers_being_seeded()

    def register_user_facing_session(self, session_identifier: str) -> None:
        if not session_identifier or not session_identifier.strip():
            return
        already_registered_identifiers = self.read_registered_session_identifiers()
        if session_identifier in already_registered_identifiers:
            return
        self._write_both_lists(
            already_registered_identifiers + [session_identifier],
            self.read_session_identifiers_being_seeded(),
        )

    def begin_seeding_user_facing_session(self, session_identifier: str) -> None:
        """Record the session before a word is sent to it.

        Registered, so its replies count as handoffs from its first turn, and
        marked as being seeded, so the seed itself is not logged as a prompt.
        """
        if not session_identifier or not session_identifier.strip():
            return
        already_registered_identifiers = self.read_registered_session_identifiers()
        if session_identifier not in already_registered_identifiers:
            already_registered_identifiers = already_registered_identifiers + [
                session_identifier
            ]
        sessions_being_seeded = self.read_session_identifiers_being_seeded()
        if session_identifier not in sessions_being_seeded:
            sessions_being_seeded = sessions_being_seeded + [session_identifier]
        self._write_both_lists(already_registered_identifiers, sessions_being_seeded)

    def finish_seeding_user_facing_session(self, session_identifier: str) -> None:
        """The orchestrator is done talking; anything further is the user."""
        self._write_both_lists(
            self.read_registered_session_identifiers(),
            [
                identifier
                for identifier in self.read_session_identifiers_being_seeded()
                if identifier != session_identifier
            ],
        )
