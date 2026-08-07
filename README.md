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

Working. The loop has run unattended across a real multi-turn task: the user
asked for a browser game, and successive branches built it, reviewed their own
work, created a public GitHub repository and pushed to it — each branch forked
fresh from the base, carrying only the accumulated handoffs.

Earlier, the core claim was isolated by hand: a codeword established in one
branch was known by the next, which was forked from the base and never told it
directly.

Two things about that run are worth knowing before repeating it. It was stopped
manually rather than finishing on its own — the loop keeps rotating for as long
as branches keep emitting handoff packages, and nothing bounds that. And the
run cost real money; see [Cost](#cost).

503 tests pass against fakes and argv assertions. The opt-in live suite
(`CONTEXT_HANDOFF_RUN_LIVE_CLAUDE_TESTS=1`) has not been run.

Design notes: [1. claude-cli-context-handoff-poc.md](1.%20claude-cli-context-handoff-poc.md)
and [2. manual-context-persistence.md](2.%20manual-context-persistence.md).
Deferred observations are in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).

A plan for rebuilding the same pattern on the Pi harness against a local model —
where the constraint is a hard context ceiling rather than token cost — is in
[3. pi-harness-context-handoff-plan.md](3.%20pi-harness-context-handoff-plan.md).

## Cost

This design trades money for a small base session, and the trade is not
subtle — worth understanding before running it on anything long.

Measured from the `message.usage` records of one real run (12 sessions: 1 base,
11 branches; 90 billed calls, de-duplicated by message id, since a forked
transcript carries copies of the parent's usage records and naive summing
double-counts):

| | tokens |
| --- | ---: |
| cache write | 1,333,771 |
| cache read | 4,264,005 |
| output | 71,352 |
| fresh input | 171 |

At the Claude Opus 5 rates that run used — $5/$25 per Mtok, cache write 1.25×
input, cache read 0.1× — that is **≈ $12.25**, of which **68% is cache writes**.
At a 1-hour cache TTL (write 2× instead of 1.25×) the same run is ≈ $17.25.

**Where the overhead comes from.** Every rotation forks a *new* session, and a
new session cannot read the previous branch's cache. The inherited base context
is therefore written cold at 1.25–2× rather than read at 0.1× — the same tokens
at 12.5–20× the price. It shows up as cache writes being 31% of cache reads
here, a fraction that would be far smaller in one long session where the prefix
is written once and read on every subsequent turn.

**How much is overhead.** If every written token had instead been a cache read —
the best case for a single ordinary session — the run would have cost ≈ $4.58.
So this approach cost up to **~2.7×** a single-session equivalent. That is an
upper bound, not an estimate: some of those writes are unavoidable, because new
content must be written to cache once regardless of how sessions are
structured, and the usage records don't separate "genuinely new" from
"re-written because we forked".

The base session itself is cheap and stays that way — 24 fresh input tokens,
215K cache write, 5,310 output across the whole run. The cost is entirely in
branches re-establishing context, which is the tradeoff the design makes on
purpose.

## Which sessions count as the user's

The orchestrator drives sessions of its own — the base session, and the
short-lived call that delivers a handoff to it. Both end turns and submit
prompts, so both reach the hooks. A branch's own seeding turn does too: the seed
rides on the launch command, so the branch answers it as its first visible turn.

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

Each hook is the only writer of a file the loop depends on, so losing either is
an error state rather than a degraded run. Without the `Stop` hook nothing writes
`context-to-keep.json`, so the loop's poll never sees a handoff and it idles
indefinitely — no rotation, no error. Without the `UserPromptSubmit` hook it does
rotate, but every handoff reaches the base session with none of the prompts that
produced it. There is no flag that starts either run: the hooks are installed, or
the run stops.

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

Once a session has done work worth saving, the agent emits a fenced block. The
Stop hook finds it and writes it to
`.claude/manual-context-persistence/context-to-keep.json`:

````markdown
```context-to-keep
{
  "context_to_keep_version": 1,
  "context_to_keep": ["A fact the next turn needs."],
  "next_action": "Ask the user whether the naming should be made consistent."
}
```
````

Emission is triggered by having done work worth saving, not by a turn ending: a
question or an acknowledgement would otherwise cost a full rotation to carry
nothing.

`next_action` is the next action to take — work, research, asking the user a
question, reporting results. It is what makes the loop continue rather than
restart: the session opened after a rotation is seeded with the task the previous
one named, then the same output contract. It is passed from one working session to
the next and is never sent to the base session, which has no user turn to act on.

The first session of a run is the only one with no task to inherit, so it is told
to ask the user for instructions instead. Every seed opens with what to do, then
how to report it.

The last valid block in a reply wins, so an agent may quote the format before
emitting the real thing. A malformed package is ignored rather than raising —
no hook may be the reason a session breaks.

## Files the system uses

Everything this system keeps lives in its own folder, named for this
repository, so nothing it writes can collide with a file the harness or another
tool puts in `.claude`. Only `settings.local.json` sits outside it, because the
harness reads hook registrations from there.

```
.claude/settings.local.json                        hook registrations (harness reads this)
.claude/manual-context-persistence/
  settings.json                                    this system's settings
  context-to-keep.json                             pending handoff
  context-to-keep-history/context-to-keep-<stamp>.json  consumed handoffs
  user-prompt-log.json                             verbatim prompts
  user-facing-sessions.json                        which sessions the user typed in
  last-stop-hook-outcome.json                      what the Stop hook decided last
```

Prompts are logged byte for byte, with up to 2000 characters of the preceding
agent output so a reply like "yes" is still meaningful later. A message typed
while the agent is working never fires the prompt hook, so it is recovered from
the transcript on the next submission — scoped to the gap since the previous
prompt, so nothing is logged twice and a forked transcript's inherited history
is never rescanned.

## Settings

`.claude/manual-context-persistence/settings.json` is created with defaults on
first run:

| Setting | Default | Meaning |
|---|---|---|
| `require_git_commit` | `false` | Ask each session to commit its work before emitting the block |
| `git_repository_url` | `null` | The repository's remote, when it has one |
| `git_repository_is_local_only` | `false` | Stated rather than inferred, so "no remote" and "not filled in yet" stay distinct |

Every default is safe for a project with no repository at all, which is why
`require_git_commit` is off: a commit instruction in a directory with no
repository is unfollowable.

`--require-git-commit` / `--no-require-git-commit` override the file for one run.

## Hooks

| Event | Script |
|---|---|
| `Stop` | `context_to_keep_stop_hook.py` |
| `UserPromptSubmit` | `user_prompt_submit_capture_hook.py` |

The harness runs these, so a project's `.claude/settings.local.json` has to name
an absolute path to each one. That path is **not** into this repository — the
scripts are deployed to `~/.claude/manual-context-persistence/hooks/` and
referenced there, so a project's settings file keeps working when this repository
is moved or renamed. Startup redeploys both scripts on every run, overwriting
what is there, so the deployed copies are always the ones this repository
currently holds — and a deleted or hand-edited copy needs no separate handling.

Startup sets this up, and the difference between the two cases is whose file it
is. No `settings.local.json` at all means nothing of the operator's exists yet,
so it is created without asking. One that is already there but does not register
these hooks is theirs, so startup asks whether to install them or abort, and
installing merges — other keys and other tools' hooks on the same event are left
as they were. Declining stops the run; there is no way to start without them.

Both hooks read a JSON payload on stdin and print a JSON response.
