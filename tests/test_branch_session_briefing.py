"""Tests for what a branch session is told when it starts.

A driven session exposed why this must exist: nothing ever told the branch
agent that the handoff protocol existed, so it never emitted a package, so the
Stop hook never fired and the loop could not turn. The design assumed the agent
knew; nothing implemented it.

The briefing is also the branch's correction to what it inherits. It forks the
base, so it arrives believing it should only acknowledge and never act.
"""
from __future__ import annotations

import json

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    extract_context_to_keep_package_from_agent_response,
)
from context_handoff.orchestration.branch_session_briefing import (
    build_branch_session_briefing_text,
)


def test_the_briefing_names_the_fence_the_stop_hook_looks_for() -> None:
    """A protocol the agent cannot spell is a protocol it cannot follow."""
    assert CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG in build_branch_session_briefing_text()


def test_the_briefing_states_the_package_version() -> None:
    assert (
        f"\"context_to_keep_version\": {CONTEXT_TO_KEEP_PACKAGE_VERSION}"
        in build_branch_session_briefing_text()
    )


def test_the_briefing_names_both_required_fields() -> None:
    briefing_text = build_branch_session_briefing_text()
    assert "summary_of_work_completed_this_turn" in briefing_text
    assert "context_to_carry_forward" in briefing_text


def test_the_example_in_the_briefing_is_itself_a_valid_package() -> None:
    """If the worked example does not parse, the agent is being taught wrong.

    This runs the briefing's own example through the extractor the Stop hook
    uses, so the instructions cannot drift away from the parser.
    """
    extracted_package = extract_context_to_keep_package_from_agent_response(
        build_branch_session_briefing_text()
    )
    assert extracted_package is not None
    assert extracted_package.summary_of_work_completed_this_turn


def test_the_briefing_tells_the_branch_it_may_act() -> None:
    """It forks the base, which was told to acknowledge and do nothing else."""
    briefing_text = build_branch_session_briefing_text().lower()
    assert "you do the work" in briefing_text


def test_the_briefing_says_to_emit_the_package_at_the_end_of_every_turn() -> None:
    briefing_text = build_branch_session_briefing_text().lower()
    assert "every turn" in briefing_text


def test_the_briefing_asks_for_a_short_acknowledgement_only() -> None:
    """Starting a branch should not burn a turn on the agent doing something."""
    briefing_text = build_branch_session_briefing_text().lower()
    assert "acknowledge" in briefing_text


def test_the_briefing_excludes_itself_from_the_every_turn_rule() -> None:
    """A driven session showed why.

    Told to acknowledge and also to emit a package every turn, the agent
    emitted one for the briefing itself — and every later package reused that
    first summary, so real turns were handed off described as "acknowledged
    the briefing; no work performed".
    """
    briefing_text = build_branch_session_briefing_text().lower()
    assert "do not emit" in briefing_text
    assert "this briefing" in briefing_text


def test_the_briefing_demands_a_summary_of_the_turn_just_finished() -> None:
    briefing_text = build_branch_session_briefing_text().lower()
    assert "just finished" in briefing_text


def test_the_briefing_forbids_reusing_an_earlier_summary() -> None:
    briefing_text = build_branch_session_briefing_text().lower()
    assert "never reuse" in briefing_text


def test_the_briefing_is_stable_across_calls() -> None:
    """It seeds a session; a briefing that varied would make turns unreproducible."""
    assert build_branch_session_briefing_text() == build_branch_session_briefing_text()


def test_the_example_package_round_trips_through_json() -> None:
    briefing_text = build_branch_session_briefing_text()
    fence_open = briefing_text.index(f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}")
    block_start = briefing_text.index("\n", fence_open) + 1
    block_end = briefing_text.index("```", block_start)
    assert json.loads(briefing_text[block_start:block_end])
