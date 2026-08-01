"""Tests for the context-to-keep package: its schema and its extraction.

The spec describes one thing: the context the agent returns that it decides is
all that is needed going forward to understand what was done. One package of
context — not a narrative plus context.

An earlier version had a separate summary field, which was invented here rather
than taken from the spec. Measured over a twenty-turn run it was where the prose
accumulated, so it is gone.

Extraction is strict about content and lenient about surroundings: an agent
reply is prose with a block somewhere inside it, and a broken block must never
be the reason a session fails.
"""
from __future__ import annotations

import json

import pytest

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    ContextToKeepPackage,
    InvalidContextToKeepPackageError,
    extract_context_to_keep_package_from_agent_response,
    parse_context_to_keep_package,
)


def build_valid_package_dictionary(**overrides) -> dict:
    package_dictionary = {
        "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
        "context_to_keep": ["Pads are addressed by colour, not position."],
        "next_action": "Ask the user which pad naming should win.",
    }
    package_dictionary.update(overrides)
    return package_dictionary


def wrap_in_fenced_block(package_dictionary: dict) -> str:
    return (
        f"Some prose first.\n\n```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
        + json.dumps(package_dictionary, indent=2)
        + "\n```\n\nSome prose after.\n"
    )


def test_a_valid_package_parses_into_its_items() -> None:
    package = parse_context_to_keep_package(build_valid_package_dictionary())
    assert isinstance(package, ContextToKeepPackage)
    assert package.context_to_keep == ["Pads are addressed by colour, not position."]


def test_a_package_carrying_nothing_is_valid() -> None:
    """A turn can genuinely produce nothing worth keeping."""
    package = parse_context_to_keep_package(
        build_valid_package_dictionary(context_to_keep=[])
    )
    assert package.context_to_keep == []


def test_a_missing_context_field_is_rejected() -> None:
    package_dictionary = build_valid_package_dictionary()
    del package_dictionary["context_to_keep"]
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(package_dictionary)


def test_the_next_action_parses_and_is_stripped() -> None:
    package = parse_context_to_keep_package(
        build_valid_package_dictionary(next_action="  Report the results.  ")
    )
    assert package.next_action == "Report the results."


def test_a_missing_next_action_is_rejected() -> None:
    """The next session is opened to carry it out, so a package without one
    leaves that session with nothing to act on."""
    package_dictionary = build_valid_package_dictionary()
    del package_dictionary["next_action"]
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(package_dictionary)


def test_a_blank_next_action_is_rejected() -> None:
    """Present but empty is the same as absent for the session that receives it."""
    for blank_value in ("", "   ", "\n\t"):
        with pytest.raises(InvalidContextToKeepPackageError):
            parse_context_to_keep_package(
                build_valid_package_dictionary(next_action=blank_value)
            )


def test_a_next_action_that_is_not_a_string_is_rejected() -> None:
    for wrong_typed_value in (["a list"], {"a": "dict"}, 7, None, True):
        with pytest.raises(InvalidContextToKeepPackageError):
            parse_context_to_keep_package(
                build_valid_package_dictionary(next_action=wrong_typed_value)
            )


def test_the_next_action_survives_a_round_trip_through_json() -> None:
    """What the store writes has to be what the next rotation can read back."""
    original_package = parse_context_to_keep_package(build_valid_package_dictionary())
    reparsed_package = parse_context_to_keep_package(
        original_package.to_json_dictionary()
    )
    assert reparsed_package.next_action == original_package.next_action


def test_an_unknown_version_is_rejected() -> None:
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(
            build_valid_package_dictionary(context_to_keep_version=999)
        )


def test_context_items_must_be_strings() -> None:
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(
            build_valid_package_dictionary(context_to_keep=[{"not": "a string"}])
        )


def test_a_context_field_that_is_not_a_list_is_rejected() -> None:
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(
            build_valid_package_dictionary(context_to_keep="a single string")
        )


def test_blank_items_are_dropped_rather_than_carried() -> None:
    package = parse_context_to_keep_package(
        build_valid_package_dictionary(context_to_keep=["   ", "a real one", ""])
    )
    assert package.context_to_keep == ["a real one"]


def test_a_package_round_trips_through_its_dictionary_form() -> None:
    original = parse_context_to_keep_package(build_valid_package_dictionary())
    assert parse_context_to_keep_package(original.to_json_dictionary()) == original


def test_the_package_carries_no_summary_field() -> None:
    """A summary field was invented here and is where the prose accumulated."""
    package = parse_context_to_keep_package(build_valid_package_dictionary())
    assert not hasattr(package, "summary_of_work_completed_this_turn")
    assert "summary" not in json.dumps(package.to_json_dictionary())


def test_a_fenced_package_is_extracted_from_surrounding_prose() -> None:
    package = extract_context_to_keep_package_from_agent_response(
        wrap_in_fenced_block(build_valid_package_dictionary())
    )
    assert package is not None
    assert package.context_to_keep == ["Pads are addressed by colour, not position."]


def test_a_response_with_no_package_extracts_to_none() -> None:
    assert (
        extract_context_to_keep_package_from_agent_response("Just prose, no package.")
        is None
    )


def test_the_last_fenced_package_wins_when_several_appear() -> None:
    """An agent may quote the format before emitting the real block."""
    first = wrap_in_fenced_block(
        build_valid_package_dictionary(context_to_keep=["an illustrative example"])
    )
    second = wrap_in_fenced_block(
        build_valid_package_dictionary(context_to_keep=["the real one"])
    )
    package = extract_context_to_keep_package_from_agent_response(first + second)
    assert package is not None
    assert package.context_to_keep == ["the real one"]


def test_a_malformed_fenced_block_extracts_to_none_rather_than_raising() -> None:
    assert (
        extract_context_to_keep_package_from_agent_response(
            f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ not valid json \n```"
        )
        is None
    )


def test_a_valid_block_after_a_malformed_one_is_still_found() -> None:
    response = (
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ broken \n```\n"
        + wrap_in_fenced_block(build_valid_package_dictionary())
    )
    assert extract_context_to_keep_package_from_agent_response(response) is not None


def test_a_schema_valid_block_that_fails_validation_extracts_to_none() -> None:
    package_dictionary = build_valid_package_dictionary()
    del package_dictionary["context_to_keep"]
    assert (
        extract_context_to_keep_package_from_agent_response(
            wrap_in_fenced_block(package_dictionary)
        )
        is None
    )
