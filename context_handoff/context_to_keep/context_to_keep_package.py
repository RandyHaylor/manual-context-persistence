"""The handoff package an agent returns at the end of a turn.

The spec describes one thing: the context the agent returns that it decides is
all that is needed going forward to understand what was done. So the package is
that context and nothing else.

An earlier version also carried a summary field. It was invented here, not
taken from the spec, and across a twenty-turn run it was where narrative
accumulated — the base session filled with prose about what had happened rather
than with what a later session needed. It is gone.

Extraction is lenient about surroundings and strict about content. An agent
reply is prose with a block somewhere inside it, and an agent may quote the
format before emitting the real thing, so the LAST valid block wins. A malformed
block yields None rather than raising: the Stop hook that calls this must never
be the reason a session fails.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

CONTEXT_TO_KEEP_PACKAGE_VERSION = 1
CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG = "context-to-keep"
CONTEXT_TO_KEEP_FIELD_NAME = "context_to_keep"
CONTEXT_TO_KEEP_VERSION_FIELD_NAME = "context_to_keep_version"

_FENCED_CONTEXT_TO_KEEP_BLOCK_PATTERN = re.compile(
    r"```" + re.escape(CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG) + r"\s*\n(.*?)```",
    re.DOTALL,
)


class InvalidContextToKeepPackageError(ValueError):
    """A candidate package did not satisfy the handoff contract."""


@dataclass(frozen=True)
class ContextToKeepPackage:
    context_to_keep: list[str] = field(default_factory=list)

    def to_json_dictionary(self) -> dict[str, Any]:
        return {
            CONTEXT_TO_KEEP_VERSION_FIELD_NAME: CONTEXT_TO_KEEP_PACKAGE_VERSION,
            CONTEXT_TO_KEEP_FIELD_NAME: list(self.context_to_keep),
        }


def parse_context_to_keep_package(
    candidate_package_dictionary: Any,
) -> ContextToKeepPackage:
    """Validate a decoded package, raising ``InvalidContextToKeepPackageError``."""
    if not isinstance(candidate_package_dictionary, dict):
        raise InvalidContextToKeepPackageError(
            f"expected a JSON object, got {type(candidate_package_dictionary).__name__}"
        )

    declared_version = candidate_package_dictionary.get(
        CONTEXT_TO_KEEP_VERSION_FIELD_NAME
    )
    if declared_version != CONTEXT_TO_KEEP_PACKAGE_VERSION:
        raise InvalidContextToKeepPackageError(
            f"unsupported {CONTEXT_TO_KEEP_VERSION_FIELD_NAME} {declared_version!r}; "
            f"this build understands {CONTEXT_TO_KEEP_PACKAGE_VERSION}"
        )

    if CONTEXT_TO_KEEP_FIELD_NAME not in candidate_package_dictionary:
        raise InvalidContextToKeepPackageError(
            f"{CONTEXT_TO_KEEP_FIELD_NAME} is required; without it the package "
            "carries nothing"
        )

    context_items = candidate_package_dictionary[CONTEXT_TO_KEEP_FIELD_NAME]
    if not isinstance(context_items, list) or not all(
        isinstance(item, str) for item in context_items
    ):
        raise InvalidContextToKeepPackageError(
            f"{CONTEXT_TO_KEEP_FIELD_NAME} must be a list of strings"
        )

    # A blank item carries nothing and would occupy a line in the base session
    # for the life of the project.
    return ContextToKeepPackage(
        context_to_keep=[item.strip() for item in context_items if item.strip()]
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
