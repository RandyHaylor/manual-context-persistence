"""Tests for reading agent output back out of a Claude CLI transcript.

The record shapes used here were taken from a real transcript, not invented:
assistant text arrives as content blocks of type "text", a real user prompt has
a plain string as its message content, tool results are user records whose
content is a list, and subagent activity is flagged with isSidechain.
"""
from __future__ import annotations

import json

from context_handoff.adapters.claude_cli.claude_cli_transcript_reader import (
    read_agent_output_since_last_user_prompt,
    read_last_assistant_text_message,
)


def write_transcript(tmp_path, records: list[dict]) -> str:
    transcript_path = str(tmp_path / "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        for record in records:
            transcript_file.write(json.dumps(record) + "\n")
    return transcript_path


def assistant_text_record(text: str, is_sidechain: bool = False) -> dict:
    return {
        "type": "assistant",
        "isSidechain": is_sidechain,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def assistant_tool_use_record(tool_name: str) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": tool_name}],
        },
    }


def assistant_thinking_record(thinking_text: str) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": thinking_text}],
        },
    }


def user_prompt_record(prompt_text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": prompt_text},
    }


def user_tool_result_record(result_text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": result_text}],
        },
    }


def test_an_empty_transcript_has_no_last_assistant_message(tmp_path) -> None:
    assert read_last_assistant_text_message(write_transcript(tmp_path, [])) is None


def test_a_missing_transcript_has_no_last_assistant_message(tmp_path) -> None:
    assert read_last_assistant_text_message(str(tmp_path / "absent.jsonl")) is None


def test_the_last_assistant_text_message_is_returned(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            assistant_text_record("earlier reply"),
            user_prompt_record("next question"),
            assistant_text_record("latest reply"),
        ],
    )
    assert read_last_assistant_text_message(transcript_path) == "latest reply"


def test_text_blocks_within_one_message_are_joined(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "first part "},
                        {"type": "text", "text": "second part"},
                    ],
                },
            }
        ],
    )
    assert read_last_assistant_text_message(transcript_path) == "first part second part"


def test_tool_use_and_thinking_records_are_not_mistaken_for_a_reply(tmp_path) -> None:
    """The Stop hook needs the text the agent showed the user, nothing else."""
    transcript_path = write_transcript(
        tmp_path,
        [
            assistant_text_record("the real reply"),
            assistant_thinking_record("private reasoning"),
            assistant_tool_use_record("Bash"),
        ],
    )
    assert read_last_assistant_text_message(transcript_path) == "the real reply"


def test_subagent_replies_are_ignored(tmp_path) -> None:
    """A sidechain is a subagent's conversation, not this session's."""
    transcript_path = write_transcript(
        tmp_path,
        [
            assistant_text_record("main session reply"),
            assistant_text_record("subagent reply", is_sidechain=True),
        ],
    )
    assert read_last_assistant_text_message(transcript_path) == "main session reply"


def test_unparsable_lines_are_skipped(tmp_path) -> None:
    transcript_path = str(tmp_path / "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        transcript_file.write('{"type":"assistant", TRUNCATED\n')
        transcript_file.write(json.dumps(assistant_text_record("survived")) + "\n")
    assert read_last_assistant_text_message(transcript_path) == "survived"


def test_agent_output_since_the_last_user_prompt_excludes_earlier_turns(
    tmp_path,
) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            assistant_text_record("OLD TURN OUTPUT"),
            user_prompt_record("the question that started this turn"),
            assistant_text_record("CURRENT TURN OUTPUT"),
        ],
    )
    recent_output = read_agent_output_since_last_user_prompt(transcript_path, 2000)
    assert "CURRENT TURN OUTPUT" in recent_output
    assert "OLD TURN OUTPUT" not in recent_output


def test_agent_output_includes_tool_results_from_this_turn(tmp_path) -> None:
    """A short reply like "yes" only makes sense beside what the agent just did."""
    transcript_path = write_transcript(
        tmp_path,
        [
            user_prompt_record("run the tests"),
            assistant_tool_use_record("Bash"),
            user_tool_result_record("158 passed"),
            assistant_text_record("All tests pass."),
        ],
    )
    recent_output = read_agent_output_since_last_user_prompt(transcript_path, 2000)
    assert "158 passed" in recent_output
    assert "All tests pass." in recent_output


def test_agent_output_is_capped_and_keeps_the_most_recent_text(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            user_prompt_record("go"),
            assistant_text_record("a" * 5000),
            assistant_text_record("THE FINAL QUESTION"),
        ],
    )
    recent_output = read_agent_output_since_last_user_prompt(
        transcript_path, maximum_characters=2000
    )
    assert len(recent_output) <= 2000
    assert recent_output.rstrip().endswith("THE FINAL QUESTION")


def test_a_turn_with_no_prior_user_prompt_returns_everything_available(
    tmp_path,
) -> None:
    transcript_path = write_transcript(
        tmp_path, [assistant_text_record("output with no preceding prompt")]
    )
    assert "output with no preceding prompt" in read_agent_output_since_last_user_prompt(
        transcript_path, 2000
    )


def test_a_missing_transcript_yields_empty_recent_output(tmp_path) -> None:
    assert read_agent_output_since_last_user_prompt(str(tmp_path / "absent.jsonl"), 2000) == ""
