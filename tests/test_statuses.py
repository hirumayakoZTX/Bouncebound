"""Status data fixtures, immutable views, and refresh storage without runtime rules."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from src.statuses import StatusEffect, StatusKind, StatusState


def fixture(kind, turn=1, source='fixture'):
    return StatusEffect(kind, None if kind is StatusKind.RERAISE else 2, turn, source,
                        charges=1 if kind in (StatusKind.WARD, StatusKind.RERAISE) else None)


class StatusDataTests(unittest.TestCase):
    def test_kind_classification_and_future_revive_hp(self):
        for kind in StatusKind:
            with self.subTest(kind=kind):
                effect = fixture(kind)
                positive = kind in (StatusKind.WARD, StatusKind.LEVITATION, StatusKind.RERAISE)
                self.assertEqual(effect.beneficial, positive)
                self.assertEqual(effect.negative, not positive)
                self.assertEqual(effect.revival_hp, 50 if kind is StatusKind.RERAISE else None)

    def test_status_fields_are_immutable(self):
        effect = fixture(StatusKind.POISON)
        for field, value in (('remaining_turns', 0), ('applied_turn', 9), ('kind', StatusKind.DOOM)):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(effect, field, value)

    def test_bad_kind_timing_sources_and_charge_models_are_rejected(self):
        invalid = [dict(kind='poison', remaining_turns=2, applied_turn=1)]
        invalid += [dict(kind=StatusKind.POISON, remaining_turns=n, applied_turn=1)
                    for n in (0, -1, True, 1.5)]
        invalid += [dict(kind=StatusKind.POISON, remaining_turns=2, applied_turn=n)
                    for n in (0, -1, False, 1.5)]
        invalid += [dict(kind=StatusKind.POISON, remaining_turns=2, applied_turn=1, source_id=n)
                    for n in (0, True, '', '  ', [])]
        invalid += [dict(kind=StatusKind.WARD, remaining_turns=1, applied_turn=1, charges=n)
                    for n in (None, 0, 2, True)]
        invalid += [dict(kind=StatusKind.LEVITATION, remaining_turns=1, applied_turn=1, charges=1),
                    dict(kind=StatusKind.LEVITATION, remaining_turns=None, applied_turn=1),
                    dict(kind=StatusKind.WARD, remaining_turns=None, applied_turn=1, charges=1),
                    dict(kind=StatusKind.RERAISE, remaining_turns=1, applied_turn=1, charges=1)]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                StatusEffect(**values)

    def test_refresh_replaces_one_record_and_retains_old_snapshot(self):
        state = StatusState()
        old = fixture(StatusKind.WARD)
        new = fixture(StatusKind.WARD, turn=5, source='refresh')
        self.assertIsNone(state.put(old))
        snapshot = state.snapshot()
        self.assertIs(state.put(new), old)
        self.assertIs(state.get(StatusKind.WARD), new)
        self.assertEqual(len(state.snapshot()), 1)
        self.assertEqual(state.get(StatusKind.WARD).charges, 1)
        self.assertEqual(snapshot, (old,))
        self.assertEqual(snapshot[0].applied_turn, 1)

    def test_snapshot_order_is_deterministic_across_insertion_orders(self):
        states = []
        for kinds in (tuple(StatusKind), tuple(reversed(tuple(StatusKind)))):
            state = StatusState()
            for kind in kinds:
                state.put(fixture(kind))
            states.append(state.snapshot())
        self.assertEqual(states[0], states[1])
        self.assertEqual([e.kind.value for e in states[0]], sorted(k.value for k in StatusKind))

    def test_remove_and_reset_are_data_operations_with_no_other_effects(self):
        state = StatusState()
        poison = fixture(StatusKind.POISON, source=42)
        state.put(poison)
        state.put(fixture(StatusKind.BIND))
        self.assertIs(state.remove(StatusKind.POISON), poison)
        self.assertIsNone(state.remove(StatusKind.POISON))
        state.reset()
        self.assertEqual(state.snapshot(), ())

    def test_invalid_records_do_not_modify_storage(self):
        state = StatusState()
        state.put(fixture(StatusKind.POISON))
        before = deepcopy(state)
        for value in (None, 'poison', {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                state.put(value)
            self.assertEqual(state, before)


if __name__ == '__main__':
    unittest.main()
