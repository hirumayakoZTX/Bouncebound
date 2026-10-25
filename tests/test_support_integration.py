"""Model-applied support/status data integrates with the projectile-only controls."""

from copy import deepcopy
import os
import unittest

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame

from src.constants import LOGICAL_SIZE
from src.game import Game
from src.renderer import Renderer
from src.spells import SpellFailure
from src.states import GameState
from src.statuses import StatusEffect, StatusKind


class SupportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.game.running = True
        self.game.world.start_new_run()
        self.game.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self):
        pygame.quit()

    def populate_model_statuses(self):
        world = self.game.world
        world.statuses.put(StatusEffect(StatusKind.POISON,2,1,'fixture'))
        world.statuses.put(StatusEffect(StatusKind.BIND,1,1,'fixture'))
        world.statuses.put(StatusEffect(StatusKind.DOOM,5,1,'fixture'))
        # Temporary unlock context for model-only grants; no stage transition is executed.
        world.stage = 2
        for spell in ('ward','levitation','reraise'):
            self.assertTrue(world.execute_support_spell(spell,spell).valid)
        world.stage = 1
        self.assertEqual(world.turn_index,1)

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

    def test_renderer_and_pause_preserve_all_status_data_and_encounter_history(self):
        self.populate_model_statuses()
        world = self.game.world
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        for paused in (False,True):
            if paused:
                self.game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE))
            before = deepcopy(vars(world))
            for _ in range(20):
                renderer.draw(screen,world.snapshot())
                world.advance_time(1000)
            self.assertEqual(vars(world),before)
        self.assertTrue(world.snapshot().reraise_used)
        self.assertEqual(len(world.snapshot().statuses),6)

    def test_statuses_process_on_shooting_turns_and_restart_clears_history(self):
        self.populate_model_statuses()
        world = self.game.world
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_UP))
        self.assertEqual(world.player_row,3)  # Bind applies through the next input interval.
        for row in (3,3,2,2,4,4,3):
            key = pygame.K_DOWN if row>world.player_row else pygame.K_UP
            for _ in range(abs(row-world.player_row)):
                self.game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=key))
            self.game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,
                                                    pos=(96,96+48*row)))
            self.assertIs(world.state,GameState.SHOT_ANIMATION)
            for _ in range(20):
                world.advance_time(.25)
            self.assertTrue(world.resolve_turn())
            self.assertTrue(world.reraise_used)
        self.assertIs(world.state,GameState.STAGE_CLEAR)
        self.assertEqual((world.turn_index,world.hp,world.mp,world.bp),(7,50,0,5))
        self.assertEqual(world.statuses.snapshot(),())
        self.assertEqual(len(world.combat.death_events),24)
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_r))
        self.assertIs(world.state,GameState.STAGE_INTRO)
        self.assertEqual(world.statuses.snapshot(),())
        self.assertFalse(world.reraise_used)
        self.assertEqual(dict(world.spells.cooldowns),{})
        self.assertEqual((world.hp,world.mp,world.bp),(100,100,1))
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertTrue(world.execute_support_spell('reraise','reraise').valid)
        self.assertEqual(world.mp,50)

    def test_support_execution_during_flight_is_rejected_without_partial_changes(self):
        world = self.game.world
        world.execute_support_spell('ward','ward')
        self.game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(96,240)))
        for paused in (False,True):
            if paused:
                world.pause()
            before = deepcopy(vars(world))
            result = world.execute_support_spell('blocked','reraise')
            self.assertIs(result.failure,SpellFailure.INVALID_STATE)
            self.assertEqual(vars(world),before)
        self.assertFalse(world.reraise_used)
        self.assertIsNone(world.statuses.get(StatusKind.RERAISE))

    def test_combined_grants_intercept_once_and_restart_clears_them(self):
        self.populate_model_statuses()
        world = self.game.world
        self.assertEqual(world.apply_player_damage(5),0)
        self.assertEqual(world.hp,100)
        self.assertIsNone(world.statuses.get(StatusKind.WARD))
        world.apply_player_damage(1000)
        self.assertEqual(world.hp,50)
        self.assertIs(world.state,GameState.PLAYER_AIM)
        world.apply_player_damage(1000)
        self.assertIs(world.state,GameState.GAME_OVER)
        self.assertEqual(world.hp,0)
        self.assertIsNone(world.statuses.get(StatusKind.WARD))
        self.assertIsNone(world.statuses.get(StatusKind.RERAISE))
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_r))
        self.assertIs(world.state,GameState.STAGE_INTRO)
        self.assertEqual(world.statuses.snapshot(),())
        self.assertFalse(world.reraise_used)
        self.assertEqual(dict(world.spells.cooldowns),{})
        self.assertEqual((world.hp,world.mp,world.bp),(100,100,1))


if __name__ == '__main__':
    unittest.main()
