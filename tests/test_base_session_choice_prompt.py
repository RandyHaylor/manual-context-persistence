"""Tests for asking the user whether to start a new base session or resume one.

Reading and writing are injected, so the prompt is exercised as a pure
conversation: scripted answers in, a decision out. Nothing here touches a real
terminal.
"""
from __future__ import annotations

import pytest

from context_handoff.startup.base_session_choice_prompt import (
    BaseSessionChoice,
    ask_whether_to_create_or_resume_base_session,
)


def build_scripted_reader(scripted_answers: list[str]):
    remaining_answers = list(scripted_answers)

    def read_next_answer(_prompt_text: str) -> str:
        if not remaining_answers:
            raise AssertionError("the prompt asked for more input than was scripted")
        return remaining_answers.pop(0)

    return read_next_answer


def test_choosing_new_returns_a_create_decision() -> None:
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["new"]),
        write_line=lambda _text: None,
        known_base_session_identifiers=[],
    )
    assert choice == BaseSessionChoice(
        should_create_new_base_session=True, base_session_identifier_to_resume=None
    )


def test_choosing_resume_asks_for_the_identifier() -> None:
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["resume", "an-existing-base"]),
        write_line=lambda _text: None,
        known_base_session_identifiers=[],
    )
    assert choice.should_create_new_base_session is False
    assert choice.base_session_identifier_to_resume == "an-existing-base"


def test_an_unrecognised_answer_is_asked_again(written_lines=None) -> None:
    written_lines = []
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["maybe", "new"]),
        write_line=written_lines.append,
        known_base_session_identifiers=[],
    )
    assert choice.should_create_new_base_session is True
    assert any("new" in line.lower() for line in written_lines)


def test_answers_are_accepted_case_insensitively_and_trimmed() -> None:
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["  NEW  "]),
        write_line=lambda _text: None,
        known_base_session_identifiers=[],
    )
    assert choice.should_create_new_base_session is True


def test_a_blank_identifier_is_asked_again(written_lines=None) -> None:
    """Accepting blank would silently create a new base and strand the old one."""
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["resume", "   ", "the-real-base"]),
        write_line=lambda _text: None,
        known_base_session_identifiers=[],
    )
    assert choice.base_session_identifier_to_resume == "the-real-base"


def test_known_base_sessions_are_offered_and_selectable_by_number() -> None:
    """Typing a UUID by hand is the kind of thing people get wrong."""
    written_lines: list[str] = []
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["resume", "2"]),
        write_line=written_lines.append,
        known_base_session_identifiers=["base-alpha", "base-beta"],
    )
    assert choice.base_session_identifier_to_resume == "base-beta"
    assert any("base-beta" in line for line in written_lines)


def test_an_out_of_range_number_is_treated_as_a_literal_identifier() -> None:
    """A session identifier is opaque; refusing digits would be wrong."""
    choice = ask_whether_to_create_or_resume_base_session(
        read_answer=build_scripted_reader(["resume", "99"]),
        write_line=lambda _text: None,
        known_base_session_identifiers=["base-alpha"],
    )
    assert choice.base_session_identifier_to_resume == "99"


def test_end_of_input_while_choosing_raises() -> None:
    """A closed stdin must not be read as "yes, create a new base"."""

    def read_answer_raising_end_of_input(_prompt_text: str) -> str:
        raise EOFError

    with pytest.raises(EOFError):
        ask_whether_to_create_or_resume_base_session(
            read_answer=read_answer_raising_end_of_input,
            write_line=lambda _text: None,
            known_base_session_identifiers=[],
        )
