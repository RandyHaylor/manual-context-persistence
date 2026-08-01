"""Append-only log of what the user literally typed, at .claude/user-prompt-log.json.

The point of the log is that the handoff carries the user's own words rather
than an agent's paraphrase, so prompt text is stored byte for byte and is never
truncated. Pre-submission content — the agent output immediately before the
prompt — is context that makes a short reply like "yes" meaningful, so it is
kept but capped, and capped from the FRONT: the text nearest the prompt is the
part that gives it meaning.

Entries carry a consumed flag rather than being deleted. A prompt typed while
the agent was still working arrives after its turn's handoff has been built, and
the flag is what lets the next handoff pick it up without resending everything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from context_handoff.project_state.project_state_directory import ProjectStateDirectory

USER_PROMPT_LOG_FILE_NAME = "user-prompt-log.json"
LOG_ENTRIES_FIELD_NAME = "entries"
MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS = 2000


@dataclass(frozen=True)
class UserPromptLogEntry:
    entry_identifier: int
    session_identifier: str
    user_prompt_text: str
    pre_submission_content: str
    has_been_consumed: bool

    def to_json_dictionary(self) -> dict[str, Any]:
        return {
            "entry_identifier": self.entry_identifier,
            "session_identifier": self.session_identifier,
            "user_prompt_text": self.user_prompt_text,
            "pre_submission_content": self.pre_submission_content,
            "has_been_consumed": self.has_been_consumed,
        }

    @classmethod
    def from_json_dictionary(cls, entry_dictionary: dict[str, Any]) -> "UserPromptLogEntry":
        return cls(
            entry_identifier=int(entry_dictionary["entry_identifier"]),
            session_identifier=str(entry_dictionary["session_identifier"]),
            user_prompt_text=str(entry_dictionary["user_prompt_text"]),
            pre_submission_content=str(entry_dictionary.get("pre_submission_content", "")),
            has_been_consumed=bool(entry_dictionary.get("has_been_consumed", False)),
        )


def cap_pre_submission_content(pre_submission_content: str) -> str:
    """Keep only the tail, which is the text closest to the prompt."""
    if len(pre_submission_content) <= MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS:
        return pre_submission_content
    return pre_submission_content[-MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS:]


class UserPromptLogStore:
    def __init__(self, project_directory: str) -> None:
        self._log_document = ProjectStateDirectory(
            project_directory
        ).application_json_document(USER_PROMPT_LOG_FILE_NAME)

    @property
    def user_prompt_log_file_path(self) -> str:
        return self._log_document.file_path

    def _read_all_entries(self) -> list[UserPromptLogEntry]:
        """Return every logged entry, skipping any that cannot be understood.

        An entry the current build cannot parse is dropped rather than raised
        on: the caller is a hook, and a hook that raises loses the prompt it
        was invoked to record.
        """
        raw_entries = self._log_document.read_dictionary_or_default({}).get(
            LOG_ENTRIES_FIELD_NAME
        )
        if not isinstance(raw_entries, list):
            return []
        parsed_entries: list[UserPromptLogEntry] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            try:
                parsed_entries.append(UserPromptLogEntry.from_json_dictionary(raw_entry))
            except (KeyError, TypeError, ValueError):
                continue
        return parsed_entries

    def _write_all_entries(self, entries: list[UserPromptLogEntry]) -> None:
        self._log_document.write_dictionary(
            {LOG_ENTRIES_FIELD_NAME: [entry.to_json_dictionary() for entry in entries]}
        )

    def append_user_prompt_entry(
        self,
        session_identifier: str,
        user_prompt_text: str,
        pre_submission_content: Optional[str] = None,
    ) -> UserPromptLogEntry:
        existing_entries = self._read_all_entries()
        next_entry_identifier = (
            max((entry.entry_identifier for entry in existing_entries), default=-1) + 1
        )
        new_entry = UserPromptLogEntry(
            entry_identifier=next_entry_identifier,
            session_identifier=session_identifier,
            user_prompt_text=user_prompt_text,
            pre_submission_content=cap_pre_submission_content(
                pre_submission_content or ""
            ),
            has_been_consumed=False,
        )
        self._write_all_entries(existing_entries + [new_entry])
        return new_entry

    def read_entries_for_session(
        self, session_identifier: str
    ) -> list[UserPromptLogEntry]:
        return [
            entry
            for entry in self._read_all_entries()
            if entry.session_identifier == session_identifier
        ]

    def read_unconsumed_entries_for_session(
        self, session_identifier: str
    ) -> list[UserPromptLogEntry]:
        return [
            entry
            for entry in self.read_entries_for_session(session_identifier)
            if not entry.has_been_consumed
        ]

    def read_all_unconsumed_entries(self) -> list[UserPromptLogEntry]:
        """Return unconsumed entries across every session, in submission order.

        Rotation uses this rather than the per-session view: a prompt typed
        while a swap was under way belongs to the session the user was looking
        at a moment ago, and scoping strictly to the current branch would strand
        it in the log forever.
        """
        return [entry for entry in self._read_all_entries() if not entry.has_been_consumed]

    def mark_entries_consumed(self, entry_identifiers: Iterable[int]) -> None:
        entry_identifiers_to_consume = set(entry_identifiers)
        if not entry_identifiers_to_consume:
            return
        updated_entries = [
            UserPromptLogEntry(
                entry_identifier=entry.entry_identifier,
                session_identifier=entry.session_identifier,
                user_prompt_text=entry.user_prompt_text,
                pre_submission_content=entry.pre_submission_content,
                has_been_consumed=(
                    entry.has_been_consumed
                    or entry.entry_identifier in entry_identifiers_to_consume
                ),
            )
            for entry in self._read_all_entries()
        ]
        self._write_all_entries(updated_entries)
