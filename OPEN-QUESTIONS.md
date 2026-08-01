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
driven run so far has needed someone to answer `1`.

This is worse than a cosmetic pause. The documentation states that project
settings are honoured "only after you accept the workspace trust dialog", and
this system's capture hooks live in project settings — so before approval the
loop runs and records nothing.

Researched: there is **no documented way to pre-trust a directory**, no
supported setting and no CLI flag. The decision is stored per project in
`~/.claude.json` under `hasTrustDialogAccepted`, which is undocumented.

What was done: startup reads that key and warns when it is definitely false,
explaining that the branch will wait and nothing is captured until approval is
given. Unknown is treated as unknown, so a directory the CLI has never opened
produces no warning.

What was NOT done, deliberately: writing that key to trust a directory
automatically. That is an unsupported edit to internal state and a safety
decision that belongs to whoever runs this, not to the tool. Say the word if
you want it and I will add it behind an explicit opt-in flag.

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

### B. The mid-turn look-behind may now be redundant
The spec points at the source-of-truth implementation for capturing mid-turn
messages, and that implementation is explicit that "a message sent while the
agent is working does NOT fire its own UserPromptSubmit hook".

A standalone spike on CLI 2.1.220 found the opposite: typing during a turn and
letting the queued message be submitted **does** fire its own UserPromptSubmit,
with the message in the `prompt` field. The platform appears to have changed
since that reference was written.

The look-behind is kept — the spec asks for it, and older CLI versions still
need it — but it is now belt-and-braces rather than the only path. A test pins
down that a message appearing both as a queued attachment and as the genuine
prompt it became is recovered only once.

Worth deciding: keep both paths, or drop the look-behind and depend on the
platform. I have not dropped it, because that would be a spec deviation based
on one version's behaviour.

### C. Ghost text appears in the input box between turns
Driven runs sometimes show text in the pane's input box that was never typed —
plausible follow-up suggestions. It has not caused an observable problem and
the log has never contained it. Noted only so it is not mistaken later for
stray input from the orchestrator.
