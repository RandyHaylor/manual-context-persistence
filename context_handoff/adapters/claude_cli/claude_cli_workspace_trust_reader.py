"""Has this project directory been trusted in the Claude CLI yet?

Worth knowing at startup because trust gates more than a dialog: the
documentation states that project settings are honoured "only after you accept
the workspace trust dialog", and this system's capture hooks live in project
settings. An untrusted directory therefore produces a branch that launches,
waits on a prompt, and records nothing.

Two deliberate limits. This only reads — whether to trust a directory is a
safety decision belonging to the person running it, and no supported way to
pre-trust one is documented. And anything it cannot determine is reported as
unknown rather than untrusted, because the state it reads is undocumented and a
confident wrong answer would be worse than no answer.
"""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_CLAUDE_STATE_FILE_PATH = os.path.expanduser("~/.claude.json")

# Confirmed by inspecting a real state file rather than assumed. Undocumented,
# which is why every failure to read it means "unknown".
TRUST_DIALOG_ACCEPTED_FIELD_NAME = "hasTrustDialogAccepted"


def read_whether_project_directory_is_trusted(
    project_directory: str,
    claude_state_file_path: str = DEFAULT_CLAUDE_STATE_FILE_PATH,
) -> Optional[bool]:
    """Return True, False, or None when it cannot be determined."""
    if not os.path.exists(claude_state_file_path):
        return None
    try:
        with open(claude_state_file_path, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(state, dict):
        return None

    project_entries = state.get("projects")
    if not isinstance(project_entries, dict):
        return None

    entry = project_entries.get(os.path.abspath(project_directory))
    if not isinstance(entry, dict):
        return None

    trust_value = entry.get(TRUST_DIALOG_ACCEPTED_FIELD_NAME)
    return trust_value if isinstance(trust_value, bool) else None
