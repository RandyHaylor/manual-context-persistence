#!/usr/bin/env python3
"""PostToolUse hook entry point: read the payload from stdin, print the response.

Register in a project's .claude/settings.local.json under hooks.PostToolUse. All
logic lives in the handler; this file only moves JSON in and out so the behaviour
can be tested without spawning a process.
"""
import json
import os
import sys

REPOSITORY_ROOT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY_ROOT_DIRECTORY not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT_DIRECTORY)

from context_handoff.hooks.post_tool_use_handoff_reminder_hook_handler import (  # noqa: E402
    handle_post_tool_use_payload,
)


def main() -> int:
    try:
        hook_payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        # Unreadable stdin is still not a reason to disturb the session.
        print("{}")
        return 0
    if not isinstance(hook_payload, dict):
        print("{}")
        return 0
    print(json.dumps(handle_post_tool_use_payload(hook_payload)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
