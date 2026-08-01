"""Tests for the turn loop, driven entirely by fakes.

No Claude CLI and no tmux appear anywhere in this file. That is the test the
adapter boundaries exist to make possible: if the orchestrator can be fully
exercised without either technology, neither has leaked into the core.
"""
from __future__ import annotations

import pytest

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import ContextToKeepPackage
from context_handoff.orchestration.handoff_message_composer import (
    ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT,
)
from context_handoff.orchestration.turn_rotation_orchestrator import (
    INTERRUPT_REPEAT_COUNT_FOR_SESSION_SWAP,
    NoPendingHandoffError,
    SHARED_WINDOW_STATUS_TEXT_WHILE_UPDATING_BASE,
    TurnRotationOrchestrator,
)
from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls
from tests.fakes.fake_user_interface_control_recording_all_calls import (
    FakeUserInterfaceControlRecordingAllCalls,
)

BASE_SESSION_IDENTIFIER = "base-session"
WINDOW_IDENTIFIER = "context-handoff-window"


class OrchestratorTestHarness:
    """Bundles the orchestrator with the fakes and stores it was built from."""

    def __init__(self, project_directory: str, harness_should_time_out: bool = False):
        self.fake_harness = FakeHarnessRecordingAllCalls(
            active_session_identifier_by_working_directory={
                project_directory: BASE_SESSION_IDENTIFIER
            },
            should_time_out_on_submission=harness_should_time_out,
        )
        self.fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()
        self.context_to_keep_store = ContextToKeepFileStore(
            project_directory=project_directory,
            generate_timestamp_text=lambda: "20260728T120000Z",
        )
        self.user_prompt_log_store = UserPromptLogStore(project_directory=project_directory)
        self.orchestrator = TurnRotationOrchestrator(
            harness=self.fake_harness,
            user_interface_control=self.fake_user_interface_control,
            context_to_keep_store=self.context_to_keep_store,
            user_prompt_log_store=self.user_prompt_log_store,
            project_directory=project_directory,
            base_session_identifier=BASE_SESSION_IDENTIFIER,
            shared_window_identifier=WINDOW_IDENTIFIER,
        )

    def stage_completed_turn(
        self,
        branch_session_identifier: str,
        user_prompt_text: str = "do the thing",
        next_action_text: str = "Ask the user which pad naming should win.",
    ) -> None:
        """Simulate what a finished branch turn leaves behind on disk."""
        self.user_prompt_log_store.append_user_prompt_entry(
            branch_session_identifier, user_prompt_text
        )
        self.context_to_keep_store.write_pending_context_to_keep_package(
            ContextToKeepPackage(
                next_action=next_action_text,
                context_to_keep=["A fact worth keeping."],
            )
        )

    def window_event_kinds(self) -> list[str]:
        return [
            event[0]
            for event in self.fake_user_interface_control.event_log_by_window_identifier[
                WINDOW_IDENTIFIER
            ]
        ]

    def command_lines_run_in_window(self) -> list[tuple]:
        return [
            event[1]
            for event in self.fake_user_interface_control.event_log_by_window_identifier[
                WINDOW_IDENTIFIER
            ]
            if event[0] == "run_command_line_in_shared_window"
        ]


@pytest.fixture
def test_harness(tmp_path) -> OrchestratorTestHarness:
    return OrchestratorTestHarness(str(tmp_path))


def test_starting_opens_the_window_and_runs_a_branch_in_it(test_harness) -> None:
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()

    assert test_harness.fake_user_interface_control.is_shared_window_alive(
        WINDOW_IDENTIFIER
    )
    assert test_harness.fake_harness.created_branch_parent_identifiers == [
        BASE_SESSION_IDENTIFIER
    ]
    assert "run_command_line_in_shared_window" in test_harness.window_event_kinds()
    assert branch_session_identifier


def test_the_window_runs_the_fork_itself_and_never_a_headless_branch(
    test_harness,
) -> None:
    """The regression this whole seam exists for.

    The branch the user works in must be brought into being by the command
    running in their window. An earlier shape forked it non-interactively first
    and then opened a second command on the finished session, so every window
    after the first was interrupted about a second after it appeared — the
    branch had already spent its turn where nobody could see it.
    """
    test_harness.orchestrator.start_first_branch_session()

    command_lines = test_harness.command_lines_run_in_window()
    assert len(command_lines) == 1, "the branch must be opened exactly once"
    launched_argv = command_lines[0]
    assert "--fork-session" in launched_argv, (
        "the window's own command must be what forks the branch"
    )
    assert "-p" not in launched_argv
    assert "--print" not in launched_argv


def test_every_rotation_opens_a_forking_command_not_only_the_first(
    test_harness,
) -> None:
    """The first branch was never the broken one; the ones after it were."""
    first_branch = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(first_branch)
    test_harness.orchestrator.rotate_to_next_branch_session()

    command_lines = test_harness.command_lines_run_in_window()
    assert len(command_lines) == 2
    for launched_argv in command_lines:
        assert "--fork-session" in launched_argv
        assert "-p" not in launched_argv


def test_the_branch_is_not_on_disk_before_its_window_command_runs(
    test_harness,
) -> None:
    """Allocation must not create the session; the visible command does."""
    branch_session_identifier = (
        test_harness.fake_harness.allocate_branch_session_identifier()
    )

    assert (
        test_harness.fake_harness.wait_until_session_transcript_is_durable(
            session_identifier=branch_session_identifier,
            working_directory="/anywhere",
            timeout_seconds=0.0,
        )
        is False
    )


def test_a_branch_that_never_becomes_durable_still_leaves_the_window_open(
    test_harness,
) -> None:
    """A slow branch is a reporting problem, not a reason to tear down."""
    test_harness.fake_harness.durability_wait_result = False

    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()

    assert branch_session_identifier
    assert test_harness.fake_user_interface_control.is_shared_window_alive(
        WINDOW_IDENTIFIER
    )


class FakeHarnessCheckingTheRegistryWhileItSeeds(FakeHarnessRecordingAllCalls):
    """Answers, at seed time, the two questions the hooks will ask.

    The seeded session replies to the seed, and with a task in that seed the
    reply is the first turn of real work. So what the registry says *during* the
    seeding call is what decides whether that handoff is kept — checking after
    the call returns cannot see the problem at all.
    """

    def __init__(self, project_directory: str, **keyword_arguments):
        super().__init__(**keyword_arguments)
        self._project_directory = project_directory
        self.was_user_facing_while_seeding: list = []
        self.was_accepting_user_prompts_while_seeding: list = []

    def wait_until_session_transcript_is_durable(
        self,
        session_identifier: str,
        working_directory: str,
        timeout_seconds: float,
    ) -> bool:
        """The durability wait IS the seeding window now.

        The branch answers its seed inside the user's window while this call
        watches for the transcript, so this is the moment the hooks' questions
        get asked — after it returns, seeding is over.
        """
        registry = UserFacingSessionRegistry(self._project_directory)
        self.was_user_facing_while_seeding.append(
            registry.is_user_facing_session(session_identifier)
        )
        self.was_accepting_user_prompts_while_seeding.append(
            registry.is_session_accepting_user_prompts(session_identifier)
        )
        return super().wait_until_session_transcript_is_durable(
            session_identifier=session_identifier,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
        )


def test_a_session_is_capturable_while_it_is_still_being_seeded(tmp_path) -> None:
    """The handoff from the seed turn must not be thrown away.

    Found in a live run: the seeded session did its task, emitted a valid block,
    and the Stop hook discarded it as "not a user-facing session" — because the
    session was written down only after the seeding call returned.
    """
    project_directory = str(tmp_path)
    checking_harness = FakeHarnessCheckingTheRegistryWhileItSeeds(
        project_directory,
        active_session_identifier_by_working_directory={
            project_directory: BASE_SESSION_IDENTIFIER
        },
    )
    orchestrator = TurnRotationOrchestrator(
        harness=checking_harness,
        user_interface_control=FakeUserInterfaceControlRecordingAllCalls(),
        context_to_keep_store=ContextToKeepFileStore(project_directory),
        user_prompt_log_store=UserPromptLogStore(project_directory),
        project_directory=project_directory,
        base_session_identifier=BASE_SESSION_IDENTIFIER,
        shared_window_identifier=WINDOW_IDENTIFIER,
    )

    orchestrator.start_first_branch_session()

    assert checking_harness.was_user_facing_while_seeding == [True]


def test_the_seed_itself_is_not_treated_as_something_the_user_typed(tmp_path) -> None:
    """The other half: the seed travels the same path a typed prompt does."""
    project_directory = str(tmp_path)
    checking_harness = FakeHarnessCheckingTheRegistryWhileItSeeds(
        project_directory,
        active_session_identifier_by_working_directory={
            project_directory: BASE_SESSION_IDENTIFIER
        },
    )
    orchestrator = TurnRotationOrchestrator(
        harness=checking_harness,
        user_interface_control=FakeUserInterfaceControlRecordingAllCalls(),
        context_to_keep_store=ContextToKeepFileStore(project_directory),
        user_prompt_log_store=UserPromptLogStore(project_directory),
        project_directory=project_directory,
        base_session_identifier=BASE_SESSION_IDENTIFIER,
        shared_window_identifier=WINDOW_IDENTIFIER,
    )

    branch_session_identifier = orchestrator.start_first_branch_session()

    assert checking_harness.was_accepting_user_prompts_while_seeding == [False]
    # And once the orchestrator has finished talking, the user's turn begins.
    assert UserFacingSessionRegistry(
        project_directory
    ).is_session_accepting_user_prompts(branch_session_identifier)


def test_only_the_first_session_is_seeded_with_the_request_for_instructions(
    test_harness,
) -> None:
    """Found in a real run, so it is pinned at the level that decides it.

    The first session opens before the user has said anything, so it is told to
    ask. Every session after a rotation exists because the user did speak and
    work was done, so the same sentence there would contradict the situation it
    is in — and would spend a turn asking a question nobody is waiting on.
    """
    from context_handoff.orchestration.branch_session_preamble import (
        REQUEST_INSTRUCTIONS_SENTENCE,
    )

    first_branch_session_identifier = (
        test_harness.orchestrator.start_first_branch_session()
    )
    test_harness.stage_completed_turn(first_branch_session_identifier)
    rotation_outcome = test_harness.orchestrator.rotate_to_next_branch_session()

    seeds_by_session = test_harness.fake_harness.submitted_texts_by_session_identifier
    assert REQUEST_INSTRUCTIONS_SENTENCE in (
        seeds_by_session[first_branch_session_identifier][0]
    )
    assert REQUEST_INSTRUCTIONS_SENTENCE not in (
        seeds_by_session[rotation_outcome.new_branch_session_identifier][0]
    )


def test_the_next_action_named_by_one_session_seeds_the_session_that_follows(
    test_harness,
) -> None:
    """The whole point of the field, checked where it actually has to survive.

    The package is retired into history before the next session is launched, so
    this proves the task is still in hand at launch rather than read back from a
    file that has already moved.
    """
    distinctive_next_action_text = "Report the WOMBAT-8842 findings to the user."
    first_branch_session_identifier = (
        test_harness.orchestrator.start_first_branch_session()
    )
    test_harness.stage_completed_turn(
        first_branch_session_identifier, next_action_text=distinctive_next_action_text
    )

    rotation_outcome = test_harness.orchestrator.rotate_to_next_branch_session()

    seed_given_to_the_new_session = (
        test_harness.fake_harness.submitted_texts_by_session_identifier[
            rotation_outcome.new_branch_session_identifier
        ][0]
    )
    assert distinctive_next_action_text in seed_given_to_the_new_session


def test_the_next_action_is_not_sent_to_the_accumulating_session(test_harness) -> None:
    """It is passed from one working session to the next, and nowhere else.

    The session that accumulates history has no user turn to act on, so an
    instruction there has nothing to do and would only add to what it carries.
    """
    distinctive_next_action_text = "Report the WOMBAT-8842 findings to the user."
    first_branch_session_identifier = (
        test_harness.orchestrator.start_first_branch_session()
    )
    test_harness.stage_completed_turn(
        first_branch_session_identifier, next_action_text=distinctive_next_action_text
    )

    test_harness.orchestrator.rotate_to_next_branch_session()

    texts_sent_to_the_accumulating_session = (
        test_harness.fake_harness.submitted_texts_by_session_identifier[
            BASE_SESSION_IDENTIFIER
        ]
    )
    for submitted_text in texts_sent_to_the_accumulating_session:
        assert distinctive_next_action_text not in submitted_text


def test_every_session_is_seeded_with_the_output_contract(test_harness) -> None:
    """The format is needed on every session; only the opening sentence differs."""
    first_branch_session_identifier = (
        test_harness.orchestrator.start_first_branch_session()
    )
    test_harness.stage_completed_turn(first_branch_session_identifier)
    rotation_outcome = test_harness.orchestrator.rotate_to_next_branch_session()

    seeds_by_session = test_harness.fake_harness.submitted_texts_by_session_identifier
    for session_identifier in (
        first_branch_session_identifier,
        rotation_outcome.new_branch_session_identifier,
    ):
        assert "## Output format" in seeds_by_session[session_identifier][0]


def test_the_branch_command_line_comes_from_the_harness(test_harness) -> None:
    """The window layer must never construct a harness command itself."""
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()

    recorded_events = test_harness.fake_user_interface_control.event_log_by_window_identifier[
        WINDOW_IDENTIFIER
    ]
    run_command_events = [
        event for event in recorded_events if event[0] == "run_command_line_in_shared_window"
    ]
    assert branch_session_identifier in run_command_events[-1][1]


def test_each_branch_is_registered_as_a_session_the_user_types_into(
    test_harness, tmp_path
) -> None:
    """Without this the prompt hook cannot tell the user's words from ours."""
    from context_handoff.user_prompt_log.user_facing_session_registry import (
        UserFacingSessionRegistry,
    )

    first_branch = test_harness.orchestrator.start_first_branch_session()
    registry = UserFacingSessionRegistry(str(tmp_path))
    assert registry.is_user_facing_session(first_branch) is True
    # The base session is driven by the orchestrator alone and must never be
    # mistaken for somewhere the user is typing.
    assert registry.is_user_facing_session(BASE_SESSION_IDENTIFIER) is False

    test_harness.stage_completed_turn(first_branch)
    outcome = test_harness.orchestrator.rotate_to_next_branch_session()
    assert registry.is_user_facing_session(outcome.new_branch_session_identifier) is True


def test_rotating_without_a_pending_handoff_raises(test_harness) -> None:
    test_harness.orchestrator.start_first_branch_session()
    with pytest.raises(NoPendingHandoffError):
        test_harness.orchestrator.rotate_to_next_branch_session()


def test_a_pending_handoff_is_detected(test_harness) -> None:
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()
    assert test_harness.orchestrator.has_pending_handoff() is False

    test_harness.stage_completed_turn(branch_session_identifier)

    assert test_harness.orchestrator.has_pending_handoff() is True


def test_rotation_interrupts_before_it_shows_the_status_line(test_harness) -> None:
    """Order matters: a status line typed into a busy pane would be swallowed."""
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(branch_session_identifier)

    test_harness.orchestrator.rotate_to_next_branch_session()

    event_kinds = test_harness.window_event_kinds()
    assert event_kinds.index("send_interrupt_to_shared_window") < event_kinds.index(
        "display_status_line_in_shared_window"
    )


def test_rotation_sends_the_interrupt_twice(test_harness) -> None:
    """One interrupt cancels the agent's turn; a second exits the session."""
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(branch_session_identifier)

    test_harness.orchestrator.rotate_to_next_branch_session()

    interrupt_events = [
        event
        for event in test_harness.fake_user_interface_control.event_log_by_window_identifier[
            WINDOW_IDENTIFIER
        ]
        if event[0] == "send_interrupt_to_shared_window"
    ]
    assert interrupt_events[0][1] == INTERRUPT_REPEAT_COUNT_FOR_SESSION_SWAP


def test_rotation_shows_the_documented_status_text(test_harness) -> None:
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(branch_session_identifier)

    test_harness.orchestrator.rotate_to_next_branch_session()

    status_events = [
        event
        for event in test_harness.fake_user_interface_control.event_log_by_window_identifier[
            WINDOW_IDENTIFIER
        ]
        if event[0] == "display_status_line_in_shared_window"
    ]
    assert status_events[0][1] == SHARED_WINDOW_STATUS_TEXT_WHILE_UPDATING_BASE


def test_rotation_submits_the_handoff_to_the_base_session(test_harness) -> None:
    branch_session_identifier = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(branch_session_identifier, "MY EXACT WORDS")

    test_harness.orchestrator.rotate_to_next_branch_session()

    submitted_texts = test_harness.fake_harness.submitted_texts_by_session_identifier[
        BASE_SESSION_IDENTIFIER
    ]
    assert len(submitted_texts) == 1
    assert "MY EXACT WORDS" in submitted_texts[0]
    assert "A fact worth keeping." in submitted_texts[0]
    assert ACKNOWLEDGE_ONLY_INSTRUCTION_TEXT in submitted_texts[0]


def test_rotation_launches_the_next_branch_from_the_base_session(test_harness) -> None:
    """Each branch forks the base, never the previous branch."""
    first_branch = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(first_branch)

    outcome = test_harness.orchestrator.rotate_to_next_branch_session()

    assert test_harness.fake_harness.created_branch_parent_identifiers == [
        BASE_SESSION_IDENTIFIER,
        BASE_SESSION_IDENTIFIER,
    ]
    assert outcome.new_branch_session_identifier != first_branch


def test_rotation_reuses_the_same_window(test_harness) -> None:
    first_branch = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(first_branch)

    test_harness.orchestrator.rotate_to_next_branch_session()

    assert list(
        test_harness.fake_user_interface_control.event_log_by_window_identifier.keys()
    ) == [WINDOW_IDENTIFIER]
    assert test_harness.fake_user_interface_control.closed_window_identifiers == []


def test_rotation_rotates_the_context_file_into_history(test_harness) -> None:
    first_branch = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(first_branch)

    outcome = test_harness.orchestrator.rotate_to_next_branch_session()

    assert outcome.rotated_history_path.endswith(
        "context-to-keep-20260728T120000Z.json"
    )
    assert test_harness.context_to_keep_store.has_pending_context_to_keep() is False


def test_rotation_marks_the_forwarded_prompts_consumed(test_harness) -> None:
    """A prompt already sent to the base must not be sent again next turn."""
    first_branch = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(first_branch, "only once please")

    test_harness.orchestrator.rotate_to_next_branch_session()

    assert (
        test_harness.user_prompt_log_store.read_unconsumed_entries_for_session(
            first_branch
        )
        == []
    )


def test_a_prompt_typed_mid_rotation_is_carried_by_the_next_handoff(
    test_harness,
) -> None:
    first_branch = test_harness.orchestrator.start_first_branch_session()
    test_harness.stage_completed_turn(first_branch, "first turn words")
    test_harness.orchestrator.rotate_to_next_branch_session()

    # The user typed into the old branch while the swap was under way.
    test_harness.user_prompt_log_store.append_user_prompt_entry(
        first_branch, "typed while swapping"
    )
    second_branch = test_harness.orchestrator.current_branch_session_identifier
    test_harness.stage_completed_turn(second_branch, "second turn words")

    test_harness.orchestrator.rotate_to_next_branch_session()

    second_submission = test_harness.fake_harness.submitted_texts_by_session_identifier[
        BASE_SESSION_IDENTIFIER
    ][1]
    assert "typed while swapping" in second_submission
    assert "second turn words" in second_submission
    assert "first turn words" not in second_submission


def test_a_timed_out_acknowledgment_is_reported_but_does_not_stop_the_loop(
    tmp_path,
) -> None:
    """Losing an ack is bad; leaving the user without a window is worse."""
    timing_out_harness = OrchestratorTestHarness(
        str(tmp_path), harness_should_time_out=True
    )
    first_branch = timing_out_harness.orchestrator.start_first_branch_session()
    timing_out_harness.stage_completed_turn(first_branch)

    outcome = timing_out_harness.orchestrator.rotate_to_next_branch_session()

    assert outcome.base_session_acknowledgment.timed_out is True
    assert outcome.new_branch_session_identifier
    assert timing_out_harness.fake_user_interface_control.is_shared_window_alive(
        WINDOW_IDENTIFIER
    )


def test_the_orchestrator_module_imports_no_adapter() -> None:
    """The boundary check, stated as a test rather than as a convention."""
    import ast
    import os

    orchestrator_source_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "context_handoff",
        "orchestration",
        "turn_rotation_orchestrator.py",
    )
    with open(orchestrator_source_path, "r", encoding="utf-8") as source_file:
        parsed_module = ast.parse(source_file.read())
    imported_module_names: list[str] = []
    for node in ast.walk(parsed_module):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_module_names.append(node.module)
        elif isinstance(node, ast.Import):
            imported_module_names.extend(alias.name for alias in node.names)
    assert not any("adapters" in name for name in imported_module_names)
