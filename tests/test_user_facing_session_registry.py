"""Tests for the registry of sessions whose prompts are genuinely the user's.

This is the gate that keeps the verbatim log verbatim. The orchestrator drives
several sessions the user never types into — the base session, and the
short-lived non-interactive calls that seed a branch or deliver a handoff — and
every one of them fires the prompt-submit hook. Without a gate, the log fills
with the orchestrator's own words presented as the user's.

Mirrors the membership gate in the implementation the spec names as the
reference: a session that is not registered is ignored entirely.
"""
from __future__ import annotations

import json
import os

from context_handoff.user_prompt_log.user_facing_session_registry import (
    UserFacingSessionRegistry,
)


def build_registry(tmp_path) -> UserFacingSessionRegistry:
    return UserFacingSessionRegistry(project_directory=str(tmp_path))


def test_no_session_is_user_facing_before_any_is_registered(tmp_path) -> None:
    """Default deny: an unknown session is never treated as the user's."""
    assert build_registry(tmp_path).is_user_facing_session("any-session") is False


def test_a_registered_session_is_user_facing(tmp_path) -> None:
    registry = build_registry(tmp_path)
    registry.register_user_facing_session("branch-one")
    assert registry.is_user_facing_session("branch-one") is True


def test_an_unregistered_session_stays_excluded(tmp_path) -> None:
    registry = build_registry(tmp_path)
    registry.register_user_facing_session("branch-one")
    assert registry.is_user_facing_session("the-base-session") is False


def test_registration_survives_a_new_registry_instance(tmp_path) -> None:
    """The hook is a separate process from the orchestrator that registers."""
    build_registry(tmp_path).register_user_facing_session("branch-one")
    assert build_registry(tmp_path).is_user_facing_session("branch-one") is True


def test_registering_twice_is_harmless(tmp_path) -> None:
    registry = build_registry(tmp_path)
    registry.register_user_facing_session("branch-one")
    registry.register_user_facing_session("branch-one")
    assert registry.read_registered_session_identifiers() == ["branch-one"]


def test_several_branches_accumulate_in_registration_order(tmp_path) -> None:
    """Rotation makes a new branch each turn; earlier ones stay recognised."""
    registry = build_registry(tmp_path)
    registry.register_user_facing_session("branch-one")
    registry.register_user_facing_session("branch-two")
    assert registry.read_registered_session_identifiers() == ["branch-one", "branch-two"]
    assert registry.is_user_facing_session("branch-one") is True


def test_a_session_being_seeded_is_already_capturable(tmp_path) -> None:
    """Its replies are handoffs from its first turn, seed or not.

    Found in a live run: the seeded session did its task, emitted a valid block,
    and the Stop hook discarded it because the session had not been written down
    yet.
    """
    registry = UserFacingSessionRegistry(str(tmp_path))

    registry.begin_seeding_user_facing_session("a-branch")

    assert registry.is_user_facing_session("a-branch") is True


def test_a_session_being_seeded_is_not_accepting_user_prompts_yet(tmp_path) -> None:
    """The seed travels the same path a typed prompt does, so it must not log."""
    registry = UserFacingSessionRegistry(str(tmp_path))

    registry.begin_seeding_user_facing_session("a-branch")

    assert registry.is_session_accepting_user_prompts("a-branch") is False


def test_finishing_the_seeding_hands_the_session_to_the_user(tmp_path) -> None:
    registry = UserFacingSessionRegistry(str(tmp_path))
    registry.begin_seeding_user_facing_session("a-branch")

    registry.finish_seeding_user_facing_session("a-branch")

    assert registry.is_user_facing_session("a-branch") is True
    assert registry.is_session_accepting_user_prompts("a-branch") is True


def test_seeding_state_survives_a_new_registry_instance(tmp_path) -> None:
    """The hooks read it from separate processes, so it has to be on disk."""
    UserFacingSessionRegistry(str(tmp_path)).begin_seeding_user_facing_session(
        "a-branch"
    )

    registry_in_another_process = UserFacingSessionRegistry(str(tmp_path))
    assert registry_in_another_process.is_user_facing_session("a-branch") is True
    assert (
        registry_in_another_process.is_session_accepting_user_prompts("a-branch")
        is False
    )


def test_finishing_one_session_leaves_another_still_seeding(tmp_path) -> None:
    registry = UserFacingSessionRegistry(str(tmp_path))
    registry.begin_seeding_user_facing_session("first-branch")
    registry.begin_seeding_user_facing_session("second-branch")

    registry.finish_seeding_user_facing_session("first-branch")

    assert registry.is_session_accepting_user_prompts("first-branch") is True
    assert registry.is_session_accepting_user_prompts("second-branch") is False


def test_beginning_seeding_twice_is_harmless(tmp_path) -> None:
    registry = UserFacingSessionRegistry(str(tmp_path))
    registry.begin_seeding_user_facing_session("a-branch")
    registry.begin_seeding_user_facing_session("a-branch")

    assert registry.read_registered_session_identifiers() == ["a-branch"]
    assert registry.read_session_identifiers_being_seeded() == ["a-branch"]


def test_a_session_nobody_registered_is_denied_both_ways(tmp_path) -> None:
    registry = UserFacingSessionRegistry(str(tmp_path))
    assert registry.is_user_facing_session("a-stranger") is False
    assert registry.is_session_accepting_user_prompts("a-stranger") is False


def test_a_plain_registration_accepts_user_prompts_immediately(tmp_path) -> None:
    """Nothing is being seeded, so there is no window to wait out."""
    registry = UserFacingSessionRegistry(str(tmp_path))

    registry.register_user_facing_session("a-branch")

    assert registry.is_session_accepting_user_prompts("a-branch") is True


def test_a_corrupt_registry_denies_rather_than_crashing(tmp_path) -> None:
    """Failing open would silently readmit machine prompts into the log."""
    registry = build_registry(tmp_path)
    os.makedirs(os.path.dirname(registry.registry_file_path), exist_ok=True)
    with open(registry.registry_file_path, "w", encoding="utf-8") as registry_file:
        registry_file.write("{ not json")
    assert registry.is_user_facing_session("branch-one") is False


def test_registering_after_corruption_starts_a_usable_registry(tmp_path) -> None:
    registry = build_registry(tmp_path)
    os.makedirs(os.path.dirname(registry.registry_file_path), exist_ok=True)
    with open(registry.registry_file_path, "w", encoding="utf-8") as registry_file:
        registry_file.write("{ not json")
    registry.register_user_facing_session("branch-one")
    assert registry.is_user_facing_session("branch-one") is True


def test_the_registry_file_is_readable_json(tmp_path) -> None:
    registry = build_registry(tmp_path)
    registry.register_user_facing_session("branch-one")
    with open(registry.registry_file_path, "r", encoding="utf-8") as registry_file:
        assert json.load(registry_file)["user_facing_session_identifiers"] == [
            "branch-one"
        ]


def test_a_blank_session_identifier_is_refused(tmp_path) -> None:
    registry = build_registry(tmp_path)
    registry.register_user_facing_session("   ")
    assert registry.read_registered_session_identifiers() == []
