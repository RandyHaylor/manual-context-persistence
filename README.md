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

The full loop has been driven end to end by hand against a real Claude CLI and
a real tmux window: a codeword established in one branch was known by the next
branch, which was forked fresh from the base and never told it directly.

Design notes: [1. claude-cli-context-handoff-poc.md](1.%20claude-cli-context-handoff-poc.md)
and [2. manual-context-persistence.md](2.%20manual-context-persistence.md).
Decisions still open for review are in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).

One precondition is not automated: a branch launched in a project directory
Claude Code has not seen before stops on its workspace-trust prompt and waits
for an answer.

## Which sessions count as the user's

The orchestrator drives sessions of its own — the base session, and the
short-lived calls that seed a branch or deliver a handoff. All of them end
turns and submit prompts, so all of them reach the hooks.

Branches are registered in `.claude/context-handoff-user-facing-sessions.json`,
and both hooks ignore anything unregistered. Without that gate the verbatim log
fills with the orchestrator's own words attributed to the user, and the base
session's acknowledgements get captured as though they were a branch's work.
Both were observed before the gate existed.

Registration happens *after* a branch is seeded, so the briefing turn is
excluded structurally rather than by asking the agent not to emit a package.

## When a turn produces no handoff

Every Stop hook run writes what it decided to
`.claude/context-handoff-last-stop-hook-outcome.json`: the outcome, the reason,
and how much agent text it was given. Read it first when a turn does not
rotate — it distinguishes "the agent emitted no package" from "the package was
unusable" from "that session is not one the user works in".

## Running it

```bash
./run_context_handoff.py                      # asks: new base session, or resume?
./run_context_handoff.py --new-base           # skip the question, create one
./run_context_handoff.py --resume-base <id>   # skip the question, resume one
```

It checks that the CLI answers and that both hooks are registered, asks whether
to create or resume a base session (the flags skip the question so it can run
unattended), opens the shared tmux window with the first branch inside it, then
watches for completed turns and rotates. `Ctrl-C` stops the loop and leaves the
window open, since the user may still be mid-conversation in it.

Starting without the capture hooks looks fine and captures nothing, so the
preflight refuses rather than warns. `--skip-hook-preflight` overrides it.

## Layout

```
context_handoff/
  interfaces/          HarnessInterface, UserInterfaceControlInterface
  adapters/claude_cli/ transcript locator, stream parser, process launcher, adapter
  adapters/tmux/       command runner, user-interface control adapter
  context_to_keep/     handoff package, file store, history rotation
  user_prompt_log/     verbatim prompt log
  orchestration/       handoff message composer, turn rotation orchestrator
  startup/             hook preflight, base session resolver
  hooks/               Stop and UserPromptSubmit handlers
hooks/                 executable hook entry points
run_context_handoff.py the app; the only place real adapters meet the core
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

Prompts are logged byte for byte, with up to 2000 characters of the preceding
agent output so a reply like "yes" is still meaningful later. A message typed
while the agent is working never fires the prompt hook, so it is recovered from
the transcript on the next submission — scoped to the gap since the previous
prompt, so nothing is logged twice and a forked transcript's inherited history
is never rescanned.

## Hooks

Register in a project's `.claude/settings.local.json`:

| Event | Script |
|---|---|
| `Stop` | `hooks/context_to_keep_stop_hook.py` |
| `UserPromptSubmit` | `hooks/user_prompt_submit_capture_hook.py` |

Both read a JSON payload on stdin and print a JSON response.
