"""What a session is told when it is opened for the user.

The block is emitted here and never by the session that receives it, so the
instruction to emit it is given at open time rather than in the preamble every
session would inherit.

This is the session the user works in. It says nothing about the machinery it
belongs to — an output format, and what belongs in it.

Sending it also serves a second purpose: a new session's transcript is not
written to disk until the session has content, so this is what makes it durable.

The shape follows the ordinary output-contract convention: a named format
section, the fields with their types, where the block may appear, and one filled
example. There is exactly one fenced block in this text, and it is a real
example rather than a skeleton with placeholders, because a placeholder is
something an agent can copy verbatim and a filled example is not.

Emission is triggered by having done work worth saving, not by finishing a turn.
Every turn would fire on a question or an acknowledgement, which costs a full
rotation to carry nothing; a turn nominated in advance points at whichever turn
this text arrives in, where no work has happened yet.

Two builders, because the first session of a run is the only one nobody has
spoken to yet. The contract is identical in both; the first one also states that
no request has arrived.
"""
from __future__ import annotations

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_FIELD_NAME,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
    CONTEXT_TO_KEEP_VERSION_FIELD_NAME,
    NEXT_ACTION_FIELD_NAME,
)

# An example entry rather than a placeholder: a constraint someone would
# genuinely need carried forward, and not recoverable by reading the files.
EXAMPLE_CONTEXT_TO_KEEP_ENTRY_TEXT = (
    "pad aria-labels are positional while the script uses colour names; "
    "do not change them unprompted"
)

# A question rather than more work, so the example does not suggest the next action
# always has to be another unit of building.
EXAMPLE_NEXT_ACTION_TEXT = (
    "Ask the user whether the aria-label naming should be made consistent."
)

GIT_COMMIT_REQUIREMENT_SENTENCE = (
    "Commit your work with git before you include the block."
)

# Only the first session of a run opens with nobody having said anything yet.
# This text arrives as a message and the session answers it, so with no stated
# first action it goes looking for a request, finds none, and says so — a reply
# to nobody. Every later session is opened because the user has already spoken
# and work has already been done, so telling one of those to ask for
# instructions would contradict the situation it is in.
REQUEST_INSTRUCTIONS_SENTENCE = "Request instructions from the user."

# Every seed opens with what to do, then how to report it. For the first session
# that is the sentence above; afterwards it is the task the previous session
# named, introduced by the field's own name so the two cannot drift apart.
NEXT_ACTION_LABEL_TEXT = f"{NEXT_ACTION_FIELD_NAME}:"


def build_branch_session_preamble_text(require_git_commit: bool = False) -> str:
    """The text a newly opened user-facing session is seeded with.

    ``require_git_commit`` adds the commit requirement. It is off by default so
    that a project without a repository is never told to commit.
    """
    commit_requirement_paragraph = (
        f"{GIT_COMMIT_REQUIREMENT_SENTENCE}\n\n" if require_git_commit else ""
    )
    return (
        "## Output format\n\n"
        "Once you have done any amount of work worth saving, include one "
        f"`{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}` block at the end of your "
        "response. Skip it while a request is still a question, an "
        "acknowledgement, or a discussion with nothing to record.\n\n"
        f"{commit_requirement_paragraph}"
        "Fields, all required, and no others:\n\n"
        f"- `{CONTEXT_TO_KEEP_VERSION_FIELD_NAME}` (integer): always "
        f"{CONTEXT_TO_KEEP_PACKAGE_VERSION}.\n"
        f"- `{CONTEXT_TO_KEEP_FIELD_NAME}` (array of strings): concise bullets "
        "about the deliverable from the last assigned task that give the "
        "information necessary to understand the work or receive the final "
        "concluding reply. Leave out anything recoverable by reading the files.\n"
        f"- `{NEXT_ACTION_FIELD_NAME}` (string): the next action to take — work, "
        "research, asking the user a question, reporting results.\n\n"
        "Example:\n\n"
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
        "{\n"
        f'  "{CONTEXT_TO_KEEP_VERSION_FIELD_NAME}": '
        f"{CONTEXT_TO_KEEP_PACKAGE_VERSION},\n"
        f'  "{CONTEXT_TO_KEEP_FIELD_NAME}": [\n'
        f'    "{EXAMPLE_CONTEXT_TO_KEEP_ENTRY_TEXT}"\n'
        "  ],\n"
        f'  "{NEXT_ACTION_FIELD_NAME}": "{EXAMPLE_NEXT_ACTION_TEXT}"\n'
        "}\n"
        "```"
    )


def build_first_branch_session_preamble_text(require_git_commit: bool = False) -> str:
    """The text the first session of a run is seeded with.

    The same contract as every other session, preceded by the one thing that is
    true only at the start: nothing has been asked yet.
    """
    return (
        f"{REQUEST_INSTRUCTIONS_SENTENCE}\n\n"
        f"{build_branch_session_preamble_text(require_git_commit=require_git_commit)}"
    )


def build_rotated_branch_session_preamble_text(
    next_action_text: str, require_git_commit: bool = False
) -> str:
    """The text a session opened after a completed turn is seeded with.

    The task the previous session named, then the same contract. This is what
    makes the loop continue rather than restart: without it a session inherits
    everything that was done and no statement of what to do about it.
    """
    return (
        f"{NEXT_ACTION_LABEL_TEXT} {next_action_text}\n\n"
        f"{build_branch_session_preamble_text(require_git_commit=require_git_commit)}"
    )


# Kept so callers that need the default text can import a constant, as before.
BRANCH_SESSION_PREAMBLE_TEXT = build_branch_session_preamble_text()
FIRST_BRANCH_SESSION_PREAMBLE_TEXT = build_first_branch_session_preamble_text()
