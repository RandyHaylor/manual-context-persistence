"""Tests for what a session is told when it is opened for the user.

The block is emitted by the session the user works in, never by the one that
receives it, so the instruction to emit it is given at open time rather than
sitting in the preamble every session would inherit.

That session is the one the user talks to, so this says nothing about the
machinery it is part of. It describes one output format and what belongs in it.

The shape is the ordinary output-contract convention: a named format section,
the fields with their types, where the block may appear, and one filled example.
"""
from __future__ import annotations

import json

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_FIELD_NAME,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    CONTEXT_TO_KEEP_VERSION_FIELD_NAME,
    NEXT_ACTION_FIELD_NAME,
    extract_context_to_keep_package_from_agent_response,
)
from context_handoff.orchestration.branch_session_preamble import (
    BRANCH_SESSION_PREAMBLE_TEXT,
    FIRST_BRANCH_SESSION_PREAMBLE_TEXT,
    GIT_COMMIT_REQUIREMENT_SENTENCE,
    REQUEST_INSTRUCTIONS_SENTENCE,
    build_branch_session_preamble_text,
    build_first_branch_session_preamble_text,
    build_rotated_branch_session_preamble_text,
)


def read_example_block(preamble_text: str) -> dict:
    fence_open = preamble_text.index(f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}")
    block_start = preamble_text.index("\n", fence_open) + 1
    block_end = preamble_text.index("```", block_start)
    return json.loads(preamble_text[block_start:block_end])


def guidance_before_the_example(preamble_text: str) -> str:
    """Everything up to the fenced example — the part that states the contract."""
    return preamble_text.split("```")[0]


def test_the_example_block_matches_the_shape_the_parser_expects() -> None:
    """Catches the format drifting away from what the Stop hook reads."""
    example = read_example_block(BRANCH_SESSION_PREAMBLE_TEXT)
    assert set(example) == {
        CONTEXT_TO_KEEP_VERSION_FIELD_NAME,
        CONTEXT_TO_KEEP_FIELD_NAME,
        NEXT_ACTION_FIELD_NAME,
    }
    assert example[CONTEXT_TO_KEEP_VERSION_FIELD_NAME] == CONTEXT_TO_KEEP_PACKAGE_VERSION


def test_the_example_is_filled_in_rather_than_a_copyable_placeholder() -> None:
    """A placeholder is something an agent can emit verbatim; a fact is not."""
    example_entries = read_example_block(BRANCH_SESSION_PREAMBLE_TEXT)[
        CONTEXT_TO_KEEP_FIELD_NAME
    ]
    assert example_entries
    for entry_text in example_entries:
        assert "<" not in entry_text
        assert "..." not in entry_text


def test_the_example_is_one_the_real_extractor_accepts() -> None:
    assert (
        extract_context_to_keep_package_from_agent_response(
            BRANCH_SESSION_PREAMBLE_TEXT
        )
        is not None
    )


def test_there_is_exactly_one_fenced_block_to_copy() -> None:
    """Two blocks means one of them is the wrong thing to emit."""
    assert BRANCH_SESSION_PREAMBLE_TEXT.count(
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}"
    ) == 1


def test_it_carries_no_field_inviting_a_narrative() -> None:
    """A summary field was invented here, and is where the prose accumulated."""
    assert "summary" not in BRANCH_SESSION_PREAMBLE_TEXT.lower()


def test_both_fields_are_named_with_their_types() -> None:
    """The typed field list is what makes this a contract rather than a hint."""
    guidance = guidance_before_the_example(BRANCH_SESSION_PREAMBLE_TEXT)
    assert f"`{CONTEXT_TO_KEEP_VERSION_FIELD_NAME}` (integer)" in guidance
    assert f"`{CONTEXT_TO_KEEP_FIELD_NAME}` (array of strings)" in guidance


def test_the_field_list_is_stated_to_be_exhaustive() -> None:
    guidance = guidance_before_the_example(BRANCH_SESSION_PREAMBLE_TEXT).lower()
    assert "all required" in guidance
    assert "no others" in guidance


def test_the_guidance_asks_for_bullets_about_the_deliverable() -> None:
    """Bullets about the deliverable, not an account of the turn."""
    guidance = guidance_before_the_example(BRANCH_SESSION_PREAMBLE_TEXT).lower()
    assert "concise bullets" in guidance
    assert "deliverable" in guidance
    assert "last assigned task" in guidance


def test_the_guidance_states_what_the_bullets_are_for() -> None:
    """The test of whether a bullet earns its place."""
    guidance = guidance_before_the_example(BRANCH_SESSION_PREAMBLE_TEXT).lower()
    assert "understand the work" in guidance
    assert "concluding reply" in guidance


def test_emission_is_triggered_by_work_worth_saving() -> None:
    """Not by a turn ending.

    Every turn fires on a question or an acknowledgement, and each of those
    costs a full rotation to carry nothing. A turn named in advance points at
    whichever turn this text arrives in, where no work has happened yet.
    """
    lowercased = BRANCH_SESSION_PREAMBLE_TEXT.lower()
    assert "work worth saving" in lowercased
    assert "this turn" not in lowercased
    assert "every turn" not in lowercased


def test_it_says_when_to_leave_the_block_out() -> None:
    """Without this the trigger reads as advice and the block appears anyway."""
    lowercased = BRANCH_SESSION_PREAMBLE_TEXT.lower()
    assert "skip it" in lowercased
    assert "question" in lowercased
    assert "acknowledgement" in lowercased


def test_it_never_describes_the_machinery() -> None:
    """This is the session the user talks to; it needs no theory of itself."""
    lowercased = BRANCH_SESSION_PREAMBLE_TEXT.lower()
    for machinery_word in (
        "base session",
        "branch",
        "fork",
        "handoff",
        "short-lived",
        "resumed",
        "orchestrat",
        "rotation",
    ):
        assert machinery_word not in lowercased, (
            f"it mentions {machinery_word!r}; the working session reads this"
        )


def test_it_never_governs_how_the_agent_replies() -> None:
    lowercased = BRANCH_SESSION_PREAMBLE_TEXT.lower()
    for reply_instruction in (
        "one short sentence",
        "reply with",
        "briefly",
        "be brief",
        "and nothing else",
    ):
        assert reply_instruction not in lowercased


def test_a_commit_is_not_required_by_default() -> None:
    """A project with no repository must never be told to commit."""
    assert GIT_COMMIT_REQUIREMENT_SENTENCE not in BRANCH_SESSION_PREAMBLE_TEXT
    assert "git" not in BRANCH_SESSION_PREAMBLE_TEXT.lower()
    assert build_branch_session_preamble_text() == BRANCH_SESSION_PREAMBLE_TEXT


def test_the_commit_requirement_appears_only_when_it_is_switched_on() -> None:
    with_commit = build_branch_session_preamble_text(require_git_commit=True)
    assert GIT_COMMIT_REQUIREMENT_SENTENCE in with_commit
    assert "commit" in with_commit.lower()


def test_switching_the_commit_requirement_on_changes_nothing_else() -> None:
    """The contract is the same document either way, plus one sentence."""
    with_commit = build_branch_session_preamble_text(require_git_commit=True)
    assert read_example_block(with_commit) == read_example_block(
        BRANCH_SESSION_PREAMBLE_TEXT
    )
    assert with_commit.replace(f"{GIT_COMMIT_REQUIREMENT_SENTENCE}\n\n", "") == (
        BRANCH_SESSION_PREAMBLE_TEXT
    )


def test_the_commit_is_asked_for_before_the_block_is_emitted() -> None:
    """A commit made after the block would not be described by it."""
    with_commit = build_branch_session_preamble_text(require_git_commit=True)
    assert with_commit.index(GIT_COMMIT_REQUIREMENT_SENTENCE) < with_commit.index(
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}"
    )


def test_the_contract_requires_a_next_action_and_says_what_counts_as_one() -> None:
    """Anything is a valid next action, so the field list has to say so.

    Without the examples it reads as "the next unit of building", and a session
    whose honest next step is a question has nothing valid to write.
    """
    guidance = guidance_before_the_example(BRANCH_SESSION_PREAMBLE_TEXT)
    assert f"`{NEXT_ACTION_FIELD_NAME}` (string)" in guidance
    lowercased = guidance.lower()
    assert "the next action to take" in lowercased
    assert "asking the user a question" in lowercased
    assert "reporting results" in lowercased


def test_the_example_names_a_next_action_that_is_not_more_building() -> None:
    example = read_example_block(BRANCH_SESSION_PREAMBLE_TEXT)
    assert example[NEXT_ACTION_FIELD_NAME].strip()


def test_a_rotated_session_is_seeded_with_the_task_it_was_given() -> None:
    """The point of the field: the loop continues rather than restarting."""
    rotated_text = build_rotated_branch_session_preamble_text(
        "Report the duplicate-selector findings to the user."
    )
    assert "Report the duplicate-selector findings to the user." in rotated_text
    assert REQUEST_INSTRUCTIONS_SENTENCE not in rotated_text


def test_a_rotated_session_is_given_the_task_before_the_output_format() -> None:
    """Every seed opens with what to do, then how to report it."""
    rotated_text = build_rotated_branch_session_preamble_text("Do the next thing.")
    assert rotated_text.index("Do the next thing.") < rotated_text.index(
        "## Output format"
    )


def test_every_seed_ends_with_the_identical_contract() -> None:
    """One contract, three openings — not three documents to keep in step."""
    assert build_rotated_branch_session_preamble_text("anything").endswith(
        BRANCH_SESSION_PREAMBLE_TEXT
    )
    assert FIRST_BRANCH_SESSION_PREAMBLE_TEXT.endswith(BRANCH_SESSION_PREAMBLE_TEXT)


def test_the_commit_requirement_reaches_a_rotated_session_too() -> None:
    assert GIT_COMMIT_REQUIREMENT_SENTENCE in (
        build_rotated_branch_session_preamble_text("anything", require_git_commit=True)
    )
    assert GIT_COMMIT_REQUIREMENT_SENTENCE not in (
        build_rotated_branch_session_preamble_text("anything")
    )


def test_only_the_first_session_is_told_to_ask_for_instructions() -> None:
    """Found in a real run, so it is pinned rather than left to be tidied away.

    The first session of a run is the only one opened before the user has said
    anything: this text arrives as a message, the session answers it, and with no
    stated first action it looked for a request, found none, and replied asking
    what the user wanted — a reply to nobody.

    Every later session is opened because the user did speak and work was done,
    so the same sentence there would contradict the situation it is in.
    """
    assert REQUEST_INSTRUCTIONS_SENTENCE in FIRST_BRANCH_SESSION_PREAMBLE_TEXT
    assert REQUEST_INSTRUCTIONS_SENTENCE not in BRANCH_SESSION_PREAMBLE_TEXT


def test_the_first_action_comes_before_the_output_format() -> None:
    """What to do now, then how to report later."""
    assert FIRST_BRANCH_SESSION_PREAMBLE_TEXT.index(
        REQUEST_INSTRUCTIONS_SENTENCE
    ) < FIRST_BRANCH_SESSION_PREAMBLE_TEXT.index("## Output format")


def test_both_sessions_receive_the_identical_contract() -> None:
    """The difference is one sentence, not a second format to keep in step."""
    assert FIRST_BRANCH_SESSION_PREAMBLE_TEXT.endswith(BRANCH_SESSION_PREAMBLE_TEXT)


def test_the_commit_requirement_reaches_the_first_session_too() -> None:
    assert GIT_COMMIT_REQUIREMENT_SENTENCE in build_first_branch_session_preamble_text(
        require_git_commit=True
    )
    assert GIT_COMMIT_REQUIREMENT_SENTENCE not in (
        build_first_branch_session_preamble_text()
    )


def test_it_stays_short_enough_to_read() -> None:
    """It is a contract now, not one sentence, but it is still not a document."""
    assert len(build_branch_session_preamble_text(require_git_commit=True)) < 1200
