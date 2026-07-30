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
TRANSCRIPT_RECORD_TYPE_ATTACHMENT = "attachment"
ATTACHMENT_TYPE_QUEUED_COMMAND = "queued_command"

# The CLI records a cancelled turn as a user record with this text. It is not
# something the user typed, so it must never be treated as a prompt.
INTERRUPT_MARKER_TEXT_PREFIX = "[Request interrupted by user"


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


def extract_user_prompt_text(record: dict[str, Any]) -> str:
    """Return the plain text of a user-prompt record, or "" if it has none.

    Content is either a plain string or a list of text blocks; the list form is
    how a prompt carrying an attachment is recorded. Mirrors the reference
    implementation named in the spec, including its "\\n" join and its
    tolerance of bare string blocks.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(part for part in text_parts if part)
    return ""


def _is_user_prompt_record(record: dict[str, Any]) -> bool:
    """True for a genuine user prompt: not a tool result, not a cancel marker.

    This mirrors the reference implementation the spec points to, deliberately
    and exactly. It judges a record by its SHAPE — string content, or list
    content without tool_result blocks — and by whether its text is an
    interrupt marker. It does not attempt to distinguish typed text from
    harness-injected text by any other signal.

    That restraint is the point. This predicate only decides where a turn
    BEGINS, which bounds how much preceding agent output is captured and how
    far back the mid-turn scan reaches. It never decides what gets logged as a
    user message: prompt text comes from the hook payload, and mid-turn
    messages come from human queued_command attachments. Widening this
    predicate on a guess moves turn boundaries without making the log more
    faithful.
    """
    if record.get("type") != TRANSCRIPT_RECORD_TYPE_USER:
        return False
    message = record.get("message")
    if not isinstance(message, dict):
        return False

    content = message.get("content")
    if isinstance(content, str):
        return not _is_interrupt_marker_text(content)
    if isinstance(content, list):
        if any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            return False
        # An attachment-style prompt whose text is only a marker is still a
        # marker.
        return not _is_interrupt_marker_text(extract_user_prompt_text(record))
    return False


def _is_interrupt_marker_text(text: str) -> bool:
    return text.strip().startswith(INTERRUPT_MARKER_TEXT_PREFIX)


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


def _is_human_queued_command_record(record: dict[str, Any]) -> bool:
    """True for a message the user typed while the agent was still working.

    Shape verified against a real transcript: an attachment record whose
    attachment is a queued_command in prompt mode originating from a human.
    """
    if record.get("type") != TRANSCRIPT_RECORD_TYPE_ATTACHMENT:
        return False
    attachment = record.get("attachment") or {}
    if not isinstance(attachment, dict):
        return False
    if attachment.get("type") != ATTACHMENT_TYPE_QUEUED_COMMAND:
        return False
    if attachment.get("commandMode") != "prompt":
        return False
    origin = attachment.get("origin") or {}
    return isinstance(origin, dict) and origin.get("kind") == "human"


def _extract_queued_command_text(record: dict[str, Any]) -> str:
    """Return the queued message's text, whatever shape the field takes.

    ``attachment.prompt`` is a plain string on some CLI versions and a list of
    text blocks on others — including the current one, where the list form is
    the common shape. Verified across 473 real transcripts: 277 string, 57
    list.

    This is the one place this module intentionally differs from the reference
    implementation, which indexes the field as a string and raises on the list
    form. Raising here is not a survivable outcome: the hook catches broadly,
    so the whole submission is dropped and the user's current prompt goes
    unlogged. The set of records treated as queued human messages is
    unchanged.
    """
    attachment = record.get("attachment") or {}
    if not isinstance(attachment, dict):
        return ""
    prompt_value = attachment.get("prompt")
    if isinstance(prompt_value, str):
        return prompt_value
    if isinstance(prompt_value, list):
        text_parts: list[str] = []
        for block in prompt_value:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(part for part in text_parts if part)
    return ""


def find_user_messages_sent_while_agent_was_working(
    transcript_path: str, incoming_prompt_text: str
) -> list[str]:
    """Return mid-turn user messages that no prompt-submit hook ever saw.

    A message typed while the agent is working does not fire the hook, so it is
    never logged — but it does land in the transcript, and the NEXT normal
    submission does fire the hook. This runs then, and recovers the gap.

    The scan is anchored to the span between the previous genuine prompt and
    this one. Scanning wider would relog old messages on every submission, and
    would rescan a forked transcript's inherited history as if it were new.

    The incoming prompt is excluded: a queued message may be the very thing
    being consumed as this submission, and the normal path already logs it.
    """
    all_records = list(_iterate_transcript_records(transcript_path))
    incoming_prompt_text_stripped = (incoming_prompt_text or "").strip()

    genuine_prompt_indices = [
        index
        for index, record in enumerate(all_records)
        if _is_main_session_record(record) and _is_user_prompt_record(record)
    ]

    # Extracted rather than indexed: a prompt's content may be a list of text
    # blocks, and str() of that list would never match the incoming text.
    incoming_prompt_is_already_recorded = bool(genuine_prompt_indices) and (
        extract_user_prompt_text(all_records[genuine_prompt_indices[-1]]).strip()
        == incoming_prompt_text_stripped
    )
    if incoming_prompt_is_already_recorded:
        anchor_index = (
            genuine_prompt_indices[-2] if len(genuine_prompt_indices) >= 2 else -1
        )
        window_end_index = genuine_prompt_indices[-1]
    else:
        anchor_index = genuine_prompt_indices[-1] if genuine_prompt_indices else -1
        window_end_index = len(all_records)

    recovered_message_texts: list[str] = []
    for record in all_records[anchor_index + 1 : window_end_index]:
        if not _is_human_queued_command_record(record):
            continue
        queued_message_text = _extract_queued_command_text(record)
        if not queued_message_text.strip():
            continue
        if queued_message_text.strip() == incoming_prompt_text_stripped:
            continue
        recovered_message_texts.append(queued_message_text)
    return recovered_message_texts


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
