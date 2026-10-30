"""Current-stage retry, campaign restart, and their input/presentation boundaries."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import os
import unittest
from unittest.mock import call, patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame

from src.game import Game
from src.renderer import Renderer
from src.screens import ScreenRenderer
from src.spells import SpellFailure
from src.states import GameOverReason, GameState
from src.statuses import StatusKind
from src.stage_config import parse_stage
from src.world import World
from test_stage_config import stage_data


def fixture_registry(*, stage_two_spawn_col: int = 0):
    data = {stage: stage_data(stage) for stage in (1, 2, 3)}
    data[2]['waves'][0]['spawns'][0]['col'] = stage_two_spawn_col
    data[3]['completion']['mandatory_enemy_ids'].append(3)
    data[3]['boss_wave'] = {
        'when': 'after_scripted_waves_cleared',
        'spawns': [{'id': 3, 'kind': 'odin', 'col': 0, 'row': 5}],
    }
    return {stage: parse_stage(value) for stage, value in data.items()}


class StageRetryTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.game = Game()
        self.game.world = World(stages=fixture_registry())
        self.game.running = True

    def tearDown(self):
        pygame.quit()

    @property
    def world(self):
        return self.game.world

    def key(self, value, *, repeat=False):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value, repeat=repeat))
        for event in pygame.event.get():
            self.game.handle_event(event)

    def start(self):
        self.key(pygame.K_RETURN)
        self.assertIs(self.world.state, GameState.STAGE_INTRO)
        self.key(pygame.K_RETURN)
        self.assertIs(self.world.state, GameState.PLAYER_AIM)

    def clear_fixture_stage(self):
        """Use a valid Fire action and the ordinary action resolver."""
        self.assertTrue(self.world.select_spell('fire'))
        self.assertTrue(self.world.cast_selected_spell().valid)
        self.world.advance_time(.45)
        self.assertTrue(self.world.resolve_turn())
        self.assertIs(self.world.state, GameState.STAGE_CLEAR)

    def advance_to_stage(self, target):
        self.start()
        for expected_stage in range(2, target + 1):
            self.clear_fixture_stage()
            self.key(pygame.K_RETURN)
            self.assertIs(self.world.state, GameState.STAGE_INTRO)
            self.assertEqual(self.world.stage, expected_stage)
            self.key(pygame.K_RETURN)
            self.assertIs(self.world.state, GameState.PLAYER_AIM)

    def test_stage_two_retry_after_consumed_reraise_resets_full_attempt(self):
        self.advance_to_stage(2)
        world = self.world
        old_encounter, old_combat = world.encounter, world.combat
        self.assertTrue(world.commit_spell('retry-fire-history', 'fire').valid)
        self.assertTrue(world.execute_support_spell('retry-reraise-grant', 'reraise').valid)
        self.assertTrue(world.reraise_used)
        for status in (StatusKind.POISON, StatusKind.BIND, StatusKind.DOOM,
                       StatusKind.WARD, StatusKind.LEVITATION):
            world.apply_status(status)
        world.place_poison_tile(3)
        world.bp = 4
        world.player_row = 5
        world.set_aim_target((96, 336))
        world._physics.accumulator = .009

        # Exercise the actual unified knockout and revival path before the final defeat.
        world.force_player_knockout(source='doom')
        self.assertEqual(world.hp, 50)
        self.assertFalse(world.statuses.is_active(StatusKind.RERAISE, world.turn_index))
        self.assertTrue(world.reraise_used)
        world.set_aim_target((96, 336))
        self.assertTrue(world.fire())
        old_projectiles = tuple(world.projectiles)
        self.assertTrue(old_projectiles)
        world.force_player_knockout(source='doom')
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertTrue(world.projectiles)  # A terminal transition can retain presentation input.

        epoch = self.game._presentation_epoch
        self.key(pygame.K_t, repeat=True)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual(self.game._presentation_epoch, epoch)
        self.key(pygame.K_t)

        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp),
                         (2, 1, 100, 100, 1))
        self.assertEqual(world.player_row, 3)
        self.assertIsNone(world.aim_target)
        self.assertEqual(world.projectiles, [])
        self.assertIsNone(world._pending_action)
        self.assertEqual(world._physics.accumulator, 0)
        self.assertEqual(world._spell_remaining, 0)
        self.assertEqual(world._next_projectile_id, 1)
        self.assertEqual(world._next_action_id, 1)
        self.assertIsNone(world.selected_spell)
        self.assertEqual(world.spell_feedback, '')
        self.assertIsNone(world.last_spell_result)
        self.assertEqual(world.statuses.snapshot(), ())
        self.assertEqual(world.status_events, ())
        self.assertEqual(world.hazards.snapshot(), ())
        self.assertFalse(world.reraise_used)
        self.assertEqual(dict(world.spells.cooldowns), {})
        self.assertEqual(world.spells._committed_actions, {})
        self.assertEqual(world.combat.death_events, [])
        self.assertEqual(world.combat.observations, ())
        self.assertEqual(world.enemies, {})
        self.assertEqual(world.crystals, {})
        self.assertEqual(world.pending_bp, 0)
        self.assertEqual(world.encounter.spawn_history, [])
        self.assertEqual(world.encounter.spawned_waves, set())
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertIsNot(world.encounter, old_encounter)
        self.assertIsNot(world.combat, old_combat)
        self.assertFalse(world.can_retry_current_stage)
        self.assertEqual(self.game._presentation_epoch, epoch + 1)

        # Repeated T cannot leave the intro; Enter is still required for Wave 1.
        snapshot = world.snapshot()
        with self.assertRaises(FrozenInstanceError):
            snapshot.retry_stage_available = True
        self.key(pygame.K_t)
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual(world.encounter.spawn_history, [])
        self.key(pygame.K_RETURN)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual(world.encounter.spawn_history, [1, 2])
        self.assertTrue(world.validate_spell('esuna').valid)
        self.assertTrue(world.validate_spell('levitation').valid)
        self.assertIs(world.validate_spell('meteor').failure, SpellFailure.STAGE_LOCKED)

    def test_stage_three_retry_after_doom_starts_clean_stage_three_not_victory(self):
        self.advance_to_stage(3)
        world = self.world
        self.assertEqual(world.stage, 3)
        # Clear the scripted enemy through a valid spell action so Odin really spawns.
        self.assertTrue(world.select_spell('fire'))
        self.assertTrue(world.cast_selected_spell().valid)
        world.advance_time(.45)
        self.assertTrue(world.resolve_turn())
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertTrue(world.encounter.boss_wave_spawned)
        self.assertEqual([enemy.enemy_type.value for enemy in world.enemies.values()
                          if enemy.active], ['odin'])
        world.apply_status(StatusKind.DOOM, 1)
        world.place_poison_tile(3)
        world.bp = 5
        world.mp = 17
        old_encounter, old_combat = world.encounter, world.combat
        world.force_player_knockout(source='doom')
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual(world.hp, 0)
        self.assertIs(world.game_over_reason, GameOverReason.HP_DEPLETED)
        failed_snapshot = world.snapshot()
        self.assertTrue(failed_snapshot.retry_stage_available)
        screen_renderer = ScreenRenderer()
        with patch.object(screen_renderer, '_text', wraps=screen_renderer._text) as text:
            screen_renderer.terminal(pygame.Surface((960, 576)), failed_snapshot)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn('T: Retry Stage 3', labels)
        self.assertIn('R: Restart Campaign', labels)

        self.key(pygame.K_t)
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp),
                         (3, 1, 100, 100, 1))
        self.assertEqual(world.enemies, {})
        self.assertEqual(world.crystals, {})
        self.assertEqual(world.encounter.spawn_history, [])
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertIsNot(world.encounter, old_encounter)
        self.assertIsNot(world.combat, old_combat)
        self.assertEqual(world.status_events, ())
        self.assertEqual(world.statuses.snapshot(), ())
        self.assertEqual(world.hazards.snapshot(), ())
        self.assertIsNone(world.game_over_reason)
        self.assertIsNone(world._cleared_stage)
        self.key(pygame.K_RETURN)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual(world.encounter.spawn_history, [1, 2])
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertEqual([enemy.enemy_type.value for enemy in world.enemies.values()
                          if enemy.active], ['basic'])
        self.assertTrue(world.validate_spell('meteor').valid)
        self.assertTrue(world.validate_spell('esuna').valid)

    def test_stage_three_r_campaign_key_still_returns_to_stage_one(self):
        self.advance_to_stage(3)
        world = self.world
        world.force_player_knockout(source='odin_execute')
        self.assertIs(world.state, GameState.GAME_OVER)
        self.key(pygame.K_r)
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp),
                         (1, 1, 100, 100, 1))
        self.assertEqual(world.encounter.definition, world.stage_definitions[1])
        self.assertEqual(world.encounter.spawn_history, [])
        self.assertEqual(world.enemies, {})
        self.assertEqual(world.crystals, {})
        self.key(pygame.K_RETURN)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertIs(world.validate_spell('meteor').failure, SpellFailure.STAGE_LOCKED)

    def test_retry_is_unavailable_for_stage_one_and_outside_game_over(self):
        world = self.world
        before = deepcopy(vars(world))
        self.assertFalse(world.retry_current_stage())
        self.assertEqual(vars(world), before)
        self.start()
        for state in (GameState.PLAYER_AIM, GameState.PAUSED):
            if state is GameState.PAUSED:
                world.pause()
            before = deepcopy(vars(world))
            self.assertFalse(world.retry_current_stage())
            self.key(pygame.K_t)
            self.assertEqual(vars(world), before)
            if state is GameState.PAUSED:
                world.resume()

        world.apply_player_damage(world.hp, source='fixture_attack')
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertFalse(world.can_retry_current_stage)
        before = deepcopy(vars(world))
        self.key(pygame.K_t)
        self.assertEqual(vars(world), before)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.key(pygame.K_r)
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual(world.stage, 1)

    def test_stage_two_retry_after_defense_failure_keeps_failure_semantics(self):
        self.game.world = World(stages=fixture_registry(stage_two_spawn_col=13))
        self.advance_to_stage(2)
        world = self.world
        self.assertTrue(world.select_spell('ward'))
        self.assertTrue(world.cast_selected_spell().valid)
        world.advance_time(.45)
        self.assertTrue(world.resolve_turn())
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual(world.hp, 100)
        self.assertIs(world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertTrue(world.can_retry_current_stage)
        self.key(pygame.K_t)
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp),
                         (2, 1, 100, 100, 1))

    def test_retry_epoch_clears_old_defeat_visuals_without_replaying_them(self):
        self.advance_to_stage(2)
        world = self.world
        world.apply_player_damage(world.hp, source='fixture_attack')
        self.assertIs(world.state, GameState.GAME_OVER)
        renderer = Renderer()
        renderer.update_feedback(world.snapshot(), 0, epoch=self.game._presentation_epoch)
        self.assertTrue(any(effect.kind == 'defeat' for effect in renderer.feedback.effects))
        self.key(pygame.K_t)
        renderer.update_feedback(world.snapshot(), 0, epoch=self.game._presentation_epoch)
        self.assertFalse(renderer.feedback.effects)
        self.assertFalse(renderer.feedback.last_events)

    def test_game_over_retry_controls_are_stage_specific_and_rendering_is_read_only(self):
        self.advance_to_stage(2)
        world = self.world
        world.apply_player_damage(world.hp, source='fixture_attack')
        snapshot = world.snapshot()
        self.assertTrue(snapshot.retry_stage_available)
        renderer = Renderer()
        labels = []
        before = deepcopy(vars(world))
        with patch.object(renderer.screens, '_text', wraps=renderer.screens._text) as text:
            renderer.draw(pygame.Surface((960, 576)), snapshot)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertIn('T: Retry Stage 2', labels)
        self.assertIn('Restart this stage from Wave 1', labels)
        self.assertIn('R: Restart Campaign', labels)
        self.assertIn(GameOverReason.HP_DEPLETED.value, labels)
        self.assertEqual(vars(world), before)

        screen_renderer = ScreenRenderer()
        stage_one = replace(snapshot, stage=1, retry_stage_available=False)
        with patch.object(screen_renderer, '_text', wraps=screen_renderer._text) as text:
            screen_renderer.terminal(pygame.Surface((960, 576)), stage_one)
        labels = [call.args[1] for call in text.call_args_list]
        self.assertNotIn('T: Retry Stage 1', labels)
        self.assertIn('R: Restart Run', labels)
        self.assertNotIn('R: Restart Campaign', labels)

    def test_retry_and_fresh_stage_action_are_frame_schedule_invariant(self):
        signatures = []
        schedules = ((1 / 30,), (1 / 60,), (1 / 144,), (.013, .041, .008, .027))
        for schedule in schedules:
            with self.subTest(schedule=schedule):
                game = Game()
                game.world = World(stages=fixture_registry())
                game.running = True

                def post_key(value):
                    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value, repeat=False))
                    for event in pygame.event.get():
                        game.handle_event(event)

                def fire_and_resolve():
                    world = game.world
                    self.assertTrue(world.select_spell('fire'))
                    self.assertTrue(world.cast_selected_spell().valid)
                    frame = 0
                    while world.state is GameState.SPELL_ANIMATION:
                        world.advance_time(schedule[frame % len(schedule)])
                        frame += 1
                        self.assertLess(frame, 256)
                    self.assertIs(world.state, GameState.TURN_RESOLVE)
                    self.assertTrue(world.resolve_turn())

                post_key(pygame.K_RETURN); post_key(pygame.K_RETURN)
                fire_and_resolve()
                self.assertIs(game.world.state, GameState.STAGE_CLEAR)
                post_key(pygame.K_RETURN); post_key(pygame.K_RETURN)
                self.assertEqual((game.world.stage, game.world.state), (2, GameState.PLAYER_AIM))

                game.world.apply_player_damage(game.world.hp, source='fixture_attack')
                self.assertIs(game.world.state, GameState.GAME_OVER)
                post_key(pygame.K_t); post_key(pygame.K_RETURN)
                self.assertEqual((game.world.stage, game.world.state), (2, GameState.PLAYER_AIM))
                self.assertEqual((game.world.turn_index, game.world.hp, game.world.mp, game.world.bp),
                                 (1, 100, 100, 1))
                fire_and_resolve()
                self.assertIs(game.world.state, GameState.STAGE_CLEAR)
                self.assertEqual((game.world.stage, game.world.turn_index, game.world.mp), (2, 1, 70))
                signatures.append(game.world.snapshot())

        self.assertTrue(all(signature == signatures[0] for signature in signatures[1:]))


if __name__ == '__main__':
    unittest.main()
