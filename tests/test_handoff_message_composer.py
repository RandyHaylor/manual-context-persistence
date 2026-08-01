"""Tests for the message sent to the base session at each rotation.

Spec 2 line 15 names exactly three things it carries: the user prompts from the
log, the context-to-keep, and an instruction to only acknowledge. These tests
hold it to that and no more.

An earlier version wrapped all of it in markdown section headers and a long
explanatory paragraph, and also carried the agent output that preceded each
prompt. Measured over a twenty-turn run, the user's own words were 4% of what
reached the base. Scaffolding is not free: it is repeated every turn, forever.
"""
from __future__ import annotations

from context_handoff.context_to_keep.context_to_keep_package import ContextToKeepPackage
from context_handoff.orchestration.handoff_message_composer import (
    ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT,
    compose_handoff_message_for_base_session,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogEntry


def build_entry(
    entry_identifier: int, user_prompt_text: str, pre_submission_content: str = ""
) -> UserPromptLogEntry:
    return UserPromptLogEntry(
        entry_identifier=entry_identifier,
        session_identifier="branch-session",
        user_prompt_text=user_prompt_text,
        pre_submission_content=pre_submission_content,
        has_been_consumed=False,
    )


def build_package() -> ContextToKeepPackage:
    return ContextToKeepPackage(
        next_task="Ask the user which pad naming should win.",
        context_to_keep=["The parser is pure.", "Timeouts are reported."],
    )


def test_the_message_carries_the_user_prompt_verbatim() -> None:
    awkward_prompt_text = "  keep   my  spacing\tand “quotes”  "
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, awkward_prompt_text)],
        context_to_keep_package=build_package(),
    )
    assert awkward_prompt_text in message


def test_the_message_carries_every_context_to_keep_entry() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[], context_to_keep_package=build_package()
    )
    assert "The parser is pure." in message
    assert "Timeouts are reported." in message


def test_the_message_ends_with_the_acknowledge_only_instruction() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "do the thing")],
        context_to_keep_package=build_package(),
    )
    assert message.rstrip().endswith(ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT)


def test_the_acknowledge_only_instruction_is_one_short_line() -> None:
    """It is repeated on every rotation for the life of the project."""
    assert len(ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT) < 60
    assert "\n" not in ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT


def test_agent_output_preceding_a_prompt_is_not_sent_to_the_base() -> None:
    """Spec 1 line 29: no full branch transcript.

    The log keeps that context so a short reply stays meaningful when read back.
    The base is not where it belongs.
    """
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[
            build_entry(0, "yes", pre_submission_content="SOME AGENT OUTPUT MARKER")
        ],
        context_to_keep_package=build_package(),
    )
    assert "SOME AGENT OUTPUT MARKER" not in message


def test_the_message_carries_no_markdown_scaffolding() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "do the thing")],
        context_to_keep_package=build_package(),
    )
    assert "##" not in message
    assert "```" not in message


def test_multiple_prompts_appear_in_order() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "FIRST"), build_entry(1, "SECOND")],
        context_to_keep_package=build_package(),
    )
    assert message.index("FIRST") < message.index("SECOND")


def test_a_turn_with_no_user_prompt_still_composes() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[], context_to_keep_package=build_package()
    )
    assert ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT in message
    assert "The parser is pure." in message


def test_a_package_carrying_nothing_still_composes() -> None:
    """A turn can produce nothing worth keeping; the prompt still travels."""
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "do the thing")],
        context_to_keep_package=ContextToKeepPackage(
            next_task="Ask the user which pad naming should win.", context_to_keep=[]
        ),
    )
    assert "do the thing" in message
    assert ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT in message


def test_the_message_is_mostly_the_material_it_carries() -> None:
    """Everything that is not prompt or context text is overhead."""
    prompt_text = "x" * 400
    package = ContextToKeepPackage(
        next_task="Ask the user which pad naming should win.", context_to_keep=["z" * 400]
    )
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, prompt_text)],
        context_to_keep_package=package,
    )
    carried_bytes = 400 * 2
    assert carried_bytes / len(message) > 0.85
