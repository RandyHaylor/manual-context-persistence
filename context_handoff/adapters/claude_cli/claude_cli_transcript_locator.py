"""Locate Claude CLI session transcripts and read facts recorded inside them.

Claude CLI stores each session as a .jsonl under
``<projects root>/<encoded working directory>/<session id>.jsonl`` where the
encoding replaces every non-alphanumeric character with a hyphen. The projects
root is a parameter rather than a constant so tests can point at a temporary
directory instead of the developer's real session history.

The CLI keys a project directory to the path it was launched from, not to
whatever subdirectory a caller happens to run in, so directory resolution walks
up to the filesystem root and considers every ancestor's transcripts.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Optional

DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY = os.path.expanduser("~/.claude/projects")

TRANSCRIPT_RECORD_TYPE_AGENT_NAME = "agent-name"


def encode_working_directory_for_transcript_directory_name(working_directory: str) -> str:
    return "".join(
        character if character.isalnum() else "-" for character in working_directory
    )


def build_transcript_directory_path(
    working_directory: str,
    claude_projects_root_directory: str = DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
) -> str:
    return os.path.join(
        claude_projects_root_directory,
        encode_working_directory_for_transcript_directory_name(working_directory),
    )


def build_transcript_file_path(
    session_identifier: str,
    working_directory: str,
    claude_projects_root_directory: str = DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
) -> str:
    return os.path.join(
        build_transcript_directory_path(working_directory, claude_projects_root_directory),
        f"{session_identifier}.jsonl",
    )


def find_active_session_identifier_for_working_directory(
    working_directory: str,
    claude_projects_root_directory: str = DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
) -> str:
    """Return the identifier of the most recently written session for a directory.

    The session currently being written to has the newest modification time,
    which is the only signal available without asking the CLI itself.

    Raises ``LookupError`` when neither the directory nor any ancestor has a
    transcript.
    """
    candidate_transcript_paths: list[str] = []
    already_visited_directories: set[str] = set()
    current_directory = os.path.abspath(working_directory)

    while current_directory and current_directory not in already_visited_directories:
        already_visited_directories.add(current_directory)
        candidate_transcript_paths.extend(
            glob.glob(
                os.path.join(
                    build_transcript_directory_path(
                        current_directory, claude_projects_root_directory
                    ),
                    "*.jsonl",
                )
            )
        )
        parent_directory = os.path.dirname(current_directory)
        if parent_directory == current_directory:
            break
        current_directory = parent_directory

    if not candidate_transcript_paths:
        raise LookupError(
            f"no session transcript found for {working_directory!r} or any ancestor "
            f"under {claude_projects_root_directory!r}"
        )

    newest_transcript_path = max(candidate_transcript_paths, key=os.path.getmtime)
    return os.path.splitext(os.path.basename(newest_transcript_path))[0]


def read_session_display_name_from_transcript(
    session_identifier: str,
    working_directory: str,
    claude_projects_root_directory: str = DEFAULT_CLAUDE_PROJECTS_ROOT_DIRECTORY,
) -> Optional[str]:
    """Return the session's human-facing name, or None when it has never been set.

    The name is recorded as repeated ``{"type": "agent-name", "agentName": ...}``
    records; the last one in the file is authoritative. Unparsable lines are
    skipped because a transcript may be read while the CLI is mid-write.
    """
    transcript_path = build_transcript_file_path(
        session_identifier, working_directory, claude_projects_root_directory
    )
    if not os.path.exists(transcript_path):
        return None

    most_recent_display_name: Optional[str] = None
    with open(transcript_path, "r", encoding="utf-8") as transcript_file:
        for line in transcript_file:
            if TRANSCRIPT_RECORD_TYPE_AGENT_NAME not in line:
                continue
            try:
                parsed_record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed_record, dict):
                continue
            if parsed_record.get("type") != TRANSCRIPT_RECORD_TYPE_AGENT_NAME:
                continue
            recorded_name = parsed_record.get("agentName")
            if isinstance(recorded_name, str) and recorded_name:
                most_recent_display_name = recorded_name
    return most_recent_display_name
