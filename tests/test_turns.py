"""Deterministic enemy phases and player damage without a display."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from src.constants import PHYSICS_STEP
from src.entities import Crystal, Enemy, EnemyTurnContext, EnemyType
from src.projectile import HitEvent
from src.states import GameState
from src.turns import resolve_enemy_phase
from src.world import World
from src.encounter import EncounterDefinition, Spawn, Wave


class TurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World(demo=False)
        self.world.start_new_run()
        self.world.transition_to(GameState.PLAYER_AIM)

    def add_enemy(self, enemy_id=1, col=4, row=3, kind=EnemyType.BASIC) -> Enemy:
        enemy = Enemy(enemy_id, kind, col, row)
        self.world.combat.add_enemy(enemy)
        return enemy

    def finish_shot(self) -> None:
        # A short lifetime keeps turn tests fast; firing and physics still run.
        self.world.player_row = 0
        self.world.set_aim_target((96, 96))
        self.assertTrue(self.world.fire())
        for orb in self.world.projectiles:
            orb.max_lifetime = PHYSICS_STEP
        self.world.advance_time(PHYSICS_STEP)
        self.assertIs(self.world.state, GameState.TURN_RESOLVE)

    def test_one_completed_shot_resolves_one_phase_and_one_turn(self) -> None:
        enemy = self.add_enemy()
        self.finish_shot()
        self.assertEqual(enemy.grid_col, 4)
        self.assertEqual(self.world.turn_index, 1)
        self.assertTrue(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, enemy.grid_row), (5, 3))
        self.assertEqual((enemy.turns_alive, enemy.last_action_turn), (1, 1))
        self.assertEqual(self.world.turn_index, 2)
        self.assertEqual(self.world.last_resolved_turn, 1)
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        before = deepcopy(vars(self.world))
        for _ in range(3):
            self.assertFalse(self.world.resolve_turn())
            self.world.advance_time(100)
        self.assertEqual(vars(self.world), before)

    def test_multiple_successive_shots_follow_the_complete_sequence(self) -> None:
        enemy = self.add_enemy()
        for turn in range(1, 4):
            self.assertEqual(self.world.turn_index, turn)
            self.finish_shot()
            self.assertTrue(self.world.resolve_turn())
            self.assertEqual(enemy.grid_col, 4 + turn)
            self.assertEqual(enemy.turns_alive, turn)
            self.assertEqual(self.world.turn_index, turn + 1)

    def test_manual_scene_edges_without_a_shot_cannot_authorize_an_enemy_phase(self) -> None:
        enemy = self.add_enemy()
        self.world.transition_to(GameState.SHOT_ANIMATION)
        self.world.transition_to(GameState.TURN_RESOLVE)
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual(vars(self.world), before)
        self.assertEqual(enemy.grid_col, 4)

    def test_movement_aiming_and_invalid_actions_do_not_advance_turns(self) -> None:
        enemy = self.add_enemy()
        self.assertFalse(self.world.fire())
        self.world.set_aim_target((900, 200))
        self.assertFalse(self.world.fire())
        self.world.move_player(-1)
        self.world.move_player(1)
        self.world.set_aim_target((300, 240))
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual((self.world.turn_index, enemy.grid_col, enemy.turns_alive), (1, 4, 0))
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp), (100, 100, 1))

    def test_phase_waits_for_every_projectile(self) -> None:
        enemy = self.add_enemy()
        self.world.bp = 3
        self.world.player_row = 0
        self.world.set_aim_target((96, 96))
        self.world.fire()
        for orb, duration in zip(self.world.projectiles, (PHYSICS_STEP, 0.05, 0.1)):
            orb.max_lifetime = duration
        self.world.advance_time(PHYSICS_STEP)
        self.assertEqual(len(self.world.projectiles), 2)
        self.assertFalse(self.world.resolve_turn())
        self.world.advance_time(0.05)
        self.assertEqual(len(self.world.projectiles), 1)
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, self.world.turn_index), (4, 1))
        self.world.advance_time(0.1)
        self.assertTrue(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, self.world.turn_index), (5, 2))

    def test_resolution_rejects_live_projectiles_even_if_scene_was_changed(self) -> None:
        enemy = self.add_enemy()
        self.world.set_aim_target((96, 96))
        self.world.fire()
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, self.world.turn_index), (4, 1))

    def test_actions_and_movement_use_stable_id_order_and_preserve_rows(self) -> None:
        enemies = [self.add_enemy(enemy_id, 4, row)
                   for enemy_id, row in ((15, 3), (2, 4), (9, 5))]
        original_action = Enemy.on_turn
        actions = []

        def record_action(enemy, context):
            actions.append((enemy.enemy_id, enemy.grid_col))
            return original_action(enemy, context)

        self.finish_shot()
        with patch.object(Enemy, "on_turn", autospec=True, side_effect=record_action):
            self.world.resolve_turn()
        self.assertEqual(actions, [(2, 4), (9, 4), (15, 4)])
        for enemy, row in zip(enemies, (3, 4, 5)):
            self.assertEqual((enemy.grid_col, enemy.grid_row), (5, row))
            self.assertEqual(enemy.position, (360, 96 + 48 * row))

    def test_dead_enemies_do_not_run_action_hooks_or_move(self) -> None:
        dead = self.add_enemy(1, 5, 3)
        rear = self.add_enemy(2, 4, 3)
        self.world.combat.apply_damage(dead.enemy_id, 5)
        self.finish_shot()
        with patch.object(dead, "on_turn", wraps=dead.on_turn) as action:
            self.world.resolve_turn()
            action.assert_not_called()
        self.assertEqual((dead.grid_col, dead.turns_alive), (5, 0))
        self.assertEqual(rear.grid_col, 5)

    def test_blocked_lower_id_waits_even_if_front_enemy_moves_later(self) -> None:
        rear = self.add_enemy(1, 4, 3)
        front = self.add_enemy(2, 5, 3)
        self.finish_shot()
        self.world.resolve_turn()
        self.assertEqual((rear.grid_col, front.grid_col), (4, 6))
        self.assertEqual((rear.turns_alive, front.turns_alive), (1, 1))

    def test_cell_vacated_by_earlier_id_is_available_to_later_id(self) -> None:
        front = self.add_enemy(1, 5, 3)
        rear = self.add_enemy(2, 4, 3)
        self.finish_shot()
        self.world.resolve_turn()
        self.assertEqual((front.grid_col, rear.grid_col), (6, 5))
        self.assertEqual(len({(e.grid_col, e.grid_row) for e in self.world.enemies.values()}), 2)

    def test_crystals_do_not_block_enemy_movement(self) -> None:
        enemy = self.add_enemy()
        self.world.combat.add_crystal(Crystal(2, 5, 3))
        self.finish_shot()
        self.world.resolve_turn()
        self.assertEqual(enemy.grid_col, 5)
        self.assertFalse(self.world.crystals[2].collected)

    def test_crossing_occurs_only_when_attempting_to_leave_column_thirteen(self) -> None:
        enemy = self.add_enemy(col=12)
        self.finish_shot()
        self.world.resolve_turn()
        self.assertEqual((enemy.grid_col, self.world.hp), (13, 100))
        self.assertTrue(enemy.active)
        self.finish_shot()
        self.world.resolve_turn()
        self.assertEqual((enemy.grid_col, self.world.hp), (13, 95))
        self.assertEqual(enemy.hp, 5)
        self.assertTrue(enemy.alive)
        self.assertFalse(enemy.active)
        self.assertTrue(enemy.escaped)
        self.assertEqual(enemy.escape_turn, 2)
        self.assertEqual(self.world.snapshot().enemies, ())
        self.assertEqual(self.world.combat.targets(), ())
        self.assertEqual(self.world.combat.death_events, [])

    def test_multiple_distinct_contacts_each_deal_five_damage_once(self) -> None:
        for enemy_id, kind in ((1, EnemyType.BASIC), (2, EnemyType.BOMB), (3, EnemyType.BASIC)):
            self.add_enemy(enemy_id, 13, enemy_id + 2, kind)
        self.finish_shot()
        self.world.resolve_turn()
        self.assertEqual(self.world.hp, 85)
        self.assertTrue(all(enemy.escaped for enemy in self.world.enemies.values()))
        self.assertEqual(self.world.combat.death_events, [])
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual(self.world.hp, 85)

    def test_escaped_bomb_never_explodes_and_vacates_its_cell(self) -> None:
        bomb = self.add_enemy(1, 13, 3, EnemyType.BOMB)
        follower = self.add_enemy(2, 12, 3)
        self.finish_shot()
        self.world.resolve_turn()
        self.assertTrue(bomb.escaped)
        self.assertEqual((bomb.hp, follower.hp, follower.grid_col), (5, 5, 13))
        self.assertEqual(self.world.combat.death_events, [])
        self.assertFalse(self.world.combat.apply_damage(bomb.enemy_id, 100))
        self.assertEqual(bomb.hp, 5)
        self.assertEqual(self.world.combat.death_events, [])

    def test_later_explosion_cannot_damage_an_archived_escape(self) -> None:
        escaped = self.add_enemy(1, 13, 3, EnemyType.BOMB)
        bomb = self.add_enemy(2, 12, 4, EnemyType.BOMB)
        self.finish_shot()
        self.world.resolve_turn()
        self.world.combat.apply_damage(bomb.enemy_id, 5)
        self.assertEqual(escaped.hp, 5)
        self.assertTrue(escaped.escaped)
        self.assertEqual([event.enemy_id for event in self.world.combat.death_events], [2])

    def test_contact_defeat_stops_remaining_enemies_and_does_not_increment_turn(self) -> None:
        self.world.hp, self.world.mp, self.world.bp = 7, 42, 3
        first = self.add_enemy(1, 13, 3)
        fatal = self.add_enemy(2, 13, 4, EnemyType.BOMB)
        untouched = self.add_enemy(3, 13, 5)
        self.finish_shot()
        with patch.object(untouched, "on_turn", wraps=untouched.on_turn) as action:
            self.assertTrue(self.world.resolve_turn())
            action.assert_not_called()
        self.assertTrue(first.escaped)
        self.assertTrue(fatal.escaped)
        self.assertTrue(untouched.active)
        self.assertIsNone(untouched.last_action_turn)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp, self.world.turn_index),
                         (0, 42, 3, 1))
        self.assertIs(self.world.state, GameState.GAME_OVER)
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.resolve_turn())
        self.assertFalse(self.world.fire())
        self.world.advance_time(100)
        self.assertEqual(vars(self.world), before)

    def test_player_damage_validates_clamps_and_preserves_other_resources(self) -> None:
        self.world.hp, self.world.mp, self.world.bp = 8, 37, 4
        for amount in (-1, True, 1.5):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.world.apply_player_damage(amount)
        self.assertEqual(self.world.hp, 8)
        self.assertEqual(self.world.apply_player_damage(3), 3)
        self.assertEqual(self.world.hp, 5)
        self.assertEqual(self.world.apply_player_damage(99), 5)
        self.assertEqual(self.world.hp, 0)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual(self.world.apply_player_damage(99), 0)
        self.assertEqual((self.world.mp, self.world.bp, self.world.turn_index), (37, 4, 1))

    def test_damage_is_ignored_in_menu_intro_pause_and_game_over(self) -> None:
        world = World(demo=False)
        self.assertEqual(world.apply_player_damage(100), 0)
        world.start_new_run()
        self.assertEqual(world.apply_player_damage(100), 0)
        world.transition_to(GameState.PLAYER_AIM)
        world.pause()
        self.assertEqual(world.apply_player_damage(100), 0)
        self.assertEqual(world.hp, 100)
        world.resume()
        world.apply_player_damage(100)
        self.assertEqual(world.apply_player_damage(100), 0)
        self.assertEqual(world.hp, 0)

    def test_action_extension_runs_before_movement_and_can_stop_phase_on_defeat(self) -> None:
        enemy = self.add_enemy()
        later = self.add_enemy(2, 6, 3)
        original = enemy.on_turn

        def fatal_action(context):
            self.assertEqual(enemy.grid_col, 4)
            claimed = original(context)
            context.damage_player(100)
            return claimed

        self.finish_shot()
        with patch.object(enemy, "on_turn", side_effect=fatal_action):
            self.world.resolve_turn()
        self.assertEqual((enemy.grid_col, later.grid_col), (4, 6))
        self.assertEqual(later.turns_alive, 0)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual(self.world.turn_index, 1)

    def test_phase_helper_cannot_act_twice_for_the_same_turn(self) -> None:
        enemy = self.add_enemy()
        context = EnemyTurnContext(1, self.world.apply_player_damage, lambda: False)
        resolve_enemy_phase(self.world.enemies.values(), context)
        self.assertEqual(enemy.grid_col, 5)
        with patch.object(enemy, "on_turn", wraps=enemy.on_turn) as action:
            resolve_enemy_phase(self.world.enemies.values(), context)
            action.assert_not_called()
        self.assertEqual((enemy.grid_col, enemy.turns_alive), (5, 1))

    def test_pause_preserves_a_completed_pending_turn_until_resume(self) -> None:
        enemy = self.add_enemy()
        self.finish_shot()
        self.world.pause()
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.resolve_turn())
        self.world.advance_time(1000)
        self.assertEqual(vars(self.world), before)
        self.world.resume()
        self.assertTrue(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, self.world.turn_index), (5, 2))

    def test_empty_demo_never_invents_a_stage_clear(self) -> None:
        self.finish_shot()
        self.assertFalse(self.world.check_stage_end())
        self.assertTrue(self.world.resolve_turn())
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        self.assertEqual((self.world.stage, self.world.turn_index), (1, 2))

    def test_stage_check_observes_settled_combat_and_runs_before_enemy_actions(self) -> None:
        self.add_enemy(1, 5, 3, EnemyType.BOMB)
        self.add_enemy(2, 6, 3, EnemyType.BOMB)
        survivor = self.add_enemy(3, 0, 5)
        self.world.combat.add_crystal(Crystal(4, 0, 6))
        self.world.combat.apply_damage(1, 5)
        self.world.combat.handle_hit(HitEvent(1, 4, 0, (120, 384), (1, 0)))
        self.finish_shot()

        def stage_check():
            self.assertFalse(self.world.combat.pending_deaths)
            self.assertEqual(self.world.pending_bp, 0)
            self.assertEqual(self.world.bp, 2)
            self.assertEqual([event.enemy_id for event in self.world.combat.death_events], [1, 2])
            self.assertEqual((survivor.grid_col, survivor.turns_alive), (0, 0))
            return False

        with patch.object(self.world, "check_stage_end", side_effect=stage_check) as check:
            self.world.resolve_turn()
            check.assert_called_once_with()
        self.assertEqual(survivor.grid_col, 1)

    def test_stage_end_claim_completes_action_before_enemy_phase(self) -> None:
        self.world = World(encounter=EncounterDefinition(1, (Wave(1, (Spawn(1, "basic", 4, 3),)),)))
        self.world.start_new_run()
        self.world.transition_to(GameState.PLAYER_AIM)
        enemy = self.world.enemies[1]
        self.finish_shot()
        with patch.object(self.world, "check_stage_end", return_value=True):
            self.assertTrue(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, self.world.turn_index), (4, 1))
        self.assertIs(self.world.state, GameState.STAGE_CLEAR)
        self.assertFalse(self.world.resolve_turn())
        self.assertIsNone(self.world._pending_turn)

    def test_new_run_restores_hp_entities_action_history_and_pending_state(self) -> None:
        world = World(demo=True)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.enemies[1].advance_one_cell()
        world.enemies[2].grid_col = 13
        world.enemies[2].escape(1)
        world.apply_player_damage(100)
        world.start_new_run()
        expected = World(demo=True)
        expected.start_new_run()
        self.assertEqual(vars(world), vars(expected))
        self.assertEqual((world.hp, world.max_hp, world.mp, world.bp), (100, 100, 100, 1))


if __name__ == "__main__":
    unittest.main()
