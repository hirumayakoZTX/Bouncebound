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
                keys = (pygame.K_SPACE, pygame.K_1)
                if state not in (GameState.GAME_OVER, GameState.STAGE_CLEAR):
                    keys += (pygame.K_r,)
                for key in keys:
                    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
                game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1))
                self.assertEqual(vars(game.world), before)

    def test_movement_keys_move_exactly_one_row_and_ignore_key_repeat(self) -> None:
        for key, expected_row in ((pygame.K_w, 2), (pygame.K_UP, 2),
                                  (pygame.K_s, 4), (pygame.K_DOWN, 4)):
            with self.subTest(key=key):
                game = self.game_in_state(GameState.PLAYER_AIM)
                game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
                self.assertEqual(game.world.player_row, expected_row)
                game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, repeat=True))
                self.assertEqual(game.world.player_row, expected_row)
                self.assertIs(game.world.state, GameState.PLAYER_AIM)
                self.assertEqual((game.world.turn_index, game.world.hp,
                                  game.world.mp, game.world.bp), (1, 100, 100, 1))

    def test_movement_and_mouse_input_are_ignored_outside_aiming(self) -> None:
        for state in GameState:
            if state is GameState.PLAYER_AIM:
                continue
            with self.subTest(state=state):
                game = self.game_in_state(state)
                before = deepcopy(vars(game.world))
                for key in (pygame.K_w, pygame.K_s, pygame.K_UP, pygame.K_DOWN):
                    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
                game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(100, 100)))
                self.assertEqual(vars(game.world), before)

    def test_mouse_aim_moves_with_player_and_survives_pause(self) -> None:
        game = self.game_in_state(GameState.PLAYER_AIM)
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(200, 150)))
        self.assertEqual(game.world.aim_target, (200, 150))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w))
        self.assertEqual(game.world.snapshot().aim_origin, (808, 192))
        before = game.world.snapshot()
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(400, 300)))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.assertEqual(game.world.snapshot(), before)
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(900, 200)))
        self.assertIsNone(game.world.aim_target)

    def test_rendering_all_scenes_preserves_world_and_snapshot(self) -> None:
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        for state in GameState:
            with self.subTest(state=state):
                world = world_in_state(state)
                if state is GameState.PLAYER_AIM:
                    world.move_player(-1)
                    world.set_aim_target((200, 150))
                before = deepcopy(vars(world))
                snapshot = world.snapshot()
                for _ in range(3):
                    renderer.draw(screen, snapshot)
                self.assertEqual(world.snapshot(), snapshot)
                self.assertEqual(vars(world), before)

    def test_renderer_uses_snapshot_player_position_and_valid_aim_only(self) -> None:
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        world = world_in_state(GameState.PLAYER_AIM)
        world.move_player(-1)
        world.set_aim_target((200, 150))
        before = deepcopy(vars(world))
        with patch("src.renderer.pygame.draw.line", wraps=pygame.draw.line) as line, patch(
            "src.renderer.pygame.draw.circle", wraps=pygame.draw.circle
        ) as circle:
            renderer.draw(screen, world.snapshot())
            self.assertEqual(line.call_count, 1)
            self.assertEqual(line.call_args.args[2:4], ((808, 192), (200, 150)))
            self.assertTrue(any(args.args[2] == (824, 192) for args in circle.call_args_list))
        self.assertEqual(vars(world), before)
        world.set_aim_target((900, 200))
        with patch("src.renderer.pygame.draw.line", wraps=pygame.draw.line) as line:
            renderer.draw(screen, world.snapshot())
            line.assert_not_called()

    def test_event_loop_navigation_keeps_turn_and_frame_cap(self) -> None:
        game = Game()
        enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
        escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        events = [[enter], [enter], [escape], [enter], [escape],
                  [pygame.event.Event(pygame.QUIT), enter]]
        snapshots = []
        original_draw = Renderer.draw
        clock = Mock()
        clock.tick.return_value = 16

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
