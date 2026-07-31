"""The project's state directory, and the documents inside it.

Every file this system keeps for a project lives under ``<project>/.claude``.
That convention is stated here once. Stores name the document they want and
otherwise know nothing about paths.

Reads are corruption-tolerant by design rather than by accident. The writers
include an agent emitting a handoff and hooks firing mid-turn, so a missing,
empty, or half-written file is an ordinary condition. Every failure to read
yields the caller's default, so no reader has to guard separately and none can
forget to.
"""
from __future__ import annotations

import json
import os
from typing import Any

PROJECT_STATE_DIRECTORY_NAME = ".claude"


class JsonDocumentFile:
    """One JSON object stored at a fixed path, read defensively."""

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path

    @property
    def file_path(self) -> str:
        return self._file_path

    def read_dictionary_or_default(self, default_value: dict[str, Any]) -> dict[str, Any]:
        """Return the stored object, or ``default_value`` if it cannot be used.

        Absent, empty, unparsable, and not-an-object all collapse to the same
        answer on purpose: to every caller so far they mean the same thing —
        there is nothing usable here.
        """
        if not os.path.exists(self._file_path):
            return default_value
        try:
            with open(self._file_path, "r", encoding="utf-8") as document_file:
                document_text = document_file.read().strip()
        except OSError:
            return default_value
        if not document_text:
            return default_value
        try:
            decoded_document = json.loads(document_text)
        except json.JSONDecodeError:
            return default_value
        return decoded_document if isinstance(decoded_document, dict) else default_value

    def holds_content(self) -> bool:
        """True when the document holds a usable object."""
        sentinel: dict[str, Any] = {}
        return self.read_dictionary_or_default(sentinel) is not sentinel

    def write_dictionary(self, document_dictionary: dict[str, Any]) -> str:
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as document_file:
            json.dump(document_dictionary, document_file, indent=2, ensure_ascii=False)
            document_file.write("\n")
        return self._file_path

    def write_empty(self) -> str:
        """Blank the document while leaving it in place.

        Emptying rather than deleting keeps "nothing pending" a single
        condition, so a watcher never has to distinguish that from "not created
        yet".
        """
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8"):
            pass
        return self._file_path


class ProjectStateDirectory:
    def __init__(self, project_directory: str) -> None:
        self._project_directory = project_directory

    @property
    def directory_path(self) -> str:
        return os.path.join(self._project_directory, PROJECT_STATE_DIRECTORY_NAME)

    def json_document(self, document_file_name: str) -> JsonDocumentFile:
        return JsonDocumentFile(os.path.join(self.directory_path, document_file_name))

    def subdirectory_path(self, subdirectory_name: str) -> str:
        """Return a path inside the state directory without creating anything."""
        return os.path.join(self.directory_path, subdirectory_name)
