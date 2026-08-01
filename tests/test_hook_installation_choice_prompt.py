"""Tests for the install-or-abort question.

Reached only when the project already has a settings file that does not register
our hooks. There is deliberately no third answer: continuing without capture
looks healthy and records nothing, and the operator who genuinely wants that
passes the skip flag on the command line, where it is an explicit choice.
"""
from __future__ import annotations

import pytest

from context_handoff.startup.hook_installation_choice_prompt import (
    ask_whether_to_install_missing_hooks,
)


class ScriptedConversation:
    def __init__(self, answers):
        self.remaining_answers = list(answers)
        self.written_lines: list[str] = []
        self.prompts_shown: list[str] = []

    def read_answer(self, prompt_text: str) -> str:
        self.prompts_shown.append(prompt_text)
        if not self.remaining_answers:
            raise EOFError
        return self.remaining_answers.pop(0)

    def ask(self) -> bool:
        return ask_whether_to_install_missing_hooks(
            read_answer=self.read_answer,
            write_line=self.written_lines.append,
            missing_hook_event_names=["Stop", "UserPromptSubmit"],
            settings_file_path="/project/.claude/settings.local.json",
        )


@pytest.mark.parametrize("answer", ["install", "i", "yes", "y", "INSTALL", " Install "])
def test_an_install_answer_is_accepted_in_its_usual_forms(answer: str) -> None:
    assert ScriptedConversation([answer]).ask() is True


@pytest.mark.parametrize("answer", ["abort", "a", "no", "n", "quit", "ABORT"])
def test_an_abort_answer_is_accepted_in_its_usual_forms(answer: str) -> None:
    assert ScriptedConversation([answer]).ask() is False


def test_an_unrecognised_answer_is_re_asked_rather_than_defaulted() -> None:
    """Guessing is destructive in one direction and merely annoying in the other."""
    conversation = ScriptedConversation(["maybe", "", "install"])

    assert conversation.ask() is True
    assert len(conversation.prompts_shown) == 3
    assert conversation.written_lines.count("Please answer 'install' or 'abort'.") == 2


def test_a_closed_stdin_is_not_consent_to_write_the_operators_file() -> None:
    conversation = ScriptedConversation([])
    with pytest.raises(EOFError):
        conversation.ask()


def test_the_question_names_the_file_and_what_is_missing_from_it() -> None:
    """An operator cannot answer this without knowing what is about to change."""
    conversation = ScriptedConversation(["abort"])

    conversation.ask()

    first_line = conversation.written_lines[0]
    assert "/project/.claude/settings.local.json" in first_line
    assert "Stop" in first_line
    assert "UserPromptSubmit" in first_line


def test_continuing_without_the_hooks_is_not_offered_as_an_answer() -> None:
    """That belongs on the command line, not in a menu chosen in passing."""
    conversation = ScriptedConversation(["abort"])

    conversation.ask()

    offered_text = " ".join(conversation.prompts_shown + conversation.written_lines).lower()
    assert "skip" not in offered_text
    assert "continue" not in offered_text
    assert "ignore" not in offered_text
