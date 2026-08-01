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

- **Package schema field names** — mine to choose.
- **Polling rather than watching the context-to-keep file** — accepted.
- **Workspace trust** — scrubbed. It was never in either spec. It surfaced only
  because every driven test used a brand-new scratch directory, which is an
  artifact of the test setup and not something a real project hits. The
  interface method, adapter module, startup warning and their tests were all
  removed.
