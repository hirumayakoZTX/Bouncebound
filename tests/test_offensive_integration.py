"""Offensive model effects remain separate from playable input and turn claiming."""

from copy import deepcopy
import os
import unittest

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame

from src.constants import LOGICAL_SIZE
from src.encounter import EncounterDefinition, EncounterOutcome, Spawn, Wave
from src.game import Game
from src.renderer import Renderer
from src.spells import SpellFailure
from src.states import GameState
from src.world import World


class OffensiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.game.running = True
        self.game.world.start_new_run()
        self.game.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self):
        pygame.quit()

    def shoot(self, row):
        world = self.game.world
        key = pygame.K_DOWN if row > world.player_row else pygame.K_UP
        for _ in range(abs(row - world.player_row)):
            self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
        self.game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                                pos=(96, 96 + 48 * row)))
        self.assertIs(world.state, GameState.SHOT_ANIMATION)
        for _ in range(20):
            world.advance_time(.25)
        self.assertIs(world.state, GameState.TURN_RESOLVE)
        self.assertTrue(world.resolve_turn())

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

    def test_rendering_after_damage_and_chains_never_mutates_or_reexecutes_effects(self):
        world = self.game.world
        result = world.execute_offensive_spell('model-fire', 'fire')
        self.assertEqual(len(result.effects.deaths), 6)
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        for paused in (False, True):
            if paused:
                world.pause()
            before = deepcopy(vars(world))
            for _ in range(10):
                renderer.draw(screen, world.snapshot())
            self.assertEqual(vars(world), before)
            self.assertEqual(world.mp, 70)
        self.assertEqual(len(world.combat.death_events), 6)

    def test_execution_is_rejected_during_flight_and_pause_without_touching_projectiles(self):
        world = self.game.world
        self.game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96,240)))
        world.advance_time(.01)
        for paused in (False, True):
            if paused:
                world.pause()
            before = deepcopy(vars(world))
            result = world.execute_offensive_spell('blocked', 'fire')
            self.assertIs(result.failure, SpellFailure.INVALID_STATE)
            self.assertIsNone(result.effects)
            self.assertEqual(vars(world), before)

    def test_spell_cleared_board_still_waits_for_shooting_turns_and_future_waves(self):
        world = self.game.world
        # This is an explicit model call, not a player-facing casting control.
        result = world.execute_offensive_spell('model-fire', 'fire')
        self.assertTrue(result.valid)
        self.assertEqual(world.snapshot().enemies, ())
        self.assertEqual(world.encounter.spawned_waves, {0})
        self.assertFalse(world.crystals[7].collected)
        self.assertEqual((world.turn_index, world.bp, world.pending_bp), (1,1,0))
        self.assertIsNone(world._pending_turn)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertFalse(world.resolve_turn())
        self.shoot(3)
        self.assertEqual((world.turn_index, world.bp, world.mp), (2,2,70))
        self.assertEqual(world.encounter.spawned_waves, {0})
        self.assertEqual(world.snapshot().enemies, ())
        self.shoot(3)
        self.assertEqual(world.turn_index, 3)
        self.assertEqual(world.encounter.spawned_waves, {0,1})
        self.assertEqual([e.enemy_id for e in world.snapshot().enemies], list(range(8,14)))
        self.assertTrue(all(e.turns_alive == 0 for e in world.enemies.values() if e.active))

    def test_final_model_spell_kill_does_not_activate_stage_or_turn_integration(self):
        config = EncounterDefinition(1, (Wave(1, (Spawn(1, "basic", 6, 3),)),))
        world = World(encounter=config)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        result = world.execute_offensive_spell("final-model-hit", "fire")
        self.assertTrue(result.valid)
        self.assertIs(world.encounter.outcome(world.combat), EncounterOutcome.CLEARED)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertIsNone(world._pending_turn)
        self.assertFalse(world.resolve_turn())
        self.assertEqual((world.turn_index, world.mp), (1, 70))

    def test_offensive_history_is_cleared_by_stage_clear_restart(self):
        world = self.game.world
        self.assertTrue(world.execute_offensive_spell('reusable', 'fire').valid)
        for row in (3,3,2,2,4,4,3):
            self.shoot(row)
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual((world.hp, world.mp, world.bp), (100,70,5))
        self.assertEqual(len(world.combat.death_events), 24)
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.hp, world.mp, world.bp, world.turn_index), (100,100,1,1))
        self.assertFalse(world.spells.cooldowns)
        self.assertFalse(world.combat.death_events)
        self.game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertTrue(world.execute_offensive_spell('reusable', 'fire').valid)
        self.assertEqual(len(world.combat.death_events), 6)
        self.assertEqual(world.mp, 70)


if __name__ == '__main__':
    unittest.main()
