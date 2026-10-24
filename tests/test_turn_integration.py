"""Application-loop and read-only rendering checks for complete turns."""

from copy import deepcopy
import os
import unittest
from unittest.mock import Mock, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from src.constants import LOGICAL_SIZE, PHYSICS_STEP
from src.entities import Crystal, Enemy, EnemyType
from src.game import Game
from src.renderer import Renderer
from src.states import GameState
from src.turns import resolve_enemy_phase
from src.world import World


class TurnIntegrationTests(unittest.TestCase):
    def tearDown(self) -> None:
        pygame.quit()

    def key(self, key: int):
        return pygame.event.Event(pygame.KEYDOWN, key=key)

    def click(self):
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 96))

    def test_application_loop_completes_three_real_shots_without_extra_phases(self) -> None:
        game = Game()
        events = [[self.key(pygame.K_RETURN)], [self.key(pygame.K_RETURN)],
                  [self.key(pygame.K_w)] * 3]
        for _ in range(3):
            events.append([self.click()])
            events.extend([[] for _ in range(23)])
        events.append([pygame.event.Event(pygame.QUIT)])
        clock = Mock()
        clock.tick.return_value = 250
        snapshots = []
        draw = Renderer.draw

        def observe(renderer, screen, snapshot):
            snapshots.append(snapshot)
            draw(renderer, screen, snapshot)

        with patch("src.game.pygame.event.get", side_effect=events), patch(
            "src.game.pygame.time.Clock", return_value=clock
        ), patch.object(Renderer, "draw", autospec=True, side_effect=observe), patch(
            "src.world.resolve_enemy_phase", wraps=resolve_enemy_phase
        ) as phase:
            game.run()
        self.assertEqual(phase.call_count, 3)
        self.assertEqual(sum(s.state is GameState.TURN_RESOLVE for s in snapshots), 3)
        self.assertEqual((game.world.turn_index, game.world.last_resolved_turn), (4, 3))
        self.assertEqual([game.world.enemies[index].grid_col for index in (1, 2, 3)], [9, 12, 11])
        self.assertTrue(all(enemy.turns_alive == 3 for enemy in game.world.enemies.values()))
        self.assertEqual((game.world.hp, game.world.mp, game.world.bp), (100, 100, 1))
        self.assertIs(game.world.state, GameState.PLAYER_AIM)
        self.assertFalse(pygame.display.get_init())

    def test_paused_pending_phase_only_runs_once_after_resume(self) -> None:
        game = Game()
        escape = self.key(pygame.K_ESCAPE)
        events = [[self.key(pygame.K_RETURN)], [self.key(pygame.K_RETURN)],
                  [self.key(pygame.K_w)] * 3 + [self.click()], [], [escape], [],
                  [escape], [], [pygame.event.Event(pygame.QUIT)]]
        snapshots = []
        clock = Mock()
        clock.tick.return_value = 100
        draw = Renderer.draw

        def observe(renderer, screen, snapshot):
            snapshots.append(snapshot)
            draw(renderer, screen, snapshot)
            if snapshot.state is GameState.SHOT_ANIMATION:
                game.world.projectiles[0].max_lifetime = PHYSICS_STEP

        with patch("src.game.pygame.event.get", side_effect=events), patch(
            "src.game.pygame.time.Clock", return_value=clock
        ), patch.object(Renderer, "draw", autospec=True, side_effect=observe), patch(
            "src.world.resolve_enemy_phase", wraps=resolve_enemy_phase
        ) as phase:
            game.run()
        self.assertIs(snapshots[3].state, GameState.TURN_RESOLVE)
        self.assertIs(snapshots[4].state, GameState.PAUSED)
        self.assertEqual(snapshots[4], snapshots[5])
        self.assertEqual(snapshots[5].turn_index, 1)
        self.assertEqual(snapshots[6].turn_index, 2)
        self.assertEqual(phase.call_count, 1)

    def test_game_over_stops_processing_and_ignores_gameplay_input(self) -> None:
        game = Game()
        game.world = World(demo=False)
        events = [[self.key(pygame.K_RETURN)], [self.key(pygame.K_RETURN)],
                  [self.key(pygame.K_w)] * 3 + [self.click()], [], [],
                  [self.click(), self.key(pygame.K_w), self.key(pygame.K_RETURN),
                   self.key(pygame.K_ESCAPE), self.key(pygame.K_r)], [],
                  [pygame.event.Event(pygame.QUIT)]]
        clock = Mock()
        clock.tick.return_value = 100
        snapshots = []
        draw = Renderer.draw
        configured = False

        def observe(renderer, screen, snapshot):
            nonlocal configured
            snapshots.append(snapshot)
            draw(renderer, screen, snapshot)
            if snapshot.state is GameState.PLAYER_AIM and not configured:
                game.world.hp = 3
                game.world.combat.add_enemy(Enemy(1, EnemyType.BOMB, 13, 3))
                configured = True
            if snapshot.state is GameState.SHOT_ANIMATION:
                game.world.projectiles[0].max_lifetime = PHYSICS_STEP

        with patch("src.game.pygame.event.get", side_effect=events), patch(
            "src.game.pygame.time.Clock", return_value=clock
        ), patch.object(Renderer, "draw", autospec=True, side_effect=observe), patch(
            "src.world.resolve_enemy_phase", wraps=resolve_enemy_phase
        ) as phase:
            game.run()
        self.assertIs(snapshots[4].state, GameState.GAME_OVER)
        self.assertEqual(snapshots[4], snapshots[5])
        self.assertEqual(snapshots[5], snapshots[6])
        self.assertEqual((game.world.hp, game.world.mp, game.world.bp, game.world.turn_index),
                         (0, 100, 1, 1))
        self.assertEqual(phase.call_count, 1)
        self.assertEqual(game.world.combat.death_events, [])

    def test_rendering_pending_completed_and_defeated_scenes_never_resolves_turns(self) -> None:
        world = World(demo=False)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 4, 3))
        world.combat.add_crystal(Crystal(2, 5, 3))
        world.player_row = 0
        world.set_aim_target((96, 96))
        world.fire()
        world.projectiles[0].max_lifetime = PHYSICS_STEP
        world.advance_time(PHYSICS_STEP)
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()

        def assert_read_only():
            before = deepcopy(vars(world))
            for _ in range(3):
                renderer.draw(screen, world.snapshot())
            self.assertEqual(vars(world), before)

        assert_read_only()
        self.assertEqual(world.enemies[1].grid_col, 4)
        world.resolve_turn()
        assert_read_only()
        self.assertEqual(world.enemies[1].grid_col, 5)
        world.apply_player_damage(100)
        assert_read_only()


if __name__ == "__main__":
    unittest.main()
