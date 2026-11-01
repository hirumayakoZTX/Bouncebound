"""Exact status timelines and unified damage through real completed World shots."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch
from src.constants import PHYSICS_STEP
from src.encounter import EncounterDefinition, Spawn, Wave
from src.entities import Enemy, EnemyType
from src.spells import SpellFailure
from src.status_runtime import process_status_phase
from src.statuses import StatusEffect, StatusEventKind as Event, StatusKind as Kind, StatusState
from src.states import GameOverReason, GameState
from src.world import World

def world():
    result = World(demo=False)
    result.start_new_run()
    result.transition_to(GameState.PLAYER_AIM)
    return result

def finish_turn(owner):
    """Short orb lifetime isolates the real shot/turn resolver, without skipping it."""
    assert owner.set_aim_target((96, owner.player_position[1]))
    assert owner.fire()
    for orb in owner.projectiles:
        orb.max_lifetime = PHYSICS_STEP
    owner.advance_time(PHYSICS_STEP)
    assert owner.state is GameState.TURN_RESOLVE
    assert owner.resolve_turn()

class StatusRuntimeTests(unittest.TestCase):

    def setUp(self):
        self.world = world()

    def apply(self, kind, duration=None):
        return self.world.apply_status(kind, duration, source_id='fixture')

    def test_three_turn_poison_skips_application_then_ticks_exactly_three_times(self):
        self.apply(Kind.POISON, 3)
        timeline = []
        for _ in range(4):
            finish_turn(self.world)
            effect = self.world.statuses.get(Kind.POISON)
            timeline.append((self.world.hp, effect.remaining_turns if effect else None))
        self.assertEqual(timeline, [(100, 3), (97, 2), (94, 1), (91, None)])
        events = [e for e in self.world.status_events if e.kind is Event.POISON_DAMAGE]
        self.assertEqual([(e.turn, e.amount, e.attempted_damage) for e in events], [(2, 3, 3), (3, 3, 3), (4, 3, 3)])
        self.assertEqual((self.world.mp, self.world.bp), (100, 1))

    def test_poison_does_not_process_during_orb_animation_or_repeated_resolution(self):
        self.apply(Kind.POISON, 1)
        self.world.set_aim_target((96, 240))
        self.world.fire()
        before = self.world.snapshot().statuses
        for _ in range(20):
            self.world.advance_time(0.25)
        self.assertEqual(self.world.hp, 100)
        self.assertEqual(self.world.snapshot().statuses, before)
        self.world.resolve_turn()
        state = deepcopy(vars(self.world))
        for _ in range(10):
            self.assertFalse(self.world.resolve_turn())
            self.world.advance_time(1000)
        self.assertEqual(vars(self.world), state)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 97)

    def test_poison_refresh_restarts_duration_and_application_grace_without_stacks(self):
        self.apply(Kind.POISON, 3)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 97)
        event = self.apply(Kind.POISON, 2)
        self.assertIs(event.kind, Event.REFRESHED)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 97)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 91)
        self.assertIsNone(self.world.statuses.get(Kind.POISON))
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.POISON_DAMAGE]), 3)


    def test_poison_can_defeat_without_revival(self):
        self.apply(Kind.POISON, 1)
        self.world.hp = 3
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual((self.world.hp, self.world.turn_index), (0, 2))
        self.assertIs(self.world.game_over_reason, GameOverReason.HP_DEPLETED)







    def test_ward_blocks_first_positive_damage_not_zero_or_second_hit(self):
        self.world.execute_support_spell('barrier', 'barrier')
        self.assertEqual(self.world.apply_player_damage(0), 0)
        self.assertIsNotNone(self.world.statuses.get(Kind.WARD))
        self.assertEqual(self.world.apply_player_damage(7), 0)
        self.assertEqual(self.world.hp, 100)
        self.assertIsNone(self.world.statuses.get(Kind.WARD))
        self.assertEqual(self.world.apply_player_damage(7), 7)
        self.assertEqual(self.world.hp, 93)
        block = [e for e in self.world.status_events if e.kind is Event.WARD_BLOCKED]
        self.assertEqual([(e.amount, e.attempted_damage) for e in block], [(0, 7)])

    def test_unused_ward_expires_after_current_full_phase_not_before_contact(self):
        self.world.execute_support_spell('barrier', 'barrier')
        self.world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 13, 3))
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        self.assertTrue(self.world.enemies[1].escaped)
        self.assertIsNone(self.world.statuses.get(Kind.WARD))
        self.assertEqual(self.world.apply_player_damage(5), 5)


    def test_defense_granted_mid_enemy_phase_is_not_aged_until_next_full_phase(self):
        target = Enemy(1, EnemyType.BASIC, 0, 3)
        self.world.combat.add_enemy(target)
        original = target.on_turn

        def grant(context):
            claimed = original(context)
            if context.turn_index == 1:
                self.world.apply_status(Kind.WARD)
            return claimed
        with patch.object(target, 'on_turn', side_effect=grant):
            finish_turn(self.world)
            self.assertIsNotNone(self.world.statuses.get(Kind.WARD))
            finish_turn(self.world)
            self.assertIsNone(self.world.statuses.get(Kind.WARD))

    def test_ward_refresh_is_single_charge_and_records_the_new_application(self):
        self.apply(Kind.WARD)
        self.apply(Kind.WARD)
        self.assertEqual(len(self.world.statuses.snapshot()), 1)
        self.assertEqual(self.world.statuses.get(Kind.WARD).charges, 1)
        self.world.apply_player_damage(1)
        self.world.apply_player_damage(1)
        self.assertEqual(self.world.hp, 99)
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.WARD_BLOCKED]), 1)








    def test_status_phase_api_is_guarded_against_duplicate_processing(self):
        self.apply(Kind.POISON, 3)
        finish_turn(self.world)
        self.world.set_aim_target((96, 240))
        self.world.fire()
        self.world.projectiles[0].max_lifetime = PHYSICS_STEP
        self.world.advance_time(PHYSICS_STEP)
        initial = self.world.statuses.snapshot()
        self.assertTrue(process_status_phase(self.world, initial))
        before = deepcopy(vars(self.world))
        self.assertEqual(process_status_phase(self.world, initial), ())
        self.assertEqual(vars(self.world), before)
        self.assertEqual(self.world.hp, 97)


    def test_events_are_immutable_and_snapshots_keep_old_records(self):
        self.apply(Kind.POISON, 1)
        snapshot = self.world.snapshot()
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(snapshot.statuses[0].remaining_turns, 1)
        self.assertEqual(len(snapshot.status_events), 1)
        with self.assertRaises(FrozenInstanceError):
            snapshot.status_events[0].amount = 9

    def test_status_phase_helpers_and_reset_are_idempotent(self):
        state = StatusState()
        record = StatusEffect(Kind.POISON, 1, 1)
        state.put(record)
        self.assertTrue(state.begin_phase(1))
        self.assertFalse(state.begin_phase(1))
        state.finish_phase(1, (record,))
        self.assertIsNone(state.take_poison_tick(1))
        self.assertIsNotNone(state.take_poison_tick(2))
        self.assertIsNone(state.take_poison_tick(2))
        state.reset()
        self.assertEqual(state, StatusState())
if __name__ == '__main__':
    unittest.main()
