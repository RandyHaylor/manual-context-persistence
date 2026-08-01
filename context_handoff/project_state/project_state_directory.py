"""The project's state directory, and the documents inside it.

Two locations, and the distinction between them is the point of this module.

``.claude`` is the harness's own directory. Exactly one file there concerns
this system: ``settings.local.json``, where the harness reads its hook
registrations from. We write that file to install our hooks, and it belongs to
the harness the rest of the time, so it is addressed on its own.

Everything else this system keeps lives one level down, in
``.claude/manual-context-persistence``, named for this repository. Keeping our
documents in their own folder means nothing we write can collide with a file the
harness or another tool puts in ``.claude``, and a reader can see at a glance
which files are ours.

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

HARNESS_STATE_DIRECTORY_NAME = ".claude"
APPLICATION_STATE_DIRECTORY_NAME = "manual-context-persistence"


def user_harness_directory_path() -> str:
    """``~/.claude`` — the harness's directory for the user, not for one project."""
    return os.path.join(os.path.expanduser("~"), HARNESS_STATE_DIRECTORY_NAME)


def user_application_directory_path() -> str:
    """``~/.claude/manual-context-persistence`` — one fixed home for our files.

    The hook scripts are deployed here rather than referenced where this
    repository happens to sit, so a project's settings file points at a path that
    does not move when the repository does.
    """
    return os.path.join(user_harness_directory_path(), APPLICATION_STATE_DIRECTORY_NAME)


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

    def exists(self) -> bool:
        """True when a file is present, whether or not its content is usable.

        Distinct from ``holds_content``: startup has to tell "no file here yet,
        set it up" apart from "a file is here and I could not read it", and
        silently overwriting the second would discard someone's settings.
        """
        return os.path.exists(self._file_path)

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
    def harness_directory_path(self) -> str:
        """``<project>/.claude`` — the harness's directory, which we do not own."""
        return os.path.join(self._project_directory, HARNESS_STATE_DIRECTORY_NAME)

    @property
    def application_directory_path(self) -> str:
        """``<project>/.claude/manual-context-persistence`` — everything of ours."""
        return os.path.join(
            self.harness_directory_path, APPLICATION_STATE_DIRECTORY_NAME
        )

    def harness_json_document(self, document_file_name: str) -> JsonDocumentFile:
        """A document directly in ``.claude``, such as ``settings.local.json``."""
        return JsonDocumentFile(
            os.path.join(self.harness_directory_path, document_file_name)
        )

    def application_json_document(self, document_file_name: str) -> JsonDocumentFile:
        return JsonDocumentFile(
            os.path.join(self.application_directory_path, document_file_name)
        )

    def application_subdirectory_path(self, subdirectory_name: str) -> str:
        """Return a path inside our directory without creating anything."""
        return os.path.join(self.application_directory_path, subdirectory_name)

    def create_application_directory(self) -> str:
        """Create our directory if it is not already there."""
        os.makedirs(self.application_directory_path, exist_ok=True)
        return self.application_directory_path
