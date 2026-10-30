"""Spell foundation boundaries: core input, rendering, shooting, and restart."""

from copy import deepcopy
import os
import unittest

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame

from src.constants import LOGICAL_SIZE
from src.entities import Enemy, EnemyType
from src.game import Game
from prototype_fixtures import prototype_game
from src.renderer import Renderer
from src.spells import SpellFailure
from src.states import GameState
from src.world import World


class SpellIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = prototype_game()
        self.game.running = True
        self.game.world.start_new_run()
        self.game.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self) -> None:
        pygame.quit()

    def test_spell_selection_is_free_and_space_uses_the_shared_cast_pipeline(self):
        world = self.game.world
        before = deepcopy(world.combat)
        for key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5,
                    pygame.K_6, pygame.K_7, pygame.K_8):
            self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
        self.assertEqual(world.combat, before)
        self.assertEqual((world.mp, world.turn_index), (100, 1))
        self.assertEqual(dict(world.spells.cooldowns), {})
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        self.assertIs(world.state, GameState.SPELL_ANIMATION)
        self.assertEqual((world.mp, world.turn_index), (50, 1))
        self.assertTrue(world.reraise_used)

    def test_validation_and_commit_do_not_execute_combat_enemy_phases_or_animation(self) -> None:
        world = self.game.world
        combat_before = deepcopy(world.combat)
        self.assertTrue(world.validate_spell('fire').valid)
        self.assertTrue(world.commit_spell('foundation-only', 'fire').valid)
        self.assertEqual(world.combat, combat_before)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual((world.mp, world.hp, world.bp, world.turn_index), (70, 100, 1, 1))
        self.assertIsNone(world.last_resolved_turn)
        self.assertFalse(world.resolve_turn())
        self.assertEqual(world.projectiles, [])

    def test_renderer_does_not_modify_cooldowns_or_make_committed_spells_tick(self) -> None:
        world = self.game.world
        world.commit_spell('record', 'fire')
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        for paused in (False, True):
            if paused:
                world.pause()
            before = deepcopy(vars(world))
            for _ in range(30):
                renderer.draw(screen, world.snapshot())
            self.assertEqual(vars(world), before)
            self.assertEqual(world.spells.next_ready_turn('fire'), 5)
            self.assertEqual(world.mp, 70)

    def test_shooting_preserves_spell_history_and_uses_the_existing_turn_clock(self) -> None:
        world = World(demo=False)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 0, 3))
        self.assertTrue(world.commit_spell('first-fire', 'fire').valid)
        self.assertEqual(world.enemies[1].hp, 5)
        # Miss from the top row so this target survives all four ordinary turns.
        for turn in (1, 2, 3, 4):
            self.assertEqual(world.turn_index, turn)
            while world.player_row:
                world.move_player(-1)
            world.set_aim_target((96, 96))
            self.assertTrue(world.fire())
            self.assertEqual(len(world.projectiles), 1)
            for _ in range(20):
                world.advance_time(.25)
            self.assertTrue(world.resolve_turn())
            self.assertEqual(world.mp, 70)
            self.assertEqual(world.spells.next_ready_turn('fire'), 5)
        self.assertEqual(world.turn_index, 5)
        for _ in range(3):
            world.move_player(1)
        self.assertTrue(world.validate_spell('fire').valid)
        self.assertEqual(world.enemies[1].grid_col, 4)
        self.assertEqual(world.enemies[1].turns_alive, 4)
        self.assertEqual((world.hp, world.bp), (100, 1))

    def test_pending_turn_remains_restricted_after_orbs_expire_until_resolved(self) -> None:
        world = self.game.world
        self.game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 240)))
        for _ in range(20):
            world.advance_time(.25)
        self.assertIs(world.state, GameState.TURN_RESOLVE)
        before = deepcopy(vars(world))
        self.assertIs(world.commit_spell('blocked', 'ward').failure, SpellFailure.INVALID_STATE)
        self.assertEqual(vars(world), before)
        world.resolve_turn()
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertTrue(world.validate_spell('ward').valid)

    def test_stage_clear_restart_clears_model_only_payment_history(self) -> None:
        world = self.game.world
        self.assertTrue(world.commit_spell("model-only", "ward").valid)
        for row in (3, 3, 2, 2, 4, 3):
            while world.player_row != row:
                world.move_player(1 if world.player_row < row else -1)
            world.set_aim_target((96, 96 + 48 * row))
            world.fire()
            for _ in range(20):
                world.advance_time(.25)
            world.resolve_turn()
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual((world.hp, world.mp, world.bp), (100, 70, 5))
        self.assertEqual(world.spells.next_ready_turn("ward"), 5)
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.hp, world.mp, world.bp, world.turn_index), (100, 100, 1, 1))
        self.assertEqual(dict(world.spells.cooldowns), {})
        world.transition_to(GameState.PLAYER_AIM)
        self.assertTrue(world.commit_spell("model-only", "ward").valid)
        self.assertEqual(world.mp, 70)


if __name__ == '__main__':
    unittest.main()
