"""Prototype end screens, input eligibility, and complete application restarts."""

from copy import deepcopy
import os
import unittest
from unittest.mock import Mock, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from src.constants import LOGICAL_SIZE
from src.game import Game
from src.renderer import Renderer
from src.states import GameOverReason, GameState
from src.world import World
from test_scenes import world_in_state


class EncounterIntegrationTests(unittest.TestCase):
    def tearDown(self):
        pygame.quit()

    def key(self, value, **extra):
        return pygame.event.Event(pygame.KEYDOWN, key=value, **extra)

    def test_r_restarts_only_game_over_and_stage_clear_and_ignores_repeat(self):
        for state in GameState:
            with self.subTest(state=state):
                game = Game()
                game.running = True
                game.world = world_in_state(state)
                game.world.hp, game.world.mp, game.world.bp = 17, 9, 4
                before = deepcopy(vars(game.world))
                game.handle_event(self.key(pygame.K_r, repeat=True))
                self.assertEqual(vars(game.world), before)
                game.handle_event(self.key(pygame.K_r))
                if state in (GameState.GAME_OVER, GameState.STAGE_CLEAR):
                    expected = World()
                    expected.start_new_run()
                    self.assertEqual(vars(game.world), vars(expected))
                else:
                    self.assertEqual(vars(game.world), before)

    def test_end_screens_include_outcome_resources_and_restart_and_are_read_only(self):
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        for state, reason, text in (
            (GameState.STAGE_CLEAR, None, "Prototype encounter complete"),
            (GameState.GAME_OVER, GameOverReason.HP_DEPLETED, "Player HP depleted"),
            (GameState.GAME_OVER, GameOverReason.DEFENSE_FAILED,
             "Defense failed: a required enemy escaped"),
        ):
            with self.subTest(state=state, reason=reason):
                world = world_in_state(state)
                world.game_over_reason = reason
                world.hp = 0 if reason is GameOverReason.HP_DEPLETED else 90
                before = deepcopy(vars(world))
                with patch.object(renderer, "_center_text", wraps=renderer._center_text) as draw:
                    for _ in range(3):
                        renderer.draw(screen, world.snapshot())
                labels = [call.args[1] for call in draw.call_args_list]
                self.assertIn("Stage Clear" if state is GameState.STAGE_CLEAR else "Game Over", labels)
                self.assertIn(text, labels)
                self.assertIn("Press R to Restart", labels)
                self.assertIn("Stage 1 | Turn 1", labels)
                self.assertTrue(any(f"HP {world.hp}/100" in label and "BP 1" in label
                                    for label in labels))
                self.assertEqual(vars(world), before)

    def test_rendering_never_spawns_future_waves_or_claims_pending_actions(self):
        world = World()
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.turn_index = 7
        pygame.display.init()
        pygame.font.init()
        renderer = Renderer()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        before = deepcopy(vars(world))
        for _ in range(5):
            renderer.draw(screen, world.snapshot())
        self.assertEqual(vars(world), before)
        self.assertEqual(world.encounter.spawned_waves, {0})

    def test_pause_freezes_wave_schedule_and_pending_turn_then_resumes_once(self):
        game = Game()
        game.running = True
        game.world.start_new_run()
        game.world.transition_to(GameState.PLAYER_AIM)
        game.world.player_row = 0
        game.world.set_aim_target((96, 96))
        game.world.fire()
        game.world.advance_time(.004)
        game.handle_event(self.key(pygame.K_ESCAPE))
        before = deepcopy(vars(game.world))
        game.handle_event(self.key(pygame.K_r))
        game.handle_event(self.key(pygame.K_w))
        game.world.advance_time(1000)
        self.assertFalse(game.world.resolve_turn())
        self.assertEqual(game.world.spawn_waves(), ())
        self.assertEqual(vars(game.world), before)
        game.handle_event(self.key(pygame.K_ESCAPE))
        for _ in range(20):
            game.world.advance_time(.25)
        game.world.resolve_turn()
        self.assertEqual(game.world.turn_index, 2)
        self.assertEqual(game.world.encounter.spawned_waves, {0})
        self.assertFalse(game.world.resolve_turn())

    def test_application_can_win_restart_lose_and_restart_without_process_restart(self):
        game = Game()
        clock = Mock()
        clock.tick.return_value = 250
        original_draw = Renderer.draw
        fired = set()
        cycle = 0
        frames = 0
        saw_later_wave = False
        outcomes = []
        intro_snapshots = []

        def post_key(value):
            pygame.event.post(self.key(value))

        def drive(renderer, screen, snapshot):
            nonlocal cycle, frames, saw_later_wave
            frames += 1
            self.assertLess(frames, 1000, "Application smoke sequence did not finish")
            original_draw(renderer, screen, snapshot)
            if snapshot.state is GameState.MENU:
                post_key(pygame.K_RETURN)
            elif snapshot.state is GameState.STAGE_INTRO:
                intro_snapshots.append(snapshot)
                if cycle == 2:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                else:
                    post_key(pygame.K_RETURN)
            elif snapshot.state is GameState.PLAYER_AIM:
                saw_later_wave |= snapshot.spawned_waves >= 2
                if (cycle, snapshot.turn_index) not in fired:
                    row = ({1: 3, 2: 3, 3: 2, 4: 2, 5: 4, 6: 4}.get(snapshot.turn_index, 3)
                           if cycle == 0 else 0)
                    step = pygame.K_s if row > snapshot.player_row else pygame.K_w
                    for _ in range(abs(row - snapshot.player_row)):
                        post_key(step)
                    pygame.event.post(pygame.event.Event(
                        pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 96 + 48 * row)
                    ))
                    fired.add((cycle, snapshot.turn_index))
            elif snapshot.state in (GameState.STAGE_CLEAR, GameState.GAME_OVER):
                outcomes.append(snapshot)
                cycle += 1
                post_key(pygame.K_r)

        with patch("src.game.pygame.time.Clock", return_value=clock), patch.object(
            Renderer, "draw", autospec=True, side_effect=drive
        ):
            game.run()
        self.assertTrue(saw_later_wave)
        self.assertEqual([s.state for s in outcomes], [GameState.STAGE_CLEAR, GameState.GAME_OVER])
        self.assertEqual(outcomes[0].hp, 100)
        self.assertEqual(outcomes[0].bp, 5)
        self.assertIs(outcomes[1].game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertEqual(len(intro_snapshots), 3)
        self.assertTrue(all(s.hp == s.mp == 100 and s.bp == s.turn_index == 1
                            and not s.projectiles and not s.enemies and not s.crystals
                            and s.spawned_waves == 0 and s.aim_target is None
                            for s in intro_snapshots))
        self.assertFalse(game.running)
        self.assertFalse(pygame.display.get_init())


if __name__ == "__main__":
    unittest.main()
