# Open questions and deferred issues

Things worth a decision that I did not decide unilaterally, and things noticed
but deliberately not acted on. Nothing here is blocking.

## Questions for review

### 1. The handoff package schema is my invention
Spec 2 line 37 asks only for "a custom json package containing the context the
agent is returning that it decides is all that is needed going forward to
understand what was done in the last turn". It does not name any fields.

I chose `context_to_keep_version`, `summary_of_work_completed_this_turn`,
`context_to_carry_forward`. That reading fits the sentence, but the field names
and the decision to split summary from carried context are mine.

### 2. Workspace trust blocks unattended startup
A branch launched in a fresh project directory stops on Claude Code's
"Is this a project you created or one you trust?" prompt and waits. Every
driven run so far has needed a human (or me) to answer `1`.

The spec does not mention it. Options if it matters: document it as a
precondition, pre-trust the directory during startup, or have the orchestrator
detect and answer it. I have not researched whether a supported non-interactive
way to pre-trust exists.

### 3. Polling versus watching
Spec 2 line 10 says the app "actively watches the cwd/.claude/context-to-keep.json
file for changes". The loop polls on an interval instead. Behaviourally
equivalent for this purpose and far simpler to test, but it is not literally
what the wording asks for.

## Deferred issues

### A. The base session's own turns reach the Stop hook
The handoff delivery is a `claude -p --resume` against the base session, which
ends a turn and therefore fires Stop. Observed in a driven run: the hook
inspected the base session's acknowledgement for a handoff package.

Being fixed now by gating the Stop hook on the user-facing session registry,
the same gate the prompt hook already uses.

### B. Ghost text appears in the input box between turns
Driven runs sometimes show text in the pane's input box that was never typed —
plausible follow-up suggestions. It has not caused an observable problem and
the log has never contained it. Noted only so it is not mistaken later for
stray input from the orchestrator.
