"""Prototype data, safe scheduling, terminal outcomes, and full-run regressions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

from config.prototype import PROTOTYPE
from src.combat import DeathEvent
from src.constants import INITIAL_PLAYER_ROW, PHYSICS_STEP
from src.encounter import EncounterDefinition, EncounterOutcome, Spawn, Wave
from src.entities import Enemy, EnemyType
from src.states import GameOverReason, GameState
from src.world import World


def definition(*waves):
    return EncounterDefinition(1, tuple(waves))


def aiming_world(encounter=PROTOTYPE):
    world = World(encounter=encounter)
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    return world


def finish_shot(world, row=0, *, full=False):
    while world.player_row != row:
        world.move_player(1 if world.player_row < row else -1)
    if not world.set_aim_target((96, world.player_position[1])) or not world.fire():
        raise AssertionError("Expected a valid player shot")
    if full:
        for _ in range(20):
            world.advance_time(0.25)
    else:
        for orb in world.projectiles:
            orb.max_lifetime = PHYSICS_STEP
        world.advance_time(PHYSICS_STEP)
    if world.state is not GameState.TURN_RESOLVE:
        raise AssertionError("Every orb must finish before resolution")


class EncounterDefinitionTests(unittest.TestCase):
    def test_prototype_has_four_six_enemy_waves_and_unique_ids(self):
        self.assertEqual(PROTOTYPE.stage, 1)
        self.assertEqual([wave.turn for wave in PROTOTYPE.waves], [1, 3, 5, 7])
        self.assertEqual(len(PROTOTYPE.mandatory_ids), 24)
        ids = []
        for wave in PROTOTYPE.waves:
            self.assertEqual(sum(s.kind != "crystal" for s in wave.spawns), 6)
            self.assertEqual(sum(s.kind == "bomb" for s in wave.spawns), 2)
            self.assertEqual(sum(s.kind == "crystal" for s in wave.spawns), 1)
            ids.extend(s.entity_id for s in wave.spawns)
        self.assertEqual(len(ids), len(set(ids)))

    def test_spawn_validation_rejects_bad_ids_kinds_and_grid_positions(self):
        for args in ((0, "basic", 0, 0), (True, "bomb", 0, 0),
                     (1, "boss", 0, 0), (1, "basic", -1, 0),
                     (1, "basic", 14, 0), (1, "crystal", 0, 8),
                     (1, "basic", 0.5, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Spawn(*args)

    def test_wave_validation_rejects_bad_turns_entries_and_duplicate_enemy_cells(self):
        spawn = Spawn(1, "basic", 0, 0)
        for turn, entries in ((0, (spawn,)), (True, (spawn,)), (1, ()),
                              (1, [spawn]), (1, (None,)),
                              (1, (spawn, Spawn(2, "bomb", 0, 0)))):
            with self.subTest(turn=turn, entries=entries), self.assertRaises(ValueError):
                Wave(turn, entries)

    def test_encounter_validation_rejects_bad_stage_order_ids_and_empty_enemy_set(self):
        first = Wave(1, (Spawn(1, "basic", 0, 0),))
        for stage, waves in ((4, (first,)), (True, (first,)), (1, ()),
                             (1, [first]), (1, (None,)),
                             (1, (Wave(3, first.spawns),)), (1, (first, first)),
                             (1, (first, Wave(3, first.spawns))),
                             (1, (Wave(1, (Spawn(1, "crystal", 0, 0),)),))):
            with self.subTest(stage=stage, waves=waves), self.assertRaises(ValueError):
                EncounterDefinition(stage, waves)

    def test_definition_is_immutable_and_world_requires_valid_configuration(self):
        with self.assertRaises(FrozenInstanceError):
            PROTOTYPE.stage = 2
        with self.assertRaises(FrozenInstanceError):
            PROTOTYPE.waves[0].spawns[0].row = 2
        for kwargs in ({"encounter": {}}, {"demo": 1},
                       {"demo": False, "encounter": PROTOTYPE}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                World(**kwargs)


class EncounterTests(unittest.TestCase):
    def setUp(self):
        self.world = aiming_world()

    def test_first_wave_is_present_on_initial_battlefield(self):
        self.assertEqual(list(self.world.enemies), [1, 2, 3, 4, 5, 6])
        self.assertEqual(list(self.world.crystals), [7])
        self.assertEqual(self.world.encounter.spawn_history, list(range(1, 8)))
        self.assertEqual(self.world.encounter.spawned_waves, {0})
        self.assertEqual((self.world.snapshot().spawned_waves,
                          self.world.snapshot().total_waves), (1, 4))

    def test_waves_spawn_at_new_turn_after_enemy_phase_not_during_shot(self):
        finish_shot(self.world)
        self.world.resolve_turn()
        self.assertEqual(self.world.turn_index, 2)
        self.assertNotIn(8, self.world.enemies)
        finish_shot(self.world)
        self.assertNotIn(8, self.world.enemies)
        self.world.resolve_turn()
        self.assertEqual(self.world.turn_index, 3)
        self.assertEqual(self.world.enemies[8].grid_col, 2)
        self.assertEqual(self.world.enemies[8].turns_alive, 0)
        self.assertIn(8, self.world.encounter.spawned_ids)
        self.assertNotIn(11, self.world.encounter.spawned_ids)  # An older enemy occupies this cell.

    def test_spawn_order_is_stable_and_completed_waves_spawn_only_once(self):
        before = deepcopy(vars(self.world))
        for _ in range(4):
            self.assertEqual(self.world.spawn_waves(), ())
        self.assertEqual(vars(self.world), before)
        self.world.turn_index = 7
        # Clear occupied cells to observe configuration order independently of movement.
        for enemy_id in tuple(self.world.enemies):
            self.world.combat.apply_damage(enemy_id, 5)
        self.world.spawn_waves()
        history = self.world.encounter.spawn_history[:]
        self.assertEqual(history[:7], list(range(1, 8)))
        self.assertEqual(len(history), len(set(history)))
        self.assertEqual(self.world.spawn_waves(), ())
        self.assertEqual(self.world.encounter.spawn_history, history)

    def test_occupied_spawn_is_deferred_without_overwrite_then_retried(self):
        config = definition(Wave(1, (Spawn(1, "basic", 0, 3), Spawn(2, "crystal", 0, 3))))
        world = World(encounter=config)
        world.start_new_run()
        blocker = Enemy(99, EnemyType.BASIC, 0, 3)
        world.combat.add_enemy(blocker)
        world.transition_to(GameState.PLAYER_AIM)
        self.assertIs(world.enemies[99], blocker)
        self.assertNotIn(1, world.enemies)
        self.assertIn(2, world.crystals)
        self.assertFalse(world.encounter.all_spawned)
        self.assertIsNone(world.encounter.outcome(world.combat))
        finish_shot(world)
        world.resolve_turn()
        self.assertEqual(blocker.grid_col, 1)
        self.assertEqual(world.enemies[1].grid_col, 0)
        self.assertEqual(world.enemies[1].last_action_turn, None)
        self.assertEqual(world.encounter.spawn_history, [2, 1])
        self.assertTrue(world.encounter.all_spawned)
        self.assertEqual(world.spawn_waves(), ())

    def test_partial_wave_does_not_count_as_spawned_or_clear(self):
        config = definition(Wave(1, (Spawn(1, "basic", 0, 3), Spawn(2, "basic", 1, 3))))
        world = World(encounter=config)
        world.start_new_run()
        world.combat.add_enemy(Enemy(99, EnemyType.BASIC, 1, 3))
        world.transition_to(GameState.PLAYER_AIM)
        world.combat.apply_damage(1, 5)
        finish_shot(world)
        self.assertFalse(world.check_stage_end())
        self.assertNotIn(0, world.encounter.spawned_waves)

    def test_spawning_is_blocked_in_flight_pause_and_terminal_states(self):
        for state in (GameState.SHOT_ANIMATION, GameState.PAUSED,
                      GameState.GAME_OVER, GameState.STAGE_CLEAR):
            with self.subTest(state=state):
                world = aiming_world()
                world.turn_index = 7
                world.set_aim_target((96, 96))
                world.fire()
                if state is GameState.PAUSED:
                    world.pause()
                elif state is not GameState.SHOT_ANIMATION:
                    world.transition_to(state)
                before = deepcopy(vars(world))
                self.assertEqual(world.spawn_waves(), ())
                world.advance_time(0.01)
                self.assertEqual(world.encounter, before["encounter"])
                self.assertEqual(list(world.enemies), list(before["combat"].enemies))

    def test_live_projectile_also_blocks_spawning_in_manually_changed_phase(self):
        self.world.set_aim_target((96, 96))
        self.world.fire()
        self.world.turn_index = 7
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.assertEqual(self.world.spawn_waves(), ())
        self.assertEqual(self.world.encounter.spawned_waves, {0})

    def test_empty_board_accelerates_one_future_wave_without_an_extra_action(self):
        for enemy_id in tuple(self.world.enemies):
            enemy = self.world.enemies[enemy_id]
            self.world.combat.apply_damage(enemy_id, enemy.max_hp)
        finish_shot(self.world)
        self.assertFalse(self.world.check_stage_end())
        self.world.resolve_turn()
        self.assertEqual(self.world.state, GameState.PLAYER_AIM)
        self.assertEqual(self.world.turn_index, 2)
        self.assertEqual({enemy.enemy_id for enemy in self.world.snapshot().enemies},
                         {8, 9, 10, 11, 12, 13})
        self.assertEqual(self.world.snapshot().spawned_waves, 2)
        self.assertEqual(self.world.enemies[8].turns_alive, 0)

    def test_final_kill_clears_only_after_every_projectile_and_effect_finishes(self):
        config = definition(Wave(1, (Spawn(1, "bomb", 4, 3), Spawn(2, "bomb", 5, 3),
                                          Spawn(3, "crystal", 11, 3))))
        world = aiming_world(config)
        # Keep the two Bombs one ordinary hit from defeat so this test can focus
        # on waiting for the complete projectile and chain-resolution boundary.
        world.enemies[1].hp = world.enemies[2].hp = 4
        world.set_aim_target((96, 240))
        world.fire()
        for _ in range(4):
            world.advance_time(.25)
        self.assertFalse(world.snapshot().enemies)
        self.assertIs(world.state, GameState.SHOT_ANIMATION)
        self.assertFalse(world.check_stage_end())
        self.assertFalse(world.resolve_turn())
        for _ in range(16):
            world.advance_time(.25)
        self.assertTrue(world.check_stage_end())
        self.assertEqual(world.bp, 2)
        with patch("src.world.resolve_enemy_phase") as enemy_phase, patch.object(
            world, "transition_to", wraps=world.transition_to
        ) as transition:
            self.assertTrue(world.resolve_turn())
            self.assertIs(world.state, GameState.STAGE_CLEAR)
            before = deepcopy(vars(world))
            for _ in range(3):
                self.assertFalse(world.resolve_turn())
                world.advance_time(10)
            self.assertEqual(vars(world), before)
            enemy_phase.assert_not_called()
            self.assertEqual(sum(call.args == (GameState.STAGE_CLEAR,)
                                 for call in transition.call_args_list), 1)
        self.assertEqual((world.turn_index, world.hp, world.mp, world.bp), (1, 100, 100, 2))
        self.assertIsNone(world._pending_turn)

    def test_pending_combat_and_bp_settle_before_stage_clear(self):
        world = aiming_world(definition(Wave(1, (Spawn(1, "bomb", 4, 3),))))
        finish_shot(world)
        world.enemies[1].take_damage(10)
        world.combat.pending_deaths.append(DeathEvent(1, EnemyType.BOMB, "projectile"))
        world.combat.pending_bp = 2
        self.assertFalse(world.check_stage_end())
        world.resolve_turn()
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertFalse(world.combat.pending_deaths)
        self.assertEqual((world.bp, world.pending_bp), (3, 0))
        self.assertEqual(len(world.combat.death_events), 1)

    def test_escaped_enemy_means_defense_failure_without_artificial_hp_loss(self):
        world = aiming_world(definition(Wave(1, (Spawn(1, "bomb", 13, 3),))))
        finish_shot(world)
        world.resolve_turn()
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertEqual((world.hp, world.mp, world.bp, world.turn_index), (95, 100, 1, 1))
        self.assertTrue(world.enemies[1].escaped)
        self.assertTrue(world.enemies[1].alive)
        self.assertEqual(world.combat.death_events, [])
        self.assertIs(world.encounter.outcome(world.combat), EncounterOutcome.FAILED)
        self.assertFalse(world.check_stage_end())

    def test_escape_does_not_end_run_while_future_waves_remain(self):
        config = definition(Wave(1, (Spawn(1, "basic", 13, 3),)),
                            Wave(3, (Spawn(2, "basic", 0, 3),)))
        world = aiming_world(config)
        finish_shot(world)
        world.resolve_turn()
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual(world.hp, 95)
        # The cleared board accelerates the pending wave after the escape.
        # The escaped mandatory enemy still prevents a successful clear.
        self.assertTrue(world.encounter.all_spawned)
        self.assertIsNone(world.encounter.outcome(world.combat))
        self.assertEqual(world.encounter.spawn_history, [1, 2])
        finish_shot(world)
        world.resolve_turn()
        self.assertIn(2, world.enemies)
        world.combat.apply_damage(2, 5)
        finish_shot(world)
        world.resolve_turn()
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual(world.hp, 95)

    def test_hp_depletion_takes_priority_and_stops_spawns(self):
        world = aiming_world(definition(Wave(1, (Spawn(1, "basic", 13, 3),)),
                                       Wave(3, (Spawn(2, "basic", 0, 3),))))
        world.hp = 5
        finish_shot(world)
        world.resolve_turn()
        self.assertIs(world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual((world.hp, world.turn_index), (0, 1))
        self.assertNotIn(2, world.enemies)
        self.assertEqual(world.spawn_waves(), ())

    def test_invalid_actions_do_not_change_waves_turns_or_resources(self):
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.fire())
        self.assertFalse(self.world.resolve_turn())
        self.assertFalse(self.world.restart())
        self.assertEqual(vars(self.world), before)
        self.world.move_player(-1)
        self.world.set_aim_target((96, 120))
        self.assertEqual(self.world.encounter, before["encounter"])
        self.assertEqual((self.world.turn_index, self.world.hp, self.world.mp, self.world.bp),
                         (1, 100, 100, 1))

    def test_full_prototype_can_clear_through_normal_movement_aim_and_shots(self):
        self.play_success()
        self.assertIs(self.world.state, GameState.STAGE_CLEAR)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp, self.world.turn_index),
                         (100, 100, 5, 7))
        self.assertEqual(len(self.world.combat.death_events), 24)
        self.assertEqual(self.world.encounter.spawn_history, list(range(1, 29)))
        self.assertTrue(self.world.encounter.all_spawned)
        self.assertEqual(self.world.snapshot().enemies, ())
        self.assertEqual(self.world.snapshot().crystals, ())

    def play_success(self):
        # Candidate B's 10-HP Bombs require more ordinary shots than the old
        # one-hit chain route; this historical fixture still clears normally.
        for row in (3,) * 7:
            finish_shot(self.world, row, full=True)
            self.world.resolve_turn()

    def test_full_prototype_can_lose_by_missing_without_fixture_damage(self):
        for _ in range(30):
            finish_shot(self.world, full=True)
            self.world.resolve_turn()
            if self.world.state is GameState.GAME_OVER:
                break
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertIs(self.world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertEqual(self.world.hp, 0)
        self.assertEqual(sum(e.escaped for e in self.world.enemies.values()), 20)
        self.assertEqual(self.world.combat.death_events, [])

    def test_full_prototype_failed_defense_ends_empty_board_with_hp_remaining(self):
        for _ in range(35):
            active = [enemy for enemy in self.world.enemies.values() if enemy.active]
            row = (max(active, key=lambda e: (e.enemy_type is EnemyType.BOMB, e.grid_col)).grid_row
                   if any(e.escaped for e in self.world.enemies.values()) else 0)
            finish_shot(self.world, row, full=True)
            self.world.resolve_turn()
            if self.world.state is GameState.GAME_OVER:
                break
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertIs(self.world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertGreater(self.world.hp, 0)
        self.assertEqual(self.world.snapshot().enemies, ())
        self.assertEqual(len(self.world.combat.death_events)
                         + sum(e.escaped for e in self.world.enemies.values()), 24)

    def test_restart_after_success_restores_every_owned_system(self):
        self.play_success()
        old_combat, old_encounter, old_physics = (self.world.combat, self.world.encounter,
                                                 self.world._physics)
        self.assertTrue(self.world.restart())
        expected = World(encounter=PROTOTYPE)
        expected.start_new_run()
        self.assertEqual(vars(self.world), vars(expected))
        self.assertIsNot(self.world.combat, old_combat)
        self.assertIsNot(self.world.encounter, old_encounter)
        self.assertIsNot(self.world._physics, old_physics)
        self.world.transition_to(GameState.PLAYER_AIM)
        finish_shot(self.world, 3, full=True)
        self.assertEqual(len(self.world.combat.death_events), 6)
        self.assertEqual(self.world._next_projectile_id, 2)

    def test_restart_after_defeat_resets_history_pending_events_and_fractional_physics(self):
        self.world.set_aim_target((96, 240))
        self.world.fire()
        self.world.advance_time(.004)
        stale_orb = self.world.projectiles[0]
        stale_orb.contact_ids.add(2)
        self.world.combat.apply_damage(2, 5)
        self.world.combat.pending_bp = 3
        self.world.apply_player_damage(100)
        self.assertTrue(self.world.restart())
        expected = World(encounter=PROTOTYPE)
        expected.start_new_run()
        self.assertEqual(vars(self.world), vars(expected))
        self.assertEqual(self.world._physics.accumulator, 0)
        self.assertEqual(self.world.projectiles, [])
        self.assertEqual(self.world.encounter.spawn_history, [])
        self.assertIsNone(self.world.game_over_reason)
        self.assertIsNone(self.world._pending_turn)
        self.world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(list(self.world.enemies), list(range(1, 7)))
        self.world.set_aim_target((96, 240))
        self.world.fire()
        self.assertEqual(self.world.projectiles[0].projectile_id, 1)
        self.assertIsNot(self.world.projectiles[0], stale_orb)
        self.assertFalse(self.world.projectiles[0].contact_ids)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp,
                          self.world.player_row, self.world.turn_index),
                         (100, 100, 1, INITIAL_PLAYER_ROW, 1))

    def test_repeated_restarts_restore_wave_schedule_without_stale_entities(self):
        for _ in range(3):
            self.play_success()
            self.assertTrue(self.world.restart())
            self.assertIs(self.world.state, GameState.STAGE_INTRO)
            self.world.transition_to(GameState.PLAYER_AIM)
            self.assertEqual(self.world.encounter.spawned_waves, {0})
            self.assertEqual(self.world.encounter.spawn_history, list(range(1, 8)))
            self.assertEqual(len(self.world.enemies), 6)
            self.assertEqual(len(self.world.crystals), 1)
            self.assertTrue(all(e.turns_alive == 0 and not e.escaped
                                for e in self.world.enemies.values()))

    def test_restart_clears_escape_history_and_defense_failure_reason(self):
        config = definition(Wave(1, (Spawn(1, "bomb", 13, 3),)))
        world = aiming_world(config)
        finish_shot(world)
        world.resolve_turn()
        self.assertTrue(world.enemies[1].escaped)
        self.assertTrue(world.restart())
        world.transition_to(GameState.PLAYER_AIM)
        self.assertFalse(world.enemies[1].escaped)
        self.assertIsNone(world.enemies[1].escape_turn)
        self.assertIsNone(world.game_over_reason)
        self.assertEqual((world.hp, world.enemies[1].hp), (100, 10))

    def test_restart_clears_deferred_spawn_progress(self):
        world = World(encounter=PROTOTYPE)
        world.start_new_run()
        world.combat.add_enemy(Enemy(99, EnemyType.BASIC, 2, 3))
        world.transition_to(GameState.PLAYER_AIM)
        self.assertNotIn(1, world.enemies)
        self.assertFalse(world.encounter.all_spawned)
        world.apply_player_damage(100)
        world.restart()
        world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(world.encounter.spawn_history, list(range(1, 8)))
        self.assertEqual(world.encounter.spawned_waves, {0})
        self.assertNotIn(99, world.enemies)


if __name__ == '__main__':
    unittest.main()
