"""Compose the one message the base session receives per turn.

Spec 2 line 15 names what it carries: the user prompts from the log, the
context-to-keep, and an instruction to only acknowledge. Nothing else goes in.

Everything here is repeated on every rotation for the life of a project, so
overhead compounds. An earlier version added markdown section headers, an
explanatory paragraph, and the agent output preceding each prompt; measured
across a twenty-turn run, the user's own words came to 4% of what reached the
base. The agent output in particular is branch transcript, which spec 1 line 29
keeps out of the base — the prompt log is where it belongs.
"""
from __future__ import annotations

from typing import Sequence

from context_handoff.context_to_keep.context_to_keep_package import ContextToKeepPackage
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogEntry

ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT = "Acknowledge receipt only."


def compose_handoff_message_for_base_session(
    user_prompt_entries: Sequence[UserPromptLogEntry],
    context_to_keep_package: ContextToKeepPackage,
) -> str:
    message_parts: list[str] = []

    for entry in user_prompt_entries:
        message_parts.append("User: " + entry.user_prompt_text)

    message_parts.append(
        "Done: " + context_to_keep_package.summary_of_work_completed_this_turn
    )
    for carried_context in context_to_keep_package.context_to_carry_forward:
        message_parts.append("Keep: " + carried_context)

    message_parts.append(ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT)
    return "\n\n".join(message_parts)
