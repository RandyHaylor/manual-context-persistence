"""Pure parser over the Claude CLI `--output-format stream-json` NDJSON stream.

Separated from process management so every stream shape — truncated output,
unparsable lines, a result event with no result field — is testable without
spawning anything. The parser never raises on malformed input: an unusable line
is skipped, and an error result is reported through the return value.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

STREAM_EVENT_KIND_LINE = "STREAM_LINE"
STREAM_EVENT_KIND_FINAL_RESULT = "FINAL_RESULT"


@dataclass(frozen=True)
class StreamJsonParseResult:
    """Outcome of reading a stream to its result event or to exhaustion.

    ``final_result_text`` is None only when no result event ever arrived, which
    is how a caller distinguishes a truncated stream from an empty answer.
    """

    final_result_text: Optional[str]
    accumulated_assistant_text: str
    is_error: bool


def parse_stream_json_event_lines(
    stream_json_lines: Iterable[str],
    observe_stream_event: Optional[Callable[[str, str], None]] = None,
) -> StreamJsonParseResult:
    """Consume NDJSON lines up to and including the first result event.

    ``observe_stream_event(kind, body)`` receives every raw line before it is
    interpreted, so a caller can persist a complete record even when the stream
    is later abandoned. An exception from the observer is never allowed to
    break parsing.
    """

    def emit_observed_event(event_kind: str, event_body_text: str) -> None:
        if observe_stream_event is None:
            return
        try:
            observe_stream_event(event_kind, event_body_text)
        except Exception:
            pass

    accumulated_assistant_text_chunks: list[str] = []
    final_result_text: Optional[str] = None
    is_error = False

    for raw_line in stream_json_lines:
        stripped_line = raw_line.strip()
        emit_observed_event(STREAM_EVENT_KIND_LINE, stripped_line)
        if not stripped_line:
            continue
        try:
            parsed_event = json.loads(stripped_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed_event, dict):
            continue

        event_type = parsed_event.get("type")
        if event_type == "assistant":
            message_content_blocks = parsed_event.get("message", {}).get("content") or []
            for content_block in message_content_blocks:
                if not isinstance(content_block, dict):
                    continue
                if content_block.get("type") != "text":
                    continue
                text_chunk = content_block.get("text") or ""
                if text_chunk:
                    accumulated_assistant_text_chunks.append(text_chunk)
        elif event_type == "result":
            is_error = bool(parsed_event.get("is_error"))
            emit_observed_event(
                STREAM_EVENT_KIND_FINAL_RESULT,
                f"is_error={is_error} cost_usd={parsed_event.get('total_cost_usd')}",
            )
            result_field = parsed_event.get("result")
            final_result_text = (
                result_field
                if isinstance(result_field, str)
                else "".join(accumulated_assistant_text_chunks)
            )
            break

    return StreamJsonParseResult(
        final_result_text=final_result_text,
        accumulated_assistant_text="".join(accumulated_assistant_text_chunks),
        is_error=is_error,
    )
