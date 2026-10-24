"""Scene input, rendering isolation, and application-loop integration."""

from copy import deepcopy
import os
import unittest
from unittest.mock import Mock, call, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from src.constants import LOGICAL_SIZE
from src.game import Game
from src.renderer import Renderer
from src.states import GameState
from src.world import World


def world_in_state(state: GameState) -> World:
    paths = {
        GameState.MENU: (),
        GameState.STAGE_INTRO: (GameState.STAGE_INTRO,),
        GameState.PLAYER_AIM: (GameState.STAGE_INTRO, GameState.PLAYER_AIM),
    }
    aim_path = paths[GameState.PLAYER_AIM]
    paths.update({
        GameState.SHOT_ANIMATION: aim_path + (GameState.SHOT_ANIMATION,),
        GameState.SPELL_ANIMATION: aim_path + (GameState.SPELL_ANIMATION,),
        GameState.TURN_RESOLVE: aim_path + (
            GameState.SHOT_ANIMATION, GameState.TURN_RESOLVE,
        ),
        GameState.STAGE_CLEAR: aim_path + (
            GameState.SHOT_ANIMATION, GameState.STAGE_CLEAR,
        ),
        GameState.GAME_OVER: aim_path + (
            GameState.SHOT_ANIMATION, GameState.GAME_OVER,
        ),
        GameState.VICTORY: aim_path + (
            GameState.SHOT_ANIMATION, GameState.VICTORY,
        ),
        GameState.RESULTS: aim_path + (
            GameState.SHOT_ANIMATION, GameState.VICTORY, GameState.RESULTS,
        ),
        GameState.PAUSED: aim_path + (GameState.PAUSED,),
    })
    world = World()
    for target in paths[state]:
        if not world.transition_to(target):
            raise AssertionError(f"Could not reach {target.name}")
    return world


class SceneTests(unittest.TestCase):
    def tearDown(self) -> None:
        pygame.quit()

    def game_in_state(self, state: GameState) -> Game:
        game = Game()
        game.world = world_in_state(state)
        game.running = True
        return game

    def test_enter_only_advances_menu_and_introduction(self) -> None:
        expected = {
            GameState.MENU: GameState.STAGE_INTRO,
            GameState.STAGE_INTRO: GameState.PLAYER_AIM,
        }
        for state in GameState:
            with self.subTest(state=state):
                game = self.game_in_state(state)
                game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
                self.assertIs(game.world.state, expected.get(state, state))
                self.assertEqual(game.world.turn_index, 1)
                self.assertTrue(game.running)

    def test_escape_is_scene_specific(self) -> None:
        expected = {
            GameState.PLAYER_AIM: GameState.PAUSED,
            GameState.SHOT_ANIMATION: GameState.PAUSED,
            GameState.SPELL_ANIMATION: GameState.PAUSED,
            GameState.TURN_RESOLVE: GameState.PAUSED,
            GameState.PAUSED: GameState.PLAYER_AIM,
        }
        for state in GameState:
            with self.subTest(state=state):
                game = self.game_in_state(state)
                game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
                self.assertIs(game.world.state, expected.get(state, state))
                self.assertEqual(game.running, state is not GameState.MENU)
                self.assertEqual(game.world.turn_index, 1)

    def test_window_close_exits_from_every_state_without_mutating_world(self) -> None:
        for state in GameState:
            with self.subTest(state=state):
                game = self.game_in_state(state)
                before = deepcopy(vars(game.world))
                game.handle_event(pygame.event.Event(pygame.QUIT))
                self.assertFalse(game.running)
                game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
                self.assertEqual(vars(game.world), before)

    def test_unimplemented_inputs_do_not_change_state_or_run_data(self) -> None:
        for state in GameState:
            with self.subTest(state=state):
                game = self.game_in_state(state)
                before = deepcopy(vars(game.world))
                for key in (pygame.K_w, pygame.K_s, pygame.K_UP, pygame.K_DOWN,
                            pygame.K_SPACE, pygame.K_1, pygame.K_r):
                    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
                game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1))
                game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(100, 100)))
                self.assertEqual(vars(game.world), before)

    def test_rendering_all_scenes_preserves_world_and_snapshot(self) -> None:
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        for state in GameState:
            with self.subTest(state=state):
                world = world_in_state(state)
                before = deepcopy(vars(world))
                snapshot = world.snapshot()
                for _ in range(3):
                    renderer.draw(screen, snapshot)
                self.assertEqual(world.snapshot(), snapshot)
                self.assertEqual(vars(world), before)

    def test_event_loop_navigation_keeps_turn_and_frame_cap(self) -> None:
        game = Game()
        enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        events = [[enter], [enter], [escape], [enter], [escape],
                  [pygame.event.Event(pygame.QUIT), enter]]
        snapshots = []
        original_draw = Renderer.draw
        clock = Mock()

        def observe_draw(renderer, screen, snapshot):
            snapshots.append(snapshot)
            original_draw(renderer, screen, snapshot)

        with patch("src.game.pygame.event.get", side_effect=events), patch(
            "src.game.pygame.time.Clock", return_value=clock
        ), patch.object(Renderer, "draw", autospec=True, side_effect=observe_draw):
            game.run()

        self.assertEqual([snapshot.state for snapshot in snapshots], [
            GameState.STAGE_INTRO, GameState.PLAYER_AIM, GameState.PAUSED,
            GameState.PAUSED, GameState.PLAYER_AIM,
        ])
        for snapshot in snapshots:
            self.assertEqual((snapshot.stage, snapshot.turn_index), (1, 1))
            self.assertEqual((snapshot.hp, snapshot.mp, snapshot.bp), (100, 100, 1))
        self.assertEqual(clock.tick.call_args_list, [call(60)] * 5)
        self.assertFalse(game.running)
        self.assertFalse(pygame.display.get_init())


if __name__ == "__main__":
    unittest.main()
