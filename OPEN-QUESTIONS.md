# Open questions and deferred issues

Things noticed but deliberately not acted on. Nothing here is blocking.

## Defects found by the twenty-turn endurance run

### 0. The rotation status line can be concatenated into a user prompt
Found in the prompt log after twenty turns of driving:

    "...the manifest are all consistent with each other.echo 'updating base session...'"

The orchestrator types `echo 'updating base session...'` into the shared window
during rotation. If the user has typed into the branch's input box and not yet
submitted, the status text lands in the same box and the two are submitted
together — so a machine-generated string ends up inside a verbatim user prompt
and is then forwarded to the base session as something the user said.

This is the same class as the earlier capture-pollution defects, and the
occurrence rate is low: one entry in nineteen, only when a prompt is typed
during the rotation window.

The tension is that spec 2 line 14 asks specifically for an echo. Options:

  a. Keep the echo, but clear the input line first — discards whatever the user
     had typed, which trades pollution for lost input. Worse.
  b. Send the status somewhere that is not the input box, e.g. the terminal's
     own status line. Satisfies the intent (the user sees "updating base
     session...") without ever touching what they are typing.
  c. Only echo once the interrupted session has actually exited, so the input
     box belongs to a shell rather than an interactive agent.

I have not chosen, because (b) departs from the literal wording of the spec and
that is your call. My preference is (b), with (c) as a smaller change that
narrows but does not close the window.

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
