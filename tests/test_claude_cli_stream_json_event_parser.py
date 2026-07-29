"""Tests for the pure parser over the harness's NDJSON event stream.

Written before the parser exists. The parser is deliberately pure — an iterable
of lines in, a result dataclass out — so every stream shape the adapter must
survive can be exercised with no subprocess.
"""
from __future__ import annotations

import json

from context_handoff.adapters.claude_cli.claude_cli_stream_json_event_parser import (
    StreamJsonParseResult,
    parse_stream_json_event_lines,
)


def build_assistant_text_event_line(text: str) -> str:
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def build_result_event_line(result_text: str, is_error: bool = False) -> str:
    return json.dumps({"type": "result", "result": result_text, "is_error": is_error})


def test_empty_stream_yields_no_final_text() -> None:
    parse_result = parse_stream_json_event_lines([])
    assert isinstance(parse_result, StreamJsonParseResult)
    assert parse_result.final_result_text is None
    assert parse_result.accumulated_assistant_text == ""
    assert parse_result.is_error is False


def test_result_event_supplies_the_final_text() -> None:
    parse_result = parse_stream_json_event_lines(
        [build_assistant_text_event_line("ack"), build_result_event_line("ack")]
    )
    assert parse_result.final_result_text == "ack"


def test_assistant_text_chunks_accumulate_in_order() -> None:
    parse_result = parse_stream_json_event_lines(
        [
            build_assistant_text_event_line("first "),
            build_assistant_text_event_line("second"),
        ]
    )
    assert parse_result.accumulated_assistant_text == "first second"


def test_result_without_result_field_falls_back_to_accumulated_text() -> None:
    parse_result = parse_stream_json_event_lines(
        [
            build_assistant_text_event_line("accumulated only"),
            json.dumps({"type": "result", "is_error": False}),
        ]
    )
    assert parse_result.final_result_text == "accumulated only"


def test_blank_and_unparsable_lines_are_ignored() -> None:
    parse_result = parse_stream_json_event_lines(
        ["", "   ", "not json at all", build_result_event_line("survived")]
    )
    assert parse_result.final_result_text == "survived"


def test_error_result_is_reported_not_raised() -> None:
    parse_result = parse_stream_json_event_lines(
        [build_result_event_line("something failed", is_error=True)]
    )
    assert parse_result.is_error is True
    assert parse_result.final_result_text == "something failed"


def test_lines_after_the_result_event_are_ignored() -> None:
    parse_result = parse_stream_json_event_lines(
        [
            build_result_event_line("final"),
            build_assistant_text_event_line("late chatter"),
        ]
    )
    assert parse_result.final_result_text == "final"
    assert "late chatter" not in parse_result.accumulated_assistant_text


def test_every_line_is_offered_to_the_observer_for_logging() -> None:
    observed_events: list[tuple[str, str]] = []
    parse_result = parse_stream_json_event_lines(
        ["", build_result_event_line("done")],
        observe_stream_event=lambda kind, body: observed_events.append((kind, body)),
    )
    assert parse_result.final_result_text == "done"
    observed_kinds = [kind for kind, _ in observed_events]
    assert "STREAM_LINE" in observed_kinds
    assert "FINAL_RESULT" in observed_kinds


def test_non_text_content_blocks_do_not_break_accumulation() -> None:
    tool_use_event_line = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read"}]},
        }
    )
    parse_result = parse_stream_json_event_lines(
        [tool_use_event_line, build_assistant_text_event_line("text survives")]
    )
    assert parse_result.accumulated_assistant_text == "text survives"
