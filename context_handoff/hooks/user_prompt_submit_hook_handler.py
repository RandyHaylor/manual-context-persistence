"""UserPromptSubmit hook: log what the user typed, verbatim, before the agent acts.

Capturing at submission time is what makes the log trustworthy. By the time a
turn ends, the only record of the user's words is whatever the agent chose to
repeat, and the entire point of the handoff is that it carries the user's own
words rather than a paraphrase.

The agent output preceding the prompt is captured alongside it, so a reply of
"yes" remains a complete requirement when it is read back later.
"""
from __future__ import annotations

from typing import Any

from context_handoff.adapters.claude_cli.claude_cli_transcript_reader import (
    find_user_messages_sent_while_agent_was_working,
    read_agent_output_since_last_user_prompt,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)
from context_handoff.user_prompt_log.user_prompt_log_store import (
    MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS,
    UserPromptLogStore,
)

EMPTY_HOOK_RESPONSE: dict[str, Any] = {}


def handle_user_prompt_submit_payload(hook_payload: dict[str, Any]) -> dict[str, Any]:
    """Append the submitted prompt, with its preceding context, to the log."""
    try:
        project_directory = hook_payload.get("cwd")
        session_identifier = hook_payload.get("session_id")
        user_prompt_text = hook_payload.get("prompt")
        if not project_directory or not session_identifier:
            return EMPTY_HOOK_RESPONSE
        if not isinstance(user_prompt_text, str) or not user_prompt_text.strip():
            return EMPTY_HOOK_RESPONSE

        # The gate. This hook also fires for the sessions the orchestrator
        # drives itself — the base session, and the non-interactive calls that
        # seed a branch or deliver a handoff — and logging those would record
        # the orchestrator's own words as the user's.
        #
        # Deliberately not the same question the Stop hook asks. A branch is
        # user-facing from the moment it exists, because its replies are
        # handoffs; but while the orchestrator is still seeding it, the text
        # arriving is the orchestrator's own.
        if not UserFacingSessionRegistry(
            project_directory
        ).is_session_accepting_user_prompts(session_identifier):
            return EMPTY_HOOK_RESPONSE

        transcript_path = hook_payload.get("transcript_path")
        pre_submission_content = ""
        user_prompt_log_store = UserPromptLogStore(project_directory)

        if transcript_path:
            pre_submission_content = read_agent_output_since_last_user_prompt(
                transcript_path, MAXIMUM_PRE_SUBMISSION_CONTENT_CHARACTERS
            )
            # Messages typed while the agent was working never fired this hook,
            # so this submission is the first chance to record them. They are
            # logged first, preserving the order the user sent them in.
            for recovered_message_text in find_user_messages_sent_while_agent_was_working(
                transcript_path, user_prompt_text
            ):
                user_prompt_log_store.append_user_prompt_entry(
                    session_identifier=session_identifier,
                    user_prompt_text=recovered_message_text,
                    # No pre-submission context: a mid-turn message interrupts
                    # the agent's work rather than answering a question, and the
                    # surrounding output is already carried by the next entry.
                    pre_submission_content="",
                )

        user_prompt_log_store.append_user_prompt_entry(
            session_identifier=session_identifier,
            # Not stripped: the log's value is that it is byte-for-byte.
            user_prompt_text=user_prompt_text,
            pre_submission_content=pre_submission_content,
        )
        return EMPTY_HOOK_RESPONSE
    except Exception:
        # Deliberately broad: no failure in this hook may block a user prompt.
        return EMPTY_HOOK_RESPONSE
