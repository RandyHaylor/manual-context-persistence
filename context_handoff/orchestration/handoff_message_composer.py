"""Compose the one message the base session receives per turn.

Everything the base session will ever know about a turn is in this message, and
everything it does NOT contain is deliberate. The branch transcript is not
carried: keeping the base compact across many turns is the reason the design
exists at all.

The acknowledge-only instruction goes last, where an instruction is least
likely to be overtaken by the material above it.
"""
from __future__ import annotations

from typing import Sequence

from context_handoff.context_to_keep.context_to_keep_package import ContextToKeepPackage
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogEntry

ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT = (
    "Acknowledge receipt of this handoff in one short sentence. Do not act on it, "
    "do not use tools, and do not answer the user prompts above — they have "
    "already been handled in a branch session. This message exists only so this "
    "session accumulates the project's context."
)


def compose_handoff_message_for_base_session(
    user_prompt_entries: Sequence[UserPromptLogEntry],
    context_to_keep_package: ContextToKeepPackage,
) -> str:
    message_sections: list[str] = ["## Handoff from the last branch turn"]

    if user_prompt_entries:
        message_sections.append("### What the user said, verbatim")
        for entry_position, entry in enumerate(user_prompt_entries, start=1):
            if entry.pre_submission_content:
                message_sections.append(
                    f"Context immediately before user message {entry_position}:\n"
                    f"{entry.pre_submission_content}"
                )
            # Fenced so the base session reads the text as quoted material
            # rather than as an instruction addressed to it.
            message_sections.append(
                f"User message {entry_position}:\n```text\n{entry.user_prompt_text}\n```"
            )
    else:
        message_sections.append(
            "### What the user said, verbatim\n(no user message in this turn)"
        )

    message_sections.append(
        "### What the last turn accomplished\n"
        + context_to_keep_package.summary_of_work_completed_this_turn
    )

    if context_to_keep_package.context_to_carry_forward:
        carried_context_lines = "\n".join(
            f"- {carried_context_entry}"
            for carried_context_entry in context_to_keep_package.context_to_carry_forward
        )
        message_sections.append(
            "### Context to carry forward\n" + carried_context_lines
        )

    message_sections.append(ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT)
    return "\n\n".join(message_sections)
