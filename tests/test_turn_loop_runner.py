"""Tests for the polling loop that drives rotations.

Sleeping and stopping are both injected, so the loop's behaviour is asserted in
milliseconds rather than waited out — and a bug that would spin the CPU or hang
forever shows up as a failing test instead of a hung suite.
"""
from __future__ import annotations

import pytest

from context_handoff.context_to_keep.context_to_keep_file_store import (
    ContextToKeepFileStore,
)
from context_handoff.context_to_keep.context_to_keep_package import ContextToKeepPackage
from context_handoff.orchestration.turn_loop_runner import run_turn_loop_until_stopped
from context_handoff.orchestration.turn_rotation_orchestrator import (
    TurnRotationOrchestrator,
)
from context_handoff.user_prompt_log.user_prompt_log_store import UserPromptLogStore
from tests.fakes.fake_harness_recording_all_calls import FakeHarnessRecordingAllCalls
from tests.fakes.fake_user_interface_control_recording_all_calls import (
    FakeUserInterfaceControlRecordingAllCalls,
)

WINDOW_IDENTIFIER = "context-handoff-window"


class LoopTestHarness:
    def __init__(self, project_directory: str):
        self.context_to_keep_store = ContextToKeepFileStore(
            project_directory=project_directory,
            generate_timestamp_text=lambda: "20260728T120000Z",
        )
        self.fake_user_interface_control = FakeUserInterfaceControlRecordingAllCalls()
        self.orchestrator = TurnRotationOrchestrator(
            harness=FakeHarnessRecordingAllCalls(),
            user_interface_control=self.fake_user_interface_control,
            context_to_keep_store=self.context_to_keep_store,
            user_prompt_log_store=UserPromptLogStore(project_directory),
            project_directory=project_directory,
            base_session_identifier="base-session",
            shared_window_identifier=WINDOW_IDENTIFIER,
        )
        self.orchestrator.start_first_branch_session()
        self.recorded_sleep_durations: list[float] = []

    def stage_pending_handoff(self) -> None:
        self.context_to_keep_store.write_pending_context_to_keep_package(
            ContextToKeepPackage(context_to_keep=["A turn happened."])
        )

    def record_sleep(self, duration_seconds: float) -> None:
        self.recorded_sleep_durations.append(duration_seconds)


@pytest.fixture
def loop_harness(tmp_path) -> LoopTestHarness:
    return LoopTestHarness(str(tmp_path))


def test_the_loop_stops_immediately_when_told_not_to_start(loop_harness) -> None:
    completed_rotation_count = run_turn_loop_until_stopped(
        orchestrator=loop_harness.orchestrator,
        should_continue_running=lambda: False,
        sleep_for_seconds=loop_harness.record_sleep,
    )
    assert completed_rotation_count == 0
    assert loop_harness.recorded_sleep_durations == []


def test_the_loop_sleeps_rather_than_spinning_when_nothing_is_pending(
    loop_harness,
) -> None:
    """A busy-wait here would burn a core for the length of every user turn."""
    remaining_iterations = [3]

    def should_continue_running() -> bool:
        remaining_iterations[0] -= 1
        return remaining_iterations[0] >= 0

    completed_rotation_count = run_turn_loop_until_stopped(
        orchestrator=loop_harness.orchestrator,
        should_continue_running=should_continue_running,
        sleep_for_seconds=loop_harness.record_sleep,
        poll_interval_seconds=0.75,
    )

    assert completed_rotation_count == 0
    assert loop_harness.recorded_sleep_durations == [0.75, 0.75, 0.75]


def test_a_pending_handoff_is_rotated(loop_harness) -> None:
    loop_harness.stage_pending_handoff()
    remaining_iterations = [1]

    def should_continue_running() -> bool:
        remaining_iterations[0] -= 1
        return remaining_iterations[0] >= 0

    completed_rotation_count = run_turn_loop_until_stopped(
        orchestrator=loop_harness.orchestrator,
        should_continue_running=should_continue_running,
        sleep_for_seconds=loop_harness.record_sleep,
    )

    assert completed_rotation_count == 1
    assert loop_harness.context_to_keep_store.has_pending_context_to_keep() is False


def test_the_loop_does_not_sleep_after_doing_work(loop_harness) -> None:
    """A second handoff may already be waiting; sleeping first would add latency."""
    loop_harness.stage_pending_handoff()
    remaining_iterations = [1]

    def should_continue_running() -> bool:
        remaining_iterations[0] -= 1
        return remaining_iterations[0] >= 0

    run_turn_loop_until_stopped(
        orchestrator=loop_harness.orchestrator,
        should_continue_running=should_continue_running,
        sleep_for_seconds=loop_harness.record_sleep,
    )

    assert loop_harness.recorded_sleep_durations == []


def test_a_rotation_failure_is_reported_and_does_not_kill_the_loop(
    loop_harness,
) -> None:
    """One bad turn must not end the user's session."""
    observed_rotation_errors: list[Exception] = []
    loop_harness.stage_pending_handoff()

    def explode_on_rotation():
        raise RuntimeError("rotation blew up")

    loop_harness.orchestrator.rotate_to_next_branch_session = explode_on_rotation
    remaining_iterations = [2]

    def should_continue_running() -> bool:
        remaining_iterations[0] -= 1
        return remaining_iterations[0] >= 0

    completed_rotation_count = run_turn_loop_until_stopped(
        orchestrator=loop_harness.orchestrator,
        should_continue_running=should_continue_running,
        sleep_for_seconds=loop_harness.record_sleep,
        report_rotation_error=observed_rotation_errors.append,
    )

    assert completed_rotation_count == 0
    assert len(observed_rotation_errors) == 2
    assert "rotation blew up" in str(observed_rotation_errors[0])
