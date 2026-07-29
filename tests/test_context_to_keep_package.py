"""Tests for the context-to-keep package: its schema and its extraction.

The package is the one thing the agent itself must produce correctly, so the
parser is strict about what it accepts and lenient about what surrounds it — an
agent reply is prose with a package somewhere inside, not a JSON document.
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
        "summary_of_work_completed_this_turn": "Added the stream parser.",
        "context_to_carry_forward": ["The parser is pure and takes an observer."],
    }
    package_dictionary.update(overrides)
    return package_dictionary


def wrap_in_fenced_block(package_dictionary: dict) -> str:
    return (
        f"Some prose first.\n\n```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
        + json.dumps(package_dictionary, indent=2)
        + "\n```\n\nSome prose after.\n"
    )


def test_a_valid_package_parses_into_its_fields() -> None:
    package = parse_context_to_keep_package(build_valid_package_dictionary())
    assert isinstance(package, ContextToKeepPackage)
    assert package.summary_of_work_completed_this_turn == "Added the stream parser."
    assert package.context_to_carry_forward == [
        "The parser is pure and takes an observer."
    ]


def test_a_missing_summary_is_rejected() -> None:
    """The handoff is useless if the base session cannot tell what happened."""
    package_dictionary = build_valid_package_dictionary()
    del package_dictionary["summary_of_work_completed_this_turn"]
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(package_dictionary)


def test_an_empty_summary_is_rejected() -> None:
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(
            build_valid_package_dictionary(summary_of_work_completed_this_turn="   ")
        )


def test_an_unknown_version_is_rejected() -> None:
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(
            build_valid_package_dictionary(context_to_keep_version=999)
        )


def test_carry_forward_entries_must_be_strings() -> None:
    with pytest.raises(InvalidContextToKeepPackageError):
        parse_context_to_keep_package(
            build_valid_package_dictionary(context_to_carry_forward=[{"not": "a string"}])
        )


def test_an_empty_carry_forward_list_is_allowed() -> None:
    """A turn may genuinely produce nothing worth carrying; that is not an error."""
    package = parse_context_to_keep_package(
        build_valid_package_dictionary(context_to_carry_forward=[])
    )
    assert package.context_to_carry_forward == []


def test_a_package_round_trips_through_its_dictionary_form() -> None:
    original_package = parse_context_to_keep_package(build_valid_package_dictionary())
    assert (
        parse_context_to_keep_package(original_package.to_json_dictionary())
        == original_package
    )


def test_a_fenced_package_is_extracted_from_surrounding_prose() -> None:
    agent_response_text = wrap_in_fenced_block(build_valid_package_dictionary())
    package = extract_context_to_keep_package_from_agent_response(agent_response_text)
    assert package is not None
    assert package.summary_of_work_completed_this_turn == "Added the stream parser."


def test_a_response_with_no_package_extracts_to_none() -> None:
    assert (
        extract_context_to_keep_package_from_agent_response("Just prose, no package.")
        is None
    )


def test_the_last_fenced_package_wins_when_several_appear() -> None:
    """An agent may quote the format before emitting the real package."""
    first_block = wrap_in_fenced_block(
        build_valid_package_dictionary(
            summary_of_work_completed_this_turn="an illustrative example"
        )
    )
    second_block = wrap_in_fenced_block(
        build_valid_package_dictionary(
            summary_of_work_completed_this_turn="the real handoff"
        )
    )
    package = extract_context_to_keep_package_from_agent_response(
        first_block + second_block
    )
    assert package is not None
    assert package.summary_of_work_completed_this_turn == "the real handoff"


def test_a_malformed_fenced_block_extracts_to_none_rather_than_raising() -> None:
    """A broken package must not take down the Stop hook that reads it."""
    agent_response_text = (
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ not valid json \n```"
    )
    assert extract_context_to_keep_package_from_agent_response(agent_response_text) is None


def test_a_valid_block_after_a_malformed_one_is_still_found() -> None:
    agent_response_text = (
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n{{ broken \n```\n"
        + wrap_in_fenced_block(build_valid_package_dictionary())
    )
    package = extract_context_to_keep_package_from_agent_response(agent_response_text)
    assert package is not None


def test_a_schema_valid_block_that_fails_validation_extracts_to_none() -> None:
    package_dictionary = build_valid_package_dictionary()
    del package_dictionary["summary_of_work_completed_this_turn"]
    agent_response_text = wrap_in_fenced_block(package_dictionary)
    assert extract_context_to_keep_package_from_agent_response(agent_response_text) is None
