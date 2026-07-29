"""The handoff package an agent emits at the end of a turn.

This is the one part of the protocol the agent itself must get right, so the
shape is deliberately small: what happened this turn, and what the next turn
needs to know. A turn's full transcript is explicitly not carried — keeping the
base session compact is the entire point of the design.

Extraction is lenient about surroundings and strict about content. An agent
reply is prose with a package somewhere inside it, and an agent may quote the
format before emitting the real thing, so the LAST valid block wins. A
malformed package yields None rather than raising: the Stop hook that calls
this must never be the reason a session breaks.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

CONTEXT_TO_KEEP_PACKAGE_VERSION = 1
CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG = "context-to-keep"

_FENCED_CONTEXT_TO_KEEP_BLOCK_PATTERN = re.compile(
    r"```" + re.escape(CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG) + r"\s*\n(.*?)```",
    re.DOTALL,
)


class InvalidContextToKeepPackageError(ValueError):
    """A candidate package did not satisfy the handoff contract."""


@dataclass(frozen=True)
class ContextToKeepPackage:
    summary_of_work_completed_this_turn: str
    context_to_carry_forward: list[str] = field(default_factory=list)

    def to_json_dictionary(self) -> dict[str, Any]:
        return {
            "context_to_keep_version": CONTEXT_TO_KEEP_PACKAGE_VERSION,
            "summary_of_work_completed_this_turn": (
                self.summary_of_work_completed_this_turn
            ),
            "context_to_carry_forward": list(self.context_to_carry_forward),
        }


def parse_context_to_keep_package(
    candidate_package_dictionary: Any,
) -> ContextToKeepPackage:
    """Validate a decoded package, raising ``InvalidContextToKeepPackageError``."""
    if not isinstance(candidate_package_dictionary, dict):
        raise InvalidContextToKeepPackageError(
            f"expected a JSON object, got {type(candidate_package_dictionary).__name__}"
        )

    declared_version = candidate_package_dictionary.get("context_to_keep_version")
    if declared_version != CONTEXT_TO_KEEP_PACKAGE_VERSION:
        raise InvalidContextToKeepPackageError(
            f"unsupported context_to_keep_version {declared_version!r}; "
            f"this build understands {CONTEXT_TO_KEEP_PACKAGE_VERSION}"
        )

    summary_text = candidate_package_dictionary.get(
        "summary_of_work_completed_this_turn"
    )
    if not isinstance(summary_text, str) or not summary_text.strip():
        raise InvalidContextToKeepPackageError(
            "summary_of_work_completed_this_turn must be a non-empty string; "
            "without it the base session cannot tell what the turn did"
        )

    carry_forward_entries = candidate_package_dictionary.get(
        "context_to_carry_forward", []
    )
    if not isinstance(carry_forward_entries, list) or not all(
        isinstance(entry, str) for entry in carry_forward_entries
    ):
        raise InvalidContextToKeepPackageError(
            "context_to_carry_forward must be a list of strings"
        )

    return ContextToKeepPackage(
        summary_of_work_completed_this_turn=summary_text.strip(),
        context_to_carry_forward=list(carry_forward_entries),
    )


def extract_context_to_keep_package_from_agent_response(
    agent_response_text: str,
) -> Optional[ContextToKeepPackage]:
    """Return the last valid package in an agent reply, or None if there is none."""
    fenced_block_bodies = _FENCED_CONTEXT_TO_KEEP_BLOCK_PATTERN.findall(
        agent_response_text
    )
    for block_body_text in reversed(fenced_block_bodies):
        try:
            decoded_block = json.loads(block_body_text)
        except json.JSONDecodeError:
            continue
        try:
            return parse_context_to_keep_package(decoded_block)
        except InvalidContextToKeepPackageError:
            continue
    return None
