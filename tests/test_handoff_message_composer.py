"""Tests for the text submitted to the base session at each rotation.

The composed message is the only thing the base session ever receives, so these
tests pin down what must be in it: the user's verbatim words, the agent's
carried context, and an instruction to acknowledge without doing work.
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
        summary_of_work_completed_this_turn="Wrote the stream parser and its tests.",
        context_to_carry_forward=[
            "The parser is pure.",
            "Timeouts are reported, not raised.",
        ],
    )


def test_the_message_contains_the_user_prompt_verbatim() -> None:
    awkward_prompt_text = "  keep   my  spacing\tand “quotes”  "
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, awkward_prompt_text)],
        context_to_keep_package=build_package(),
    )
    assert awkward_prompt_text in message


def test_the_message_contains_the_turn_summary() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[], context_to_keep_package=build_package()
    )
    assert "Wrote the stream parser and its tests." in message


def test_the_message_contains_every_carried_context_entry() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[], context_to_keep_package=build_package()
    )
    assert "The parser is pure." in message
    assert "Timeouts are reported, not raised." in message


def test_the_message_ends_with_the_acknowledge_only_instruction() -> None:
    """The base session must accumulate context, not start doing the work."""
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "do the thing")],
        context_to_keep_package=build_package(),
    )
    assert message.rstrip().endswith(ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT)


def test_multiple_prompts_appear_in_order() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "FIRST PROMPT"), build_entry(1, "SECOND PROMPT")],
        context_to_keep_package=build_package(),
    )
    assert message.index("FIRST PROMPT") < message.index("SECOND PROMPT")


def test_pre_submission_content_is_included_when_present() -> None:
    """A reply of "yes" is only a requirement alongside the question it answers."""
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[
            build_entry(0, "yes", pre_submission_content="Shall I use adapters?")
        ],
        context_to_keep_package=build_package(),
    )
    assert "Shall I use adapters?" in message


def test_a_turn_with_no_user_prompt_still_composes() -> None:
    """Rotation can follow an agent-only turn; the handoff is still worth sending."""
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[], context_to_keep_package=build_package()
    )
    assert ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT in message
    assert "Wrote the stream parser and its tests." in message


def test_a_package_with_no_carried_context_still_composes() -> None:
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "do the thing")],
        context_to_keep_package=ContextToKeepPackage(
            summary_of_work_completed_this_turn="Nothing worth carrying.",
            context_to_carry_forward=[],
        ),
    )
    assert "Nothing worth carrying." in message
    assert ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT in message


def test_the_message_does_not_contain_the_branch_transcript() -> None:
    """Compactness is the whole design; only summary and carried context travel."""
    message = compose_handoff_message_for_base_session(
        user_prompt_entries=[build_entry(0, "do the thing")],
        context_to_keep_package=build_package(),
    )
    assert len(message) < 4000
