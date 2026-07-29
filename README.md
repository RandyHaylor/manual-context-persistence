# manual-context-persistence

A context-handoff proof of concept: one persistent **base session** kept compact
by accumulated handoffs, and short-lived **branch sessions** the user actually
talks to.

Each turn, the user works in a branch. When the turn ends, the agent's
context-to-keep package and the user's verbatim prompts are submitted to the
base session, which acknowledges and does nothing else. The next branch forks
the updated base. The base therefore accumulates meaning without accumulating
transcript.

## Status

The full loop runs against a real Claude CLI and a real tmux window. See
[1. claude-cli-context-handoff-poc.md](1.%20claude-cli-context-handoff-poc.md)
for the original design notes.

## Layout

```
context_handoff/
  interfaces/          HarnessInterface, UserInterfaceControlInterface
  adapters/claude_cli/ transcript locator, stream parser, process launcher, adapter
  adapters/tmux/       command runner, user-interface control adapter
  context_to_keep/     handoff package, file store, history rotation
  user_prompt_log/     verbatim prompt log
  orchestration/       handoff message composer, turn rotation orchestrator
  hooks/               Stop and UserPromptSubmit handlers
hooks/                 executable hook entry points
tests/                 unit, contract, integration, and opt-in live tests
```

The core depends only on `interfaces/`. The orchestrator's entire test suite
runs with no Claude CLI and no tmux, which is the check that the boundaries
actually hold — enforced by tests, not by convention.

## Running the tests

```bash
python3 -m pytest tests -q
```

That runs everything except the live tests. Real-tmux integration tests are
included and skip automatically when tmux is absent.

Live tests make billable Claude calls and are opt-in:

```bash
CONTEXT_HANDOFF_RUN_LIVE_CLAUDE_TESTS=1 python3 -m pytest tests -q
```

They assume the CLI is installed and already logged in through its own local
OAuth flow. Nothing in this project prompts for, stores, or manages credentials.

## The handoff package

At the end of a turn the agent emits a fenced block. The Stop hook finds it and
writes it to `.claude/context-to-keep.json`:

````markdown
```context-to-keep
{
  "context_to_keep_version": 1,
  "summary_of_work_completed_this_turn": "What this turn accomplished.",
  "context_to_carry_forward": ["A fact the next turn needs."]
}
```
````

The last valid block in a reply wins, so an agent may quote the format before
emitting the real thing. A malformed package is ignored rather than raising —
no hook may be the reason a session breaks.

## Files the system uses

```
.claude/context-to-keep.json                                  pending handoff
.claude/context-to-keep-history/context-to-keep-<stamp>.json  consumed handoffs
.claude/user-prompt-log.json                                  verbatim prompts
```

## Hooks

Register in a project's `.claude/settings.local.json`:

| Event | Script |
|---|---|
| `Stop` | `hooks/context_to_keep_stop_hook.py` |
| `UserPromptSubmit` | `hooks/user_prompt_submit_capture_hook.py` |

Both read a JSON payload on stdin and print a JSON response.
