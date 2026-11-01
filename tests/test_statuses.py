"""Immutable Poison and Ward records with deterministic phase timing."""

from dataclasses import FrozenInstanceError, replace
import unittest

from src.statuses import (
    StatusEffect, StatusEventKind, StatusKind, StatusState,
)


def effect(kind, turn=1, remaining=2, source="fixture"):
    return StatusEffect(kind, remaining, turn, source,
                        charges=1 if kind is StatusKind.WARD else None)


class StatusDataTests(unittest.TestCase):
    def test_only_remaining_statuses_are_available(self):
        self.assertEqual(set(StatusKind), {StatusKind.POISON, StatusKind.WARD})
        self.assertEqual(StatusKind.POISON.beneficial if hasattr(StatusKind.POISON, "beneficial") else False, False)
        self.assertEqual(StatusEventKind.WARD_BLOCKED.value, "damage_blocked_by_ward")

    def test_records_validate_timing_and_ward_charge_model(self):
        invalid = [
            dict(kind="poison", remaining_turns=2, applied_turn=1),
            dict(kind=StatusKind.POISON, remaining_turns=0, applied_turn=1),
            dict(kind=StatusKind.POISON, remaining_turns=True, applied_turn=1),
            dict(kind=StatusKind.POISON, remaining_turns=2, applied_turn=0),
            dict(kind=StatusKind.WARD, remaining_turns=1, applied_turn=1),
            dict(kind=StatusKind.WARD, remaining_turns=1, applied_turn=1, charges=2),
            dict(kind=StatusKind.POISON, remaining_turns=1, applied_turn=1, charges=1),
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                StatusEffect(**values)

    def test_effects_and_events_are_immutable(self):
        record = effect(StatusKind.POISON)
        with self.assertRaises(FrozenInstanceError):
            record.remaining_turns = 1
        state = StatusState()
        state.put(record)
        with self.assertRaises(FrozenInstanceError):
            state.events[0].amount = 4

    def test_refresh_replaces_one_record_and_old_snapshot_is_stable(self):
        state = StatusState()
        old = effect(StatusKind.POISON)
        refreshed = effect(StatusKind.POISON, turn=4, remaining=3, source=7)
        state.put(old)
        snapshot = state.snapshot()
        self.assertIs(state.put(refreshed), old)
        self.assertEqual(state.snapshot(), (refreshed,))
        self.assertEqual(snapshot, (old,))
        self.assertEqual(len(state.snapshot()), 1)

    def test_poison_has_application_grace_and_one_tick_per_phase(self):
        state = StatusState()
        original = effect(StatusKind.POISON, turn=1, remaining=3)
        state.put(original)
        initial = state.snapshot()
        state.begin_phase(1)
        self.assertIsNone(state.take_poison_tick(1, original))
        state.finish_phase(1, initial)
        state.begin_phase(2)
        self.assertIsNotNone(state.take_poison_tick(2, original))
        self.assertIsNone(state.take_poison_tick(2, original))

    def test_refresh_during_phase_keeps_already_earned_tick(self):
        state = StatusState()
        original = effect(StatusKind.POISON, turn=1, remaining=3)
        state.put(original)
        state.begin_phase(2)
        initial = state.snapshot()
        due = state.take_poison_tick(2, original)
        self.assertIs(due, original)
        refreshed = effect(StatusKind.POISON, turn=2, remaining=3, source=9)
        state.put(refreshed)
        self.assertIsNone(state.take_poison_tick(2, original))
        state.finish_phase(2, initial)
        self.assertEqual(state.get(StatusKind.POISON), refreshed)

    def test_ward_has_one_charge_and_status_order_is_deterministic(self):
        states = []
        for order in ((StatusKind.POISON, StatusKind.WARD),
                      (StatusKind.WARD, StatusKind.POISON)):
            state = StatusState()
            for kind in order:
                state.put(effect(kind, remaining=1))
            states.append(state.snapshot())
        self.assertEqual(states[0], states[1])
        self.assertEqual([item.kind for item in states[0]],
                         [StatusKind.POISON, StatusKind.WARD])
        self.assertEqual(states[0][1].charges, 1)

    def test_remove_and_reset_are_data_operations(self):
        state = StatusState()
        poison = effect(StatusKind.POISON)
        state.put(poison)
        self.assertIs(state.remove(StatusKind.POISON), poison)
        state.put(effect(StatusKind.WARD))
        state.reset()
        self.assertEqual(state.snapshot(), ())
        self.assertEqual(state.events, ())


if __name__ == "__main__":
    unittest.main()
