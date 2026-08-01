"""The project's settings for this system, stored in our own state folder.

Three settings, all about the project's git repository, because the only choice
this system currently offers an operator is whether a branch must commit its
work before handing off. Every setting has a default that is safe for a project
with no repository at all, so an absent or unreadable settings file is an
ordinary starting condition rather than an error.

``require_git_commit`` defaults to false: a project that does not use git must
work untouched, and a preamble asking for a commit in a directory with no
repository would send the agent chasing an impossible instruction.

``git_repository_is_local_only`` exists so that a repository with no remote is a
stated fact rather than something inferred from a missing URL. Inferring it
would make "the operator has not filled this in yet" and "there is deliberately
no remote" the same state, and they call for different behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from context_handoff.project_state.project_state_directory import ProjectStateDirectory

CONTEXT_HANDOFF_SETTINGS_FILE_NAME = "settings.json"

REQUIRE_GIT_COMMIT_FIELD_NAME = "require_git_commit"
GIT_REPOSITORY_URL_FIELD_NAME = "git_repository_url"
GIT_REPOSITORY_IS_LOCAL_ONLY_FIELD_NAME = "git_repository_is_local_only"


@dataclass(frozen=True)
class ContextHandoffSettings:
    """What the operator chose, independent of where it was written down."""

    require_git_commit: bool = False
    git_repository_url: Optional[str] = None
    git_repository_is_local_only: bool = False

    def to_json_dictionary(self) -> dict[str, Any]:
        return {
            REQUIRE_GIT_COMMIT_FIELD_NAME: self.require_git_commit,
            GIT_REPOSITORY_URL_FIELD_NAME: self.git_repository_url,
            GIT_REPOSITORY_IS_LOCAL_ONLY_FIELD_NAME: self.git_repository_is_local_only,
        }

    def with_require_git_commit_override(
        self, require_git_commit_override: Optional[bool]
    ) -> "ContextHandoffSettings":
        """Apply a command-line override, or return self when none was given.

        ``None`` means the operator did not pass the flag at all, which is
        different from passing it as false — so only a stated override replaces
        what the file says.
        """
        if require_git_commit_override is None:
            return self
        return ContextHandoffSettings(
            require_git_commit=require_git_commit_override,
            git_repository_url=self.git_repository_url,
            git_repository_is_local_only=self.git_repository_is_local_only,
        )


def _read_boolean_or_default(
    settings_dictionary: dict[str, Any], field_name: str, default_value: bool
) -> bool:
    # Only a real boolean counts. A string "true" from a hand-edited file is
    # ambiguous enough that guessing is worse than falling back to the default.
    stored_value = settings_dictionary.get(field_name)
    return stored_value if isinstance(stored_value, bool) else default_value


def _read_optional_text(
    settings_dictionary: dict[str, Any], field_name: str
) -> Optional[str]:
    stored_value = settings_dictionary.get(field_name)
    if not isinstance(stored_value, str):
        return None
    stripped_value = stored_value.strip()
    return stripped_value or None


def parse_context_handoff_settings(
    settings_dictionary: dict[str, Any],
) -> ContextHandoffSettings:
    """Read what is usable and default the rest, never raising."""
    default_settings = ContextHandoffSettings()
    return ContextHandoffSettings(
        require_git_commit=_read_boolean_or_default(
            settings_dictionary,
            REQUIRE_GIT_COMMIT_FIELD_NAME,
            default_settings.require_git_commit,
        ),
        git_repository_url=_read_optional_text(
            settings_dictionary, GIT_REPOSITORY_URL_FIELD_NAME
        ),
        git_repository_is_local_only=_read_boolean_or_default(
            settings_dictionary,
            GIT_REPOSITORY_IS_LOCAL_ONLY_FIELD_NAME,
            default_settings.git_repository_is_local_only,
        ),
    )


class ContextHandoffSettingsStore:
    def __init__(self, project_directory: str) -> None:
        self._settings_document = ProjectStateDirectory(
            project_directory
        ).application_json_document(CONTEXT_HANDOFF_SETTINGS_FILE_NAME)

    @property
    def settings_file_path(self) -> str:
        return self._settings_document.file_path

    def settings_file_exists(self) -> bool:
        return self._settings_document.exists()

    def read_settings(self) -> ContextHandoffSettings:
        return parse_context_handoff_settings(
            self._settings_document.read_dictionary_or_default({})
        )

    def write_settings(self, settings: ContextHandoffSettings) -> str:
        return self._settings_document.write_dictionary(settings.to_json_dictionary())

    def write_default_settings_if_absent(self) -> bool:
        """Create the file with defaults, and report whether it was created.

        Absence is the only trigger. An existing file is left exactly as it is,
        including one that cannot be parsed — overwriting that would destroy
        settings the operator meant to keep in order to fix a typo for them.
        """
        if self._settings_document.exists():
            return False
        self.write_settings(ContextHandoffSettings())
        return True
