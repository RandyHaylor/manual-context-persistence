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

## Resolved

- **Package schema field names** — mine to choose.
- **Polling rather than watching the context-to-keep file** — accepted.
- **Workspace trust** — scrubbed. It was never in either spec. It surfaced only
  because every driven test used a brand-new scratch directory, which is an
  artifact of the test setup and not something a real project hits. The
  interface method, adapter module, startup warning and their tests were all
  removed.
