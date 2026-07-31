"""The on-disk context-to-keep file, and its rotation into a history folder.

Layout under the project directory:

    .claude/context-to-keep.json
    .claude/context-to-keep-history/context-to-keep-<timestamp>.json

The pending file is the handoff channel between the Stop hook that writes it
and the turn loop that consumes it. After consumption it is rotated into
history and left empty rather than deleted, so "file exists but is empty"
unambiguously means "nothing pending" and the watcher never has to distinguish
that from a file that has not been created yet.

The timestamp generator is injected so callers can make rotation deterministic
in tests.
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Callable, Optional

from context_handoff.project_state.project_state_directory import ProjectStateDirectory

from .context_to_keep_package import (
    ContextToKeepPackage,
    InvalidContextToKeepPackageError,
    parse_context_to_keep_package,
)

CONTEXT_TO_KEEP_FILE_NAME = "context-to-keep.json"
CONTEXT_TO_KEEP_HISTORY_DIRECTORY_NAME = "context-to-keep-history"
ROTATED_AT_TIMESTAMP_FIELD_NAME = "rotated_at_timestamp"


def generate_utc_timestamp_text() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ContextToKeepFileStore:
    def __init__(
        self,
        project_directory: str,
        generate_timestamp_text: Optional[Callable[[], str]] = None,
    ) -> None:
        project_state_directory = ProjectStateDirectory(project_directory)
        self._pending_document = project_state_directory.json_document(
            CONTEXT_TO_KEEP_FILE_NAME
        )
        self._history_directory = project_state_directory.subdirectory_path(
            CONTEXT_TO_KEEP_HISTORY_DIRECTORY_NAME
        )
        self._generate_timestamp_text = (
            generate_timestamp_text or generate_utc_timestamp_text
        )

    @property
    def context_to_keep_file_path(self) -> str:
        return self._pending_document.file_path

    @property
    def context_to_keep_history_directory(self) -> str:
        return self._history_directory

    def read_pending_context_to_keep_package(self) -> Optional[ContextToKeepPackage]:
        """Return the pending package, or None when there is nothing usable.

        A malformed package reads as None rather than raising: the writer is an
        agent, and one bad package must not stall the turn loop.
        """
        pending_dictionary = self._pending_document.read_dictionary_or_default({})
        if not pending_dictionary:
            return None
        try:
            return parse_context_to_keep_package(pending_dictionary)
        except InvalidContextToKeepPackageError:
            return None

    def has_pending_context_to_keep(self) -> bool:
        return self.read_pending_context_to_keep_package() is not None

    def write_pending_context_to_keep_package(
        self, package: ContextToKeepPackage
    ) -> str:
        return self._pending_document.write_dictionary(package.to_json_dictionary())

    def _allocate_unused_history_path(self, timestamp_text: str) -> str:
        """Return a history path that does not already exist.

        Two turns can land inside one timestamp tick; a plain overwrite would
        silently discard the earlier handoff.
        """
        base_history_path = os.path.join(
            self.context_to_keep_history_directory,
            f"context-to-keep-{timestamp_text}.json",
        )
        if not os.path.exists(base_history_path):
            return base_history_path
        collision_index = 2
        while True:
            candidate_history_path = os.path.join(
                self.context_to_keep_history_directory,
                f"context-to-keep-{timestamp_text}-{collision_index}.json",
            )
            if not os.path.exists(candidate_history_path):
                return candidate_history_path
            collision_index += 1

    def rotate_pending_context_to_keep_into_history(self) -> str:
        """Archive the pending package and leave an empty file behind.

        Raises ``FileNotFoundError`` when nothing is pending: rotating nothing
        would create an empty archive entry and mask the real problem.
        """
        pending_dictionary = self._pending_document.read_dictionary_or_default({})
        if not pending_dictionary:
            raise FileNotFoundError(
                f"nothing pending to rotate at {self.context_to_keep_file_path}"
            )

        os.makedirs(self.context_to_keep_history_directory, exist_ok=True)
        history_path = self._allocate_unused_history_path(self._generate_timestamp_text())

        archived_dictionary = dict(pending_dictionary)
        archived_dictionary[ROTATED_AT_TIMESTAMP_FIELD_NAME] = os.path.basename(
            history_path
        )[len("context-to-keep-") : -len(".json")]
        with open(history_path, "w", encoding="utf-8") as history_file:
            json.dump(archived_dictionary, history_file, indent=2, ensure_ascii=False)
            history_file.write("\n")

        self._pending_document.write_empty()
        return history_path
