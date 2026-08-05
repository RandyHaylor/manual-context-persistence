# Open questions and deferred issues

Things noticed but deliberately not acted on. Nothing here is blocking.

## Deferred issues

### A. Ghost text appears in the input box between turns
Driven runs sometimes show text in the pane's input box that was never typed —
plausible follow-up suggestions from the CLI. It has not caused an observable
problem and the prompt log has never contained it. Noted only so it is not
mistaken later for stray input from the orchestrator.

### B. The mid-turn look-behind is belt-and-braces on current versions
The spec points at the source-of-truth implementation for capturing messages
typed while the agent is working, and that implementation is explicit that such
a message "does NOT fire its own UserPromptSubmit hook".

A standalone spike on CLI 2.1.220 found the opposite: the queued message does
fire its own UserPromptSubmit when submitted, with the text in the `prompt`
field. The platform appears to have changed since that reference was written.

Both paths are kept. A test pins down that a message appearing both as a queued
attachment and as the genuine prompt it became is recovered exactly once.

### C. The specs' file paths and hook handling are now behind the code

Two deliberate departures, both decided by the user after the conflict with the
specs was raised. Recorded here so the specs and the code are not left silently
disagreeing — spec 1 should be updated, or these reverted.

**State file locations.** Spec 1 lines 129-132 name `.claude/context-to-keep.json`,
`.claude/context-to-keep-history/`, and `.claude/user-prompt-log.json` directly
under `.claude`. They now live in `.claude/manual-context-persistence/`, with
this system's own `settings.json` alongside them. `.claude/settings.local.json`
stays where it is, because the harness reads it.

**Hook installation.** Spec 1 lines 46-48 say *verify* the hooks, and the build
did only that: it refused to start and left registration to the operator by
hand. Startup now creates `settings.local.json` when it is absent, and asks
install-or-abort when the file exists without these hooks.

## Resolved

- **Interrupting a session that is still working** — not a real case, and not to
  be treated as one again.

  Measured on CLI 2.1.220, driving a real tmux pane: `Ctrl+C` twice exits a
  session that is idle at its prompt, but a session that is mid-turn only has
  its turn cancelled and stays alive, needing a second pair. That measurement is
  true, and it is also irrelevant to the turn loop, because rotation cannot
  reach a mid-turn session: a rotation happens only when a context-to-keep is
  pending, that file is written only by the Stop hook, and the Stop hook fires
  only once the agent has finished replying.

  A day was spent designing escalating interrupts and retry loops for this, on
  the strength of a spike that interrupted as soon as the branch's *transcript
  file appeared* — which happens mid-turn. That trigger is not the one the app
  uses. The busy session was manufactured by the spike.

  Two things follow. First, the spec's "send `Ctrl+C` twice" (spec 1 line 75) is
  correct as written and needs no change. Second, a pane's state is not a
  substitute for the Stop signal: `pane_current_command` distinguishes a running
  session from a shell, but an agent generating a reply and an agent waiting for
  input are the same process, so it cannot tell a turn has ended.

  Still genuinely possible, and much narrower: the base session is interrupted
  after only its *transcript* is observed, not after Stop, so that one path can
  hit a working session; and a user who submits another prompt between Stop
  firing and the rotation leaves the branch busy. Neither justifies escalation
  in the general path.

- **Package schema field names** — mine to choose.
- **Polling rather than watching the context-to-keep file** — accepted.
- **Workspace trust** — scrubbed. It was never in either spec. It surfaced only
  because every driven test used a brand-new scratch directory, which is an
  artifact of the test setup and not something a real project hits. The
  interface method, adapter module, startup warning and their tests were all
  removed.
