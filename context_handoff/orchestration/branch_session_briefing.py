"""What a branch session is told when it starts.

Two jobs, both discovered by driving the system by hand rather than by reading
it.

First, the handoff protocol. The Stop hook waits for a package the agent has no
other way to know about, so before this existed the loop could never turn — the
branch worked normally and simply never emitted anything.

Second, a correction. A branch forks the base session, so it inherits the base
preamble telling it to acknowledge and never act. That is right for the base
and wrong for the branch, which is the session the user actually works in.

The example below is exercised by the same extractor the Stop hook uses, so
these instructions cannot quietly drift away from what the parser accepts.
"""
from __future__ import annotations

from context_handoff.context_to_keep.context_to_keep_package import (
    CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG,
    CONTEXT_TO_KEEP_PACKAGE_VERSION,
)


def build_branch_session_briefing_text() -> str:
    return (
        "[context-handoff branch briefing]\n\n"
        "You are a branch session. The user works with you directly and you do "
        "the work they ask for — ignore any earlier instruction to only "
        "acknowledge and not act, which belongs to the session you were forked "
        "from.\n\n"
        "This session is short-lived. At the end of every turn, finish your "
        "normal reply and then emit one fenced block so the next session "
        "inherits what matters:\n\n"
        f"```{CONTEXT_TO_KEEP_FENCE_LANGUAGE_TAG}\n"
        "{\n"
        f'  "context_to_keep_version": {CONTEXT_TO_KEEP_PACKAGE_VERSION},\n'
        '  "summary_of_work_completed_this_turn": "What this turn actually did.",\n'
        '  "context_to_carry_forward": [\n'
        '    "A fact the next session needs and could not work out on its own."\n'
        "  ]\n"
        "}\n"
        "```\n\n"
        "Write it for a session that cannot see this conversation. Carry "
        "decisions, constraints and surprises; leave out anything recoverable "
        "from the files themselves. An empty list is a fine answer when the "
        "turn produced nothing worth carrying.\n\n"
        "The summary describes the turn that just finished — what the user "
        "asked and what you actually did. Never reuse an earlier summary and "
        "never copy the example above; a stale summary is worse than none, "
        "because the next session will act on it as if it were true.\n\n"
        "This briefing is not a turn. Do not emit a package for it. Reply with "
        "one short sentence acknowledging it and nothing else."
    )
