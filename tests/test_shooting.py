"""World, event-loop, pause, and rendering integration for one shooting action."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import os
import unittest
import tempfile

from src.assets import AssetManager
from unittest.mock import Mock, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from src.collision import Bounds, Target
from src.constants import LOGICAL_SIZE, PHYSICS_STEP
from src.game import Game
from src.projectile import Projectile
from src.renderer import Renderer
from src.states import GameState
from src.world import World


class ShootingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World(demo=False)
        self.world.start_new_run()
        self.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self) -> None:
        pygame.quit()

    def fire(self) -> None:
        self.world.set_aim_target((300, 200))
        self.assertTrue(self.world.fire())

    def test_shot_uses_current_origin_and_locks_direction(self) -> None:
        self.world.move_player(-1)
        self.fire()
        self.assertIs(self.world.state, GameState.SHOT_ANIMATION)
        self.assertEqual(len(self.world.projectiles), 1)
        before = self.world.snapshot()
        self.assertEqual(before.projectiles[0].position, (808, 192))
        self.assertFalse(self.world.move_player(1))
        self.assertFalse(self.world.set_aim_target((400, 300)))
        self.assertFalse(self.world.fire())
        self.assertEqual(self.world.snapshot(), before)

    def test_invalid_aim_and_non_aiming_states_do_not_fire(self) -> None:
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.fire())
        self.assertEqual(vars(self.world), before)
        self.world.set_aim_target((900, 200))
        self.assertFalse(self.world.fire())
        self.fire()
        self.world.pause()
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.fire())
        self.assertEqual(vars(self.world), before)

    def test_click_position_is_validated_and_only_left_click_fires(self) -> None:
        game = Game()
        game.world = self.world
        game.running = True
        self.world.set_aim_target((300, 200))
        before = deepcopy(vars(self.world))
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(300, 200)))
        self.assertEqual(vars(self.world), before)
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(900, 200)))
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        self.assertEqual(self.world.projectiles, [])
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(300, 200)))
        self.assertIs(self.world.state, GameState.SHOT_ANIMATION)
        before = self.world.snapshot()
        for _ in range(3):
            game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(600, 400)))
        self.assertEqual(self.world.snapshot(), before)

    def test_shooting_does_not_change_turn_or_resources(self) -> None:
        self.world.hp, self.world.mp = 73, 41
        self.fire()
        for _ in range(300):
            self.world.advance_time(1 / 60)
        self.assertEqual((self.world.stage, self.world.turn_index,
                          self.world.hp, self.world.mp, self.world.bp), (1, 1, 73, 41, 1))

    def test_completion_waits_for_all_projectiles_and_stops_at_turn_resolve(self) -> None:
        self.fire()
        self.world.projectiles[0].max_lifetime = PHYSICS_STEP
        self.world.projectiles.append(Projectile(2, (300, 200), (-520, 0), max_lifetime=0.1))
        self.world.advance_time(PHYSICS_STEP)
        self.assertIs(self.world.state, GameState.SHOT_ANIMATION)
        self.assertEqual([orb.projectile_id for orb in self.world.projectiles], [2])
        self.world.advance_time(0.1)
        self.assertEqual(self.world.projectiles, [])
        self.assertIs(self.world.state, GameState.TURN_RESOLVE)
        before = deepcopy(vars(self.world))
        self.assertEqual(self.world.advance_time(1000), ())
        self.assertFalse(self.world.fire())
        self.assertEqual(vars(self.world), before)

    def test_pause_freezes_position_velocity_lifetime_and_partial_step(self) -> None:
        self.fire()
        self.world.advance_time(0.004)
        projectile_before = self.world.snapshot().projectiles
        accumulator = self.world._physics.accumulator
        self.world.pause()
        paused = deepcopy(vars(self.world))
        self.assertEqual(self.world.advance_time(1000), ())
        self.assertEqual(vars(self.world), paused)
        self.assertEqual(self.world.snapshot().projectiles, projectile_before)
        self.world.resume()
        self.assertEqual(self.world._physics.accumulator, accumulator)
        self.world.advance_time(PHYSICS_STEP - 0.004)
        self.assertAlmostEqual(self.world.projectiles[0].age, PHYSICS_STEP)

    def test_reset_clears_projectiles_fractional_time_and_identifiers(self) -> None:
        self.fire()
        self.world.advance_time(0.004)
        self.world.pause()
        self.world.start_new_run()
        self.assertEqual(vars(self.world), vars(World(demo=False)) | {"_state": GameState.STAGE_INTRO})
        self.world.transition_to(GameState.PLAYER_AIM)
        self.fire()
        self.assertEqual(self.world.projectiles[0].projectile_id, 1)
        self.assertEqual(self.world.projectiles[0].age, 0)

    def test_snapshot_projectiles_are_detached_and_immutable(self) -> None:
        self.fire()
        snapshot = self.world.snapshot()
        self.world.advance_time(0.1)
        self.assertEqual(snapshot.projectiles[0].position, (808, 240))
        self.assertEqual(snapshot.projectiles[0].age, 0)
        with self.assertRaises(FrozenInstanceError):
            snapshot.projectiles[0].age = 1

    def test_world_returns_hit_events_without_applying_damage(self) -> None:
        self.world.set_aim_target((300, 240))
        self.world.fire()
        target = Target(7, Bounds(700, 220, 720, 260))
        events = self.world.advance_time(0.2, (target,))
        self.assertEqual([(event.projectile_id, event.target_id, event.damage)
                          for event in events], [(1, 7, 4)])
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp), (100, 100, 1))

    def test_flying_and_paused_rendering_are_read_only_and_hide_aim_line(self) -> None:
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        renderer = Renderer(AssetManager(root=directory.name))
        self.fire()
        self.world.advance_time(0.1)
        for pause in (False, True):
            with self.subTest(paused=pause):
                if pause:
                    self.world.pause()
                before = deepcopy(vars(self.world))
                with patch("src.renderer.pygame.draw.line", wraps=pygame.draw.line) as line, patch(
                    "src.renderer.pygame.draw.circle", wraps=pygame.draw.circle
                ) as circle:
                    renderer.draw(screen, self.world.snapshot())
                    line.assert_not_called()
                    self.assertTrue(any(c.args[2] == self.world.projectiles[0].position
                                        and c.args[3] == 7 for c in circle.call_args_list))
                self.assertEqual(vars(self.world), before)

    def test_event_loop_does_not_apply_paused_elapsed_time_on_resume(self) -> None:
        game = Game()
        enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(300, 200))
        events = [[enter], [enter], [click], [], [escape], [], [escape], [],
                  [pygame.event.Event(pygame.QUIT)]]
        clock = Mock()
        clock.tick.side_effect = [16, 16, 16, 16, 10_000, 20_000, 16, 16]
        snapshots = []
        original_draw = Renderer.draw

        def record_draw(renderer, screen, snapshot):
            snapshots.append(snapshot)
            original_draw(renderer, screen, snapshot)

        with patch("src.game.pygame.event.get", side_effect=events), patch(
            "src.game.pygame.time.Clock", return_value=clock
        ), patch.object(Renderer, "draw", autospec=True, side_effect=record_draw):
            game.run()
        self.assertEqual(snapshots[2].projectiles[0].age, 0)
        self.assertEqual(snapshots[4].projectiles, snapshots[5].projectiles)
        self.assertEqual(snapshots[5].projectiles, snapshots[6].projectiles)
        self.assertAlmostEqual(snapshots[7].projectiles[0].age, 0.025)
        self.assertEqual(game.world.turn_index, 1)
        self.assertFalse(game.running)


if __name__ == "__main__":
    unittest.main()
