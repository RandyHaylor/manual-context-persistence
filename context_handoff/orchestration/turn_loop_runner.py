"""Poll for finished turns and rotate when one appears.

Sleeping and stopping are injected rather than called directly, which is what
makes the loop testable in milliseconds instead of in real seconds.

Two behaviours here are deliberate. The loop does not sleep after doing work,
because a second handoff may already be waiting and sleeping first would add
latency the user feels. And a failed rotation is reported but does not end the
loop: one bad turn must not take the user's session down with it.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from .turn_rotation_orchestrator import TurnRotationOrchestrator

DEFAULT_POLL_INTERVAL_SECONDS = 1.0


def run_turn_loop_until_stopped(
    orchestrator: TurnRotationOrchestrator,
    should_continue_running: Callable[[], bool],
    sleep_for_seconds: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    report_rotation_error: Optional[Callable[[Exception], None]] = None,
) -> int:
    """Rotate whenever a handoff appears; return how many rotations completed."""
    completed_rotation_count = 0
    while should_continue_running():
        if not orchestrator.has_pending_handoff():
            sleep_for_seconds(poll_interval_seconds)
            continue
        try:
            orchestrator.rotate_to_next_branch_session()
            completed_rotation_count += 1
        except Exception as rotation_error:
            if report_rotation_error is not None:
                report_rotation_error(rotation_error)
            else:
                raise
    return completed_rotation_count
