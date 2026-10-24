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

    def test_esuna_prevents_next_poison_tick_and_removes_bind(self):
        self.apply(Kind.POISON, 3)
        self.apply(Kind.BIND, 1)
        finish_turn(self.world)
        self.assertFalse(self.world.move_player(-1))
        self.world.stage = 2
        result = self.world.execute_support_spell('cleanse', 'esuna')
        self.assertTrue(result.valid)
        self.assertTrue(self.world.move_player(-1))
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        self.assertFalse(any((e.kind is Event.POISON_DAMAGE for e in self.world.status_events)))

    def test_poison_can_defeat_without_revival(self):
        self.apply(Kind.POISON, 1)
        self.world.hp = 3
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual((self.world.hp, self.world.turn_index), (0, 2))
        self.assertIs(self.world.game_over_reason, GameOverReason.HP_DEPLETED)

    def test_lethal_poison_revives_atomically_at_fifty_once(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.apply(Kind.POISON, 2)
        self.world.hp = 3
        finish_turn(self.world)
        with patch.object(self.world, 'transition_to', wraps=self.world.transition_to) as scene:
            finish_turn(self.world)
            self.assertFalse(any((c.args == (GameState.GAME_OVER,) for c in scene.call_args_list)))
        self.assertEqual(self.world.hp, 50)
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        self.assertIsNone(self.world.statuses.get(Kind.RERAISE))
        self.assertTrue(self.world.reraise_used)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 47)

    def test_bind_blocks_model_movement_but_not_aiming_shooting_or_resources(self):
        self.apply(Kind.BIND, 1)
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.move_player(-1))
        self.assertFalse(self.world.move_player(1))
        self.assertEqual(vars(self.world), before)
        self.assertTrue(self.world.set_aim_target((96, 240)))
        finish_turn(self.world)
        self.assertFalse(self.world.move_player(-1))
        finish_turn(self.world)
        self.assertTrue(self.world.move_player(-1))
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp), (100, 100, 1))
        self.assertEqual(self.world.turn_index, 3)

    def test_bind_refresh_preserves_one_record_and_new_full_input_interval(self):
        self.apply(Kind.BIND, 1)
        finish_turn(self.world)
        self.apply(Kind.BIND, 1)
        finish_turn(self.world)
        self.assertFalse(self.world.move_player(-1))
        self.assertEqual(len(self.world.statuses.snapshot()), 1)
        finish_turn(self.world)
        self.assertTrue(self.world.move_player(-1))

    def test_five_turn_doom_application_and_each_countdown_boundary(self):
        self.apply(Kind.DOOM, 5)
        timeline = []
        for _ in range(6):
            finish_turn(self.world)
            effect = self.world.statuses.get(Kind.DOOM)
            timeline.append(effect.remaining_turns if effect else 0)
        self.assertEqual(timeline, [5, 4, 3, 2, 1, 0])
        events = [e for e in self.world.status_events if e.kind is Event.DOOM_ADVANCED]
        self.assertEqual([(e.turn, e.remaining_turns) for e in events], [(2, 4), (3, 3), (4, 2), (5, 1), (6, 0)])
        self.assertEqual((self.world.hp, self.world.turn_index), (0, 6))
        self.assertIs(self.world.state, GameState.GAME_OVER)

    def test_doom_refresh_resets_countdown_and_esuna_cannot_cleanse_it(self):
        self.apply(Kind.DOOM, 2)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.statuses.get(Kind.DOOM).remaining_turns, 1)
        self.apply(Kind.DOOM, 3)
        self.world.stage = 2
        self.assertTrue(self.world.execute_support_spell('esuna', 'esuna').valid)
        finish_turn(self.world)
        self.assertEqual(self.world.statuses.get(Kind.DOOM).remaining_turns, 3)
        finish_turn(self.world)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        finish_turn(self.world)
        self.assertIs(self.world.state, GameState.GAME_OVER)

    def test_doom_bypasses_ward_and_consumes_reraise_without_retrigger(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.apply(Kind.DOOM, 1)
        finish_turn(self.world)
        self.apply(Kind.WARD)
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 50)
        self.assertIsNone(self.world.statuses.get(Kind.DOOM))
        self.assertIsNone(self.world.statuses.get(Kind.RERAISE))
        self.assertFalse(any((e.kind is Event.WARD_BLOCKED for e in self.world.status_events)))
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 50)
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.FORCED_KNOCKOUT]), 1)

    def test_ward_blocks_first_positive_damage_not_zero_or_second_hit(self):
        self.world.execute_support_spell('ward', 'ward')
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
        self.world.execute_support_spell('ward', 'ward')
        self.world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 13, 3))
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 100)
        self.assertTrue(self.world.enemies[1].escaped)
        self.assertIsNone(self.world.statuses.get(Kind.WARD))
        self.assertEqual(self.world.apply_player_damage(5), 5)

    def test_unused_ward_and_levitation_cover_exactly_one_full_phase(self):
        self.world.stage = 2
        self.world.execute_support_spell('ward', 'ward')
        self.world.execute_support_spell('lev', 'levitation')
        finish_turn(self.world)
        self.assertIsNone(self.world.statuses.get(Kind.WARD))
        self.assertIsNone(self.world.statuses.get(Kind.LEVITATION))
        expired = [e.status for e in self.world.status_events if e.kind is Event.EXPIRED]
        self.assertEqual(expired, [Kind.LEVITATION, Kind.WARD])

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

    def test_ward_prevents_lethal_hit_without_consuming_reraise(self):
        self.world.execute_support_spell('ward', 'ward')
        self.world.execute_support_spell('revive', 'reraise')
        self.world.hp = 1
        self.assertEqual(self.world.apply_player_damage(5), 0)
        self.assertEqual(self.world.hp, 1)
        self.assertIsNotNone(self.world.statuses.get(Kind.RERAISE))
        self.world.apply_player_damage(5)
        self.assertEqual(self.world.hp, 50)
        self.assertIsNone(self.world.statuses.get(Kind.RERAISE))

    def test_forced_knockout_does_not_consume_ward(self):
        self.world.execute_support_spell('ward', 'ward')
        self.world.execute_support_spell('revive', 'reraise')
        self.world.force_player_knockout()
        self.assertEqual(self.world.hp, 50)
        self.assertEqual(self.world.statuses.get(Kind.WARD).charges, 1)
        self.assertFalse(any((e.kind is Event.WARD_BLOCKED for e in self.world.status_events)))

    def test_real_knockout_only_activates_reraise_once_and_reports_actual_loss(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.world.hp = 4
        self.assertEqual(self.world.apply_player_damage(99), 4)
        self.assertEqual(self.world.hp, 50)
        self.assertTrue(self.world.reraise_used)
        self.assertIs(self.world.validate_spell('reraise').failure, SpellFailure.RERAISE_USED)
        self.world.apply_player_damage(99)
        self.assertEqual(self.world.hp, 0)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.RERAISE_ACTIVATED]), 1)

    def test_zero_damage_or_preexisting_zero_hp_does_not_activate_reraise(self):
        self.world.execute_support_spell('revive', 'reraise')
        before = deepcopy(vars(self.world))
        self.world.apply_player_damage(0)
        self.assertEqual(vars(self.world), before)
        self.world.hp = 0
        self.world.apply_player_damage(5)
        self.assertIsNotNone(self.world.statuses.get(Kind.RERAISE))
        self.assertFalse(any((e.kind is Event.RERAISE_ACTIVATED for e in self.world.status_events)))

    def test_revival_allows_later_enemies_to_act_once_in_same_phase(self):
        self.world.execute_support_spell('revive', 'reraise')
        self.world.hp = 3
        for i in (3, 1, 2):
            self.world.combat.add_enemy(Enemy(i, EnemyType.BASIC, 13, i))
        finish_turn(self.world)
        self.assertEqual(self.world.hp, 40)
        self.assertEqual(self.world.turn_index, 2)
        self.assertTrue(all((e.turns_alive == 1 and e.escaped for e in self.world.enemies.values())))
        self.assertEqual(len([e for e in self.world.status_events if e.kind is Event.RERAISE_ACTIVATED]), 1)

    def test_defense_failure_with_positive_hp_does_not_trigger_reraise(self):
        config = EncounterDefinition(1, (Wave(1, (Spawn(1, 'basic', 13, 3),)),))
        owner = World(encounter=config)
        owner.start_new_run()
        owner.transition_to(GameState.PLAYER_AIM)
        owner.execute_support_spell('revive', 'reraise')
        finish_turn(owner)
        self.assertIs(owner.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertEqual(owner.hp, 95)
        self.assertIsNotNone(owner.statuses.get(Kind.RERAISE))
        self.assertFalse(any((e.kind is Event.RERAISE_ACTIVATED for e in owner.status_events)))

    def test_stage_clear_precedes_contact_hazards_poison_and_doom(self):
        config = EncounterDefinition(1, (Wave(1, (Spawn(1, 'basic', 0, 3),)),))
        owner = World(encounter=config)
        owner.start_new_run()
        owner.transition_to(GameState.PLAYER_AIM)
        owner.apply_status(Kind.POISON, 1)
        owner.apply_status(Kind.DOOM, 1)
        owner.place_poison_tile(3)
        owner.hp = 1
        finish_turn(owner)
        owner.combat.apply_damage(1, 5)
        before = owner.snapshot()
        finish_turn(owner)
        self.assertIs(owner.state, GameState.STAGE_CLEAR)
        self.assertEqual(owner.hp, 1)
        self.assertEqual(owner.statuses.snapshot(), before.statuses)
        self.assertEqual(owner.hazards.snapshot(), before.hazards)
        self.assertEqual(owner.status_events, before.status_events)

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

    def test_invalid_model_placements_do_not_change_state_or_events(self):
        for kind, duration in (('poison', 1), (Kind.POISON, 0), (Kind.DOOM, True)):
            before = deepcopy(vars(self.world))
            with self.assertRaises(ValueError):
                self.world.apply_status(kind, duration)
            self.assertEqual(vars(self.world), before)

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
