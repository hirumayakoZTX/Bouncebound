"""Headless checks of the real Pygame bootstrap lifecycle."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from src.constants import LOGICAL_SIZE, TARGET_FPS, WINDOW_TITLE
from src.game import Game
from src.renderer import Renderer


class BootstrapTests(unittest.TestCase):
    def tearDown(self) -> None:
        pygame.quit()

    def test_imports_do_not_initialize_pygame_or_open_a_window(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", (
                "import main, src.constants, src.game, src.renderer, pygame; "
                "assert not pygame.display.get_init(); "
                "assert not pygame.font.get_init()"
            )],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_window_renders_and_processes_posted_quit_with_frame_cap(self) -> None:
        game = Game()
        clock = Mock()
        original_draw = Renderer.draw
        observed_sizes = []

        def draw_and_request_quit(renderer, screen, snapshot):
            observed_sizes.append(screen.get_size())
            self.assertTrue(pygame.font.get_init())
            self.assertEqual(pygame.display.get_caption()[0], WINDOW_TITLE)
            original_draw(renderer, screen, snapshot)
            pygame.event.post(pygame.event.Event(pygame.QUIT))

        with patch("src.game.pygame.time.Clock", return_value=clock), patch.object(
            Renderer, "draw", autospec=True, side_effect=draw_and_request_quit
        ), patch("src.game.pygame.display.flip", wraps=pygame.display.flip) as flip:
            game.run()

        self.assertEqual(LOGICAL_SIZE, (960, 576))
        self.assertEqual(observed_sizes, [(960, 576)])
        self.assertEqual(TARGET_FPS, 60)
        clock.tick.assert_called_once_with(60)
        flip.assert_called_once_with()
        self.assertFalse(game.running)
        self.assertFalse(pygame.display.get_init())
        self.assertFalse(pygame.font.get_init())

    def test_escape_and_window_close_exit_before_rendering(self) -> None:
        for event in (
            pygame.event.Event(pygame.QUIT),
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE),
        ):
            with self.subTest(event=event), patch(
                "src.game.pygame.event.get", side_effect=[[event]]
            ), patch.object(Renderer, "draw") as draw:
                game = Game()
                game.run()
                draw.assert_not_called()
                self.assertFalse(game.running)
                self.assertFalse(pygame.display.get_init())

    def test_unrelated_events_do_not_exit(self) -> None:
        game = Game()
        game.running = True
        game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(100, 100)))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
        self.assertTrue(game.running)

    def test_startup_failure_still_shuts_down_initialized_subsystems(self) -> None:
        game = Game()
        with patch(
            "src.game.pygame.display.set_mode", side_effect=pygame.error("No display")
        ), self.assertRaisesRegex(pygame.error, "No display"):
            game.run()
        self.assertFalse(game.running)
        self.assertFalse(pygame.display.get_init())
        self.assertFalse(pygame.font.get_init())

    def test_startup_from_directory_without_optional_assets(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        code = (
            f"import sys; sys.path.insert(0, {str(repo_root)!r}); "
            "import pygame; from src.game import Game; "
            "from src.renderer import Renderer; "
            "original_draw = Renderer.draw; "
            "Renderer.draw = lambda self, screen, snapshot: "
            "(original_draw(self, screen, snapshot), "
            "pygame.event.post(pygame.event.Event(pygame.QUIT))); "
            "Game().run(); assert not pygame.display.get_init()"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=directory,
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
