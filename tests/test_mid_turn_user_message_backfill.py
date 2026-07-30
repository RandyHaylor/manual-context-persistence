"""Tests for recovering user messages sent while the agent was working.

A message typed mid-turn does not fire the prompt-submit hook, so it is never
logged by the normal path. It does land in the transcript as a queued_command
attachment. The next normal submission does fire the hook, and that is when
these messages are recovered.

The attachment shape here was verified against a real transcript:
type "attachment", attachment.type "queued_command", commandMode "prompt",
origin.kind "human", text in attachment.prompt.

Scoping is gap-anchored — only the span between the previous genuine prompt and
this one — so a forked transcript's inherited history is never rescanned and
nothing is logged twice.
"""
from __future__ import annotations

import json

from context_handoff.adapters.claude_cli.claude_cli_transcript_reader import (
    find_user_messages_sent_while_agent_was_working,
)


def write_transcript(tmp_path, records: list[dict]) -> str:
    transcript_path = str(tmp_path / "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as transcript_file:
        for record in records:
            transcript_file.write(json.dumps(record) + "\n")
    return transcript_path


def genuine_user_prompt_record(prompt_text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": prompt_text},
    }


def tool_result_record(result_text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": result_text}],
        },
    }


def queued_human_message_record(prompt_text: str) -> dict:
    return {
        "type": "attachment",
        "attachment": {
            "type": "queued_command",
            "commandMode": "prompt",
            "origin": {"kind": "human"},
            "prompt": prompt_text,
        },
    }


def queued_non_human_message_record(prompt_text: str) -> dict:
    return {
        "type": "attachment",
        "attachment": {
            "type": "queued_command",
            "commandMode": "prompt",
            "origin": {"kind": "system"},
            "prompt": prompt_text,
        },
    }


def test_a_transcript_with_no_queued_messages_backfills_nothing(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path, [genuine_user_prompt_record("first"), tool_result_record("output")]
    )
    assert (
        find_user_messages_sent_while_agent_was_working(transcript_path, "second") == []
    )


def test_a_missing_transcript_backfills_nothing(tmp_path) -> None:
    assert (
        find_user_messages_sent_while_agent_was_working(
            str(tmp_path / "absent.jsonl"), "anything"
        )
        == []
    )


def test_a_mid_turn_message_after_the_last_prompt_is_recovered(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("do the work"),
            queued_human_message_record("actually also do this"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "the next prompt"
    ) == ["actually also do this"]


def test_several_mid_turn_messages_are_recovered_in_order(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("do the work"),
            queued_human_message_record("first aside"),
            tool_result_record("some output"),
            queued_human_message_record("second aside"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "the next prompt"
    ) == ["first aside", "second aside"]


def test_messages_before_the_previous_prompt_are_not_rescanned(tmp_path) -> None:
    """Rescanning old history would relog it on every single submission."""
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("turn one"),
            queued_human_message_record("OLD ASIDE ALREADY HANDLED"),
            genuine_user_prompt_record("turn two"),
            queued_human_message_record("new aside"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "turn three"
    ) == ["new aside"]


def test_the_incoming_prompt_is_not_backfilled_as_well(tmp_path) -> None:
    """A queued message may be consumed AS this submission; logging it twice is wrong."""
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("turn one"),
            queued_human_message_record("this becomes the incoming prompt"),
        ],
    )
    assert (
        find_user_messages_sent_while_agent_was_working(
            transcript_path, "this becomes the incoming prompt"
        )
        == []
    )


def test_the_gap_is_measured_before_the_incoming_prompt_when_already_recorded(
    tmp_path,
) -> None:
    """The hook may run after the incoming prompt is already in the transcript."""
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("turn one"),
            queued_human_message_record("mid-turn aside"),
            genuine_user_prompt_record("turn two"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "turn two"
    ) == ["mid-turn aside"]


def test_non_human_queued_commands_are_ignored(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("turn one"),
            queued_non_human_message_record("injected by tooling"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(transcript_path, "next") == []


def test_blank_queued_messages_are_ignored(tmp_path) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [genuine_user_prompt_record("turn one"), queued_human_message_record("   ")],
    )
    assert find_user_messages_sent_while_agent_was_working(transcript_path, "next") == []


def interrupt_marker_record() -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": "[Request interrupted by user for tool use]",
        },
    }


def attachment_style_user_prompt_record(prompt_text: str) -> dict:
    """A typed prompt carrying an attachment: list content, no tool_result."""
    return {
        "type": "user",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": prompt_text}],
        },
    }


def test_an_interrupt_marker_does_not_move_the_anchor(tmp_path) -> None:
    """This loop sends ctrl+c every rotation, so interrupts are the normal path.

    If a cancel marker counted as a genuine prompt it would drag the anchor
    past the user's aside, and that aside would never be logged at all.
    """
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("do the work"),
            queued_human_message_record("aside typed before the interrupt"),
            interrupt_marker_record(),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "the next prompt"
    ) == ["aside typed before the interrupt"]


def test_an_attachment_style_prompt_does_move_the_anchor(tmp_path) -> None:
    """It is a real typed prompt, so anything before it was already logged."""
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("turn one"),
            queued_human_message_record("OLD ASIDE ALREADY HANDLED"),
            attachment_style_user_prompt_record("turn two with a pasted file"),
            queued_human_message_record("new aside"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "turn three"
    ) == ["new aside"]


def test_an_attachment_style_incoming_prompt_is_recognised_as_already_recorded(
    tmp_path,
) -> None:
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("turn one"),
            queued_human_message_record("mid-turn aside"),
            attachment_style_user_prompt_record("turn two"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "turn two"
    ) == ["mid-turn aside"]


def test_injected_meta_records_do_not_move_the_anchor(tmp_path) -> None:
    """A system reminder between prompt and aside must not hide the aside."""
    transcript_path = write_transcript(
        tmp_path,
        [
            genuine_user_prompt_record("do the work"),
            {
                "type": "user",
                "isSidechain": False,
                "isMeta": True,
                "message": {"role": "user", "content": "<system-reminder>x</system-reminder>"},
            },
            queued_human_message_record("aside after an injected record"),
        ],
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "the next prompt"
    ) == ["aside after an injected record"]


def test_a_transcript_with_no_prior_prompt_still_recovers_queued_messages(
    tmp_path,
) -> None:
    transcript_path = write_transcript(
        tmp_path, [queued_human_message_record("aside with no prior prompt")]
    )
    assert find_user_messages_sent_while_agent_was_working(
        transcript_path, "next"
    ) == ["aside with no prior prompt"]
