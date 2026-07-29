"""Read agent output back out of a Claude CLI session transcript.

Two questions are answered here, both needed by hooks:

  * what the agent last said to the user — the Stop hook searches it for the
    handoff package;
  * what the agent produced during the current turn — the prompt-capture hook
    stores it beside the user's words, so a reply of "yes" is still a complete
    requirement later.

The record shapes were taken from a real transcript. Assistant text arrives as
content blocks of type "text"; thinking and tool_use blocks are not text the
user saw. A real user prompt has a plain string as its message content, while a
tool result is a user record whose content is a list. Subagent activity is
flagged with isSidechain and belongs to another conversation.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

TRANSCRIPT_RECORD_TYPE_ASSISTANT = "assistant"
TRANSCRIPT_RECORD_TYPE_USER = "user"


def _iterate_transcript_records(transcript_path: str):
    """Yield decoded records, skipping anything unreadable.

    A transcript may be read while the CLI is mid-write, so a truncated final
    line is normal rather than exceptional.
    """
    if not os.path.exists(transcript_path):
        return
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as transcript_file:
        for line in transcript_file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def _is_main_session_record(record: dict[str, Any]) -> bool:
    return not record.get("isSidechain", False)


def _extract_assistant_text(record: dict[str, Any]) -> Optional[str]:
    if record.get("type") != TRANSCRIPT_RECORD_TYPE_ASSISTANT:
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content_blocks = message.get("content")
    if not isinstance(content_blocks, list):
        return None
    text_chunks = [
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    joined_text = "".join(text_chunks)
    return joined_text or None


def _is_user_prompt_record(record: dict[str, Any]) -> bool:
    """True for a message the user typed, false for a tool result.

    The distinguishing feature is the content type: a typed prompt is a plain
    string, a tool result is a list of blocks.
    """
    if record.get("type") != TRANSCRIPT_RECORD_TYPE_USER:
        return False
    message = record.get("message")
    if not isinstance(message, dict):
        return False
    return isinstance(message.get("content"), str)


def _extract_tool_result_text(record: dict[str, Any]) -> Optional[str]:
    if record.get("type") != TRANSCRIPT_RECORD_TYPE_USER:
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content_blocks = message.get("content")
    if not isinstance(content_blocks, list):
        return None
    result_chunks: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        block_content = block.get("content")
        if isinstance(block_content, str):
            result_chunks.append(block_content)
        elif isinstance(block_content, list):
            result_chunks.extend(
                inner_block.get("text", "")
                for inner_block in block_content
                if isinstance(inner_block, dict) and inner_block.get("type") == "text"
            )
    joined_text = "\n".join(chunk for chunk in result_chunks if chunk)
    return joined_text or None


def read_last_assistant_text_message(transcript_path: str) -> Optional[str]:
    """Return the last thing the agent said to the user, or None."""
    most_recent_assistant_text: Optional[str] = None
    for record in _iterate_transcript_records(transcript_path):
        if not _is_main_session_record(record):
            continue
        assistant_text = _extract_assistant_text(record)
        if assistant_text is not None:
            most_recent_assistant_text = assistant_text
    return most_recent_assistant_text


def read_agent_output_since_last_user_prompt(
    transcript_path: str, maximum_characters: int
) -> str:
    """Return this turn's agent output, capped to the most recent characters.

    Capped from the front: the text nearest the user's next prompt is the part
    that gives that prompt its meaning.
    """
    records_in_current_turn: list[dict[str, Any]] = []
    for record in _iterate_transcript_records(transcript_path):
        if not _is_main_session_record(record):
            continue
        if _is_user_prompt_record(record):
            records_in_current_turn = []
            continue
        records_in_current_turn.append(record)

    rendered_sections: list[str] = []
    for record in records_in_current_turn:
        assistant_text = _extract_assistant_text(record)
        if assistant_text:
            rendered_sections.append(assistant_text)
            continue
        tool_result_text = _extract_tool_result_text(record)
        if tool_result_text:
            rendered_sections.append(tool_result_text)

    rendered_output = "\n\n".join(rendered_sections)
    if len(rendered_output) <= maximum_characters:
        return rendered_output
    return rendered_output[-maximum_characters:]
