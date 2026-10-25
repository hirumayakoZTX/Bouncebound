"""PoisonTile data, placement, duration, defensive precedence, and ordered events."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest
from src.entities import Enemy, EnemyType
from src.hazards import HazardState, PoisonTile
from src.statuses import StatusEventKind as Event, StatusKind as Kind
from src.states import GameState
from test_status_runtime import finish_turn, world

class HazardTests(unittest.TestCase):

    def setUp(self):
        self.world = world()

    def test_placement_validation_rejects_bad_rows_durations_and_sources_atomically(self):
        for row, duration, source in ((-1, 2, None), (8, 2, None), (True, 2, None), (1.5, 2, None), (3, 0, None), (3, -1, None), (3, True, None), (3, 1.5, None), (3, 2, True), (3, 2, '')):
            before = deepcopy(vars(self.world))
            with self.assertRaises(ValueError):
                self.world.place_poison_tile(row, duration, source_id=source)
            self.assertEqual(vars(self.world), before)

    def test_tile_has_two_ticks_after_application_grace_and_then_expires(self):
        self.world.place_poison_tile(3)
        timeline = []
        for _ in range(3):
            finish_turn(self.world)
            tiles = self.world.hazards.snapshot()
            timeline.append((self.world.hp, tiles[0].remaining_turns if tiles else None))
        self.assertEqual(timeline, [(100, 2), (95, 1), (90, None)])
        hits = [e for e in self.world.status_events if e.kind is Event.HAZARD_DAMAGE]
        self.assertEqual([(e.turn, e.row, e.amount) for e in hits], [(2, 3, 5), (3, 3, 5)])

    def test_unoccupied_hazard_still_ages_and_expires_without_damage(self):
        self.world.place_poison_tile(0)
        for _ in range(3):
            finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        self.assertEqual(self.world.hazards.snapshot(), ())
        self.assertFalse(any((e.kind is Event.HAZARD_DAMAGE for e in self.world.status_events)))

    def test_duplicate_placement_refreshes_one_row_without_duplicate_damage(self):
        first = self.world.place_poison_tile(3)
        second = self.world.place_poison_tile(3)
        self.assertIs(first.kind, Event.HAZARD_PLACED)
        self.assertIs(second.kind, Event.HAZARD_REFRESHED)
        self.assertEqual(len(self.world.hazards.snapshot()), 1)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 95)
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.HAZARD_DAMAGE]), 1)

    def test_refresh_restores_duration_and_application_grace(self):
        self.world.place_poison_tile(3)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 95)
        self.world.place_poison_tile(3, 2, source_id='refresh')
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 95)
        self.assertEqual(self.world.hazards.snapshot()[0].remaining_turns, 2)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 85)
        self.assertEqual(self.world.hazards.snapshot(), ())

    def test_distinct_tiles_are_ordered_by_row_and_expire_deterministically(self):
        for row in (7, 3, 1):
            self.world.place_poison_tile(row)
        self.assertEqual([t.row for t in self.world.snapshot().hazards], [1, 3, 7])
        for _ in range(3):
            finish_turn(self.world)
        self.assertEqual(self.world.hp, 90)
        expired = [e.row for e in self.world.status_events if e.kind is Event.HAZARD_EXPIRED]
        self.assertEqual(expired, [1, 3, 7])

    def test_levitation_blocks_one_full_phase_and_does_not_extend_hazard_lifetime(self):
        self.world.place_poison_tile(3)
        finish_turn(self.world)
        self.world.stage = 2
        self.world.execute_support_spell('lev', 'levitation')
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        self.assertIsNone(self.world.statuses.get(Kind.LEVITATION))
        self.assertEqual(self.world.hazards.snapshot()[0].remaining_turns, 1)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 95)
        self.assertEqual(self.world.hazards.snapshot(), ())
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.LEVITATION_BLOCKED]), 1)

    def test_levitation_does_not_protect_contact_or_remove_poison(self):
        self.world.place_poison_tile(3)
        self.world.apply_status(Kind.POISON, 3)
        finish_turn(self.world)
        self.world.apply_status(Kind.LEVITATION)
        self.world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 13, 1))
        finish_turn(self.world)
        # Contact costs 5 HP and Poison costs 3; Levitation blocks the floor.
        self.assertEqual(self.world.hp, 92)
        self.assertEqual(self.world.statuses.get(Kind.POISON).remaining_turns, 2)

    def test_levitation_does_not_protect_from_doom(self):
        self.world.apply_status(Kind.DOOM, 1)
        finish_turn(self.world)
        self.world.apply_status(Kind.LEVITATION)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 0)
        self.assertIs(self.world.state, GameState.GAME_OVER)

    def test_ward_blocks_floor_first_then_poison_uses_same_damage_path(self):
        self.world.place_poison_tile(3)
        self.world.apply_status(Kind.POISON, 1)
        finish_turn(self.world)
        self.world.apply_status(Kind.WARD)
        start = len(self.world.status_events)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 97)
        events = self.world.status_events[start:]
        block = next((e for e in events if e.kind is Event.WARD_BLOCKED))
        self.assertEqual((block.source_id, block.attempted_damage), ('poison_tile', 5))
        self.assertTrue(any((e.kind is Event.POISON_DAMAGE for e in events)))

    def test_levitation_blocks_hazard_before_ward_is_available_for_poison(self):
        self.world.place_poison_tile(3)
        self.world.apply_status(Kind.POISON, 1)
        finish_turn(self.world)
        self.world.apply_status(Kind.WARD)
        self.world.apply_status(Kind.LEVITATION)
        start = len(self.world.status_events)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        events = self.world.status_events[start:]
        block = next((e for e in events if e.kind is Event.WARD_BLOCKED))
        self.assertEqual((block.source_id, block.attempted_damage), ('poison', 3))
        self.assertIs(events[0].kind, Event.LEVITATION_BLOCKED)

    def test_damage_doom_revival_and_expiry_event_order_is_exact(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.world.place_poison_tile(3)
        self.world.apply_status(Kind.POISON, 2)
        self.world.apply_status(Kind.DOOM, 1)
        finish_turn(self.world)
        self.world.apply_status(Kind.WARD)
        start = len(self.world.status_events)
        finish_turn(self.world)
        self.assertEqual([e.kind for e in self.world.status_events[start:]], [Event.WARD_BLOCKED, Event.REMOVED, Event.POISON_DAMAGE, Event.DOOM_ADVANCED, Event.EXPIRED, Event.FORCED_KNOCKOUT, Event.REMOVED, Event.RERAISE_ACTIVATED, Event.DURATION_ADVANCED, Event.DURATION_ADVANCED])
        self.assertEqual(self.world.hp, 50)
        self.assertEqual(self.world.turn_index, 3)

    def test_hazard_can_revive_then_later_poison_can_cause_another_knockout(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.world.place_poison_tile(3)
        self.world.apply_status(Kind.POISON, 1)
        finish_turn(self.world)
        self.world.hp = 5
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 47)
        self.assertIsNone(self.world.statuses.get(Kind.RERAISE))
        self.assertTrue(self.world.reraise_used)

    def test_poison_revival_does_not_protect_from_a_later_doom_knockout(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.world.apply_status(Kind.POISON, 1)
        self.world.apply_status(Kind.DOOM, 1)
        finish_turn(self.world)
        self.world.hp = 3
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 0)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.RERAISE_ACTIVATED]), 1)

    def test_hazards_do_not_become_projectile_targets_or_consume_projectile_hits(self):
        targets = self.world.combat.targets()
        self.world.place_poison_tile(3)
        self.assertEqual(self.world.combat.targets(), targets)
        self.world.set_aim_target((96, 240))
        self.world.fire()
        orb = self.world.projectiles[0]
        for _ in range(20):
            self.world.advance_time(0.25)
        self.assertEqual(orb.hits, 0)
        self.assertEqual(self.world.hp, 100)

    def test_safe_removal_does_not_repeat_events_and_invalid_removal_is_atomic(self):
        self.world.place_poison_tile(3)
        tile = self.world.remove_poison_tile(3)
        self.assertEqual(tile.row, 3)
        before = deepcopy(vars(self.world))
        self.assertIsNone(self.world.remove_poison_tile(3))
        self.assertEqual(vars(self.world), before)
        with self.assertRaises(ValueError):
            self.world.remove_poison_tile(8)
        self.assertEqual(vars(self.world), before)

    def test_hazard_snapshots_and_processing_events_are_immutable(self):
        self.world.place_poison_tile(3)
        snapshot = self.world.snapshot()
        for _ in range(3):
            finish_turn(self.world)
        self.assertEqual(snapshot.hazards[0].remaining_turns, 2)
        with self.assertRaises(FrozenInstanceError):
            snapshot.hazards[0].remaining_turns = 1
        with self.assertRaises(FrozenInstanceError):
            snapshot.status_events[0].row = 0

    def test_hazard_phase_guards_prevent_repeated_aging_and_reset_clears_them(self):
        state = HazardState()
        tile = PoisonTile(3, 2, 1)
        state.put(tile)
        self.assertEqual(state.begin_phase(1), ())
        due = state.begin_phase(2)
        self.assertEqual(due, (tile,))
        state.finish_phase(2, due)
        before = deepcopy(state)
        self.assertEqual(state.begin_phase(2), ())
        self.assertEqual(state.finish_phase(2, due), ())
        self.assertEqual(state, before)
        state.reset()
        self.assertEqual(state, HazardState())
if __name__ == '__main__':
    unittest.main()
