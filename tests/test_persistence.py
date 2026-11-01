"""Local high-score schema, error handling, and authorized-save integration."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.persistence import (
    HighScoreRecord, HighScoreStore, SAVE_VERSION, default_save_path,
)
from src.states import GameState
from src.world import World
from stage_one_fixtures import perform_action
from test_gr02_balance import STAGE_ONE_ROWS, run_defended_campaign


class CountingStore(HighScoreStore):
    def __init__(self, path):
        super().__init__(path)
        self.save_calls = 0

    def save_completed_campaign(self, score, last_stage):
        self.save_calls += 1
        return super().save_completed_campaign(score, last_stage)


class HighScoreStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "app-data" / "save" / "high_scores.json"
        self.store = HighScoreStore(self.path)

    def test_default_path_is_platform_relative_and_outside_the_project(self):
        home = self.root / "user"
        mac = default_save_path(platform="darwin", environ={}, home=home)
        self.assertEqual(mac, home / "Library/Application Support/Bouncebound/save/high_scores.json")
        windows = default_save_path(platform="win32", environ={"LOCALAPPDATA": str(self.root / "Local")}, home=home)
        self.assertEqual(windows, self.root / "Local/Bouncebound/save/high_scores.json")
        linux = default_save_path(platform="linux", environ={"XDG_DATA_HOME": str(self.root / "xdg")}, home=home)
        self.assertEqual(linux, self.root / "xdg/bouncebound/save/high_scores.json")

    def test_missing_file_is_a_normal_first_launch_and_directory_is_lazy(self):
        loaded = self.store.load()
        self.assertTrue(loaded.available)
        self.assertEqual(loaded.record, HighScoreRecord())
        self.assertFalse(self.path.parent.exists())
        saved = self.store.save_completed_campaign(1234, 3)
        self.assertTrue(saved.saved)
        self.assertTrue(self.path.is_file())
        self.assertEqual(json.loads(self.path.read_text()), {
            "version": SAVE_VERSION, "best_score": 1234,
            "last_score": 1234, "last_stage": 3,
        })

    def test_saved_score_loads_in_a_fresh_process(self):
        self.store.save_completed_campaign(7654, 3)
        code = (
            "import os; from src.persistence import HighScoreStore; "
            "r=HighScoreStore(os.environ['TEST_SCORE_PATH']).load(); "
            "print(r.record.best_score, r.record.last_score, r.record.last_stage)"
        )
        env = dict(os.environ, TEST_SCORE_PATH=str(self.path),
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=self.root,
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "7654 7654 3")

    def test_best_score_comparison_lower_higher_and_equal_policy(self):
        first = self.store.save_completed_campaign(1000, 3)
        self.assertTrue(first.new_record)
        lower = self.store.save_completed_campaign(700, 3)
        self.assertFalse(lower.new_record)
        self.assertEqual(lower.record, HighScoreRecord(1000, 700, 3))
        equal = self.store.save_completed_campaign(1000, 3)
        self.assertFalse(equal.new_record)
        self.assertEqual(equal.record, HighScoreRecord(1000, 1000, 3))
        higher = self.store.save_completed_campaign(1200, 3)
        self.assertTrue(higher.new_record)
        self.assertEqual(higher.record, HighScoreRecord(1200, 1200, 3))

    def test_malformed_and_invalid_records_are_rejected_without_crashing(self):
        valid = {"version": 1, "best_score": 100, "last_score": 80, "last_stage": 3}
        cases = [
            "{not json",
            "[]",
            json.dumps({**valid, "version": 2}),
            json.dumps({**valid, "version": True}),
            json.dumps({**valid, "best_score": -1}),
            json.dumps({**valid, "last_score": -1}),
            json.dumps({**valid, "best_score": True}),
            json.dumps({**valid, "last_score": False}),
            json.dumps({**valid, "last_stage": True}),
            json.dumps({**valid, "last_stage": 4}),
            json.dumps({**valid, "last_score": 101}),
            json.dumps({"version": 1, "best_score": 1, "last_score": 1}),
            json.dumps({**valid, "extra": 1}),
            '{"version":1,"version":1,"best_score":1,"last_score":1,"last_stage":3}',
        ]
        for contents in cases:
            with self.subTest(contents=contents):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(contents, encoding="utf-8")
                loaded = self.store.load()
                self.assertFalse(loaded.available)
                self.assertIsNone(loaded.record)

    def test_corrupt_json_is_rebuilt_only_after_completed_campaign(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("corrupt", encoding="utf-8")
        self.assertFalse(self.store.load().available)
        repaired = self.store.save_completed_campaign(4321, 3)
        self.assertTrue(repaired.saved)
        self.assertIsNone(repaired.new_record)  # Previous best was not knowable.
        self.assertEqual(repaired.record.best_score, 4321)
        self.assertTrue(self.store.load().available)

    def test_file_deleted_between_load_and_completion_is_recreated(self):
        first = self.store.save_completed_campaign(1000, 3)
        self.assertTrue(first.saved)
        self.assertEqual(self.store.load().record.best_score, 1000)
        self.path.unlink()
        saved = self.store.save_completed_campaign(700, 3)
        self.assertTrue(saved.saved)
        self.assertTrue(saved.new_record)  # A deleted file is a fresh local record.
        self.assertEqual(saved.record, HighScoreRecord(700, 700, 3))

    def test_unsupported_future_schema_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"version":99,"future_field":"keep me"}', encoding="utf-8")
        before = self.path.read_bytes()
        result = self.store.save_completed_campaign(5000, 3)
        self.assertFalse(result.saved)
        self.assertIn("unsupported", result.message)
        self.assertEqual(self.path.read_bytes(), before)

    def test_scores_and_stage_must_be_real_integers_and_final_stage(self):
        for score in (-1, True, 1.0, "100"):
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.store.save_completed_campaign(score, 3)
        for stage in (1, 2, True, 3.0):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                self.store.save_completed_campaign(100, stage)
        self.assertFalse(self.path.exists())

    def test_read_permission_error_is_reported_as_unavailable(self):
        original_open = Path.open

        def deny_read(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError("read denied")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=deny_read):
            loaded = self.store.load()
            self.assertFalse(loaded.available)
            self.assertIsNone(loaded.record)

    def test_atomic_write_permission_error_preserves_existing_record(self):
        self.store.save_completed_campaign(900, 3)
        original = self.path.read_bytes()
        with patch("src.persistence.os.replace", side_effect=PermissionError("write denied")):
            failed = self.store.save_completed_campaign(1500, 3)
        self.assertFalse(failed.saved)
        self.assertFalse(failed.new_record)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_no_repository_files_are_created_by_injected_store(self):
        repository = Path(__file__).resolve().parents[1]
        self.store.save_completed_campaign(333, 3)
        self.assertFalse((repository / "save" / "high_scores.json").exists())


class WorldPersistenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "save" / "high_scores.json"

    def test_stage_clear_game_over_retry_and_campaign_restart_do_not_save(self):
        store = HighScoreStore(self.path)
        seed = store.save_completed_campaign(4321, 3)
        self.assertTrue(seed.saved)
        original_record = self.path.read_bytes()
        world = World(high_score_store=store)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        for row in STAGE_ONE_ROWS:
            perform_action(world, "shot", row)
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual(self.path.read_bytes(), original_record)
        self.assertTrue(world.advance_stage())
        world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(world.apply_player_damage(100), 100)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual(self.path.read_bytes(), original_record)
        self.assertTrue(world.retry_current_stage())
        self.assertEqual(self.path.read_bytes(), original_record)
        world.transition_to(GameState.PLAYER_AIM)
        world.apply_player_damage(100)
        self.assertTrue(world.restart())
        self.assertEqual(self.path.read_bytes(), original_record)

    def test_legitimate_campaign_saves_once_after_final_bonuses_and_reload(self):
        store = CountingStore(self.path)
        world, completed = run_defended_campaign((1 / 60,), high_score_store=store)
        self.assertTrue(completed)
        self.assertIs(world.state, GameState.RESULTS)
        score = world.snapshot().score
        high_scores = world.snapshot().high_scores
        self.assertEqual(score.total, 30750)
        self.assertEqual(score.breakdown.stage_bonuses, 6000)
        self.assertEqual(store.save_calls, 1)
        self.assertTrue(high_scores.saved)
        self.assertTrue(high_scores.new_record)
        self.assertEqual(high_scores.record, HighScoreRecord(30750, 30750, 3))
        for _ in range(10):
            world.snapshot()
            self.assertFalse(world.resolve_turn())
        self.assertEqual(store.save_calls, 1)

        fresh_instance = HighScoreStore(self.path).load()
        self.assertEqual(fresh_instance.record, high_scores.record)

    def test_results_rendering_is_read_only_and_shows_best_and_save_state(self):
        import pygame
        from src.screens import ScreenRenderer

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.display.init()
        pygame.font.init()
        self.addCleanup(pygame.quit)
        screen = pygame.Surface((960, 576))
        store = CountingStore(self.path)
        saved = store.save_completed_campaign(2200, 3)
        world = World(high_score_store=store)
        world.high_scores = saved
        world.score.finalize_stage(100, 100, 100, 100)
        world.stage = 3
        world._cleared_stage = 3
        world._state = GameState.RESULTS
        renderer = ScreenRenderer()
        labels = []
        draw_text = renderer._text

        def capture_text(target, text, *args, **kwargs):
            labels.append(text)
            return draw_text(target, text, *args, **kwargs)

        before = self.path.read_bytes()
        with patch.object(renderer, "_text", side_effect=capture_text):
            for _ in range(5):
                renderer.terminal(screen, world.snapshot())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn("Best: 2200", labels)
        self.assertIn("NEW RECORD SAVED", labels)
        self.assertEqual(world.snapshot().high_scores.record.best_score, 2200)
        self.assertEqual(store.save_calls, 1)

    def test_world_and_game_without_injected_store_never_open_default_score_file(self):
        from src.game import Game

        with patch.object(HighScoreStore, "load", side_effect=AssertionError("unexpected disk read")):
            World()
            Game()

    def test_equivalent_full_campaigns_save_identical_records_at_all_schedules(self):
        reference = None
        for index, schedule in enumerate(((1 / 30,), (1 / 60,), (1 / 144,),
                                          (0.003, 0.071, 0.19, 0.016, 0.11))):
            with self.subTest(schedule=schedule):
                path = Path(self.temporary.name) / str(index) / "high_scores.json"
                store = CountingStore(path)
                world, completed = run_defended_campaign(schedule, high_score_store=store)
                self.assertTrue(completed)
                result = (world.snapshot().score.total, world.snapshot().high_scores.record,
                          world.snapshot().high_scores.new_record, store.save_calls)
                self.assertEqual(result, (30750, HighScoreRecord(30750, 30750, 3), True, 1))
                if reference is None:
                    reference = result
                self.assertEqual(result, reference)


class ApplicationPersistenceWiringTests(unittest.TestCase):
    def test_main_bootstrap_supplies_platform_store_without_import_time_io(self):
        import main

        with patch.object(main, "Game") as game_class:
            main.main(["--no-effects"])
            game_class.assert_called_once()
            args, kwargs = game_class.call_args
            self.assertEqual(args, ())
            self.assertFalse(kwargs["effects_enabled"])
            self.assertFalse(kwargs["audio_enabled"])
            self.assertIsInstance(kwargs["high_score_store"], HighScoreStore)
            game_class.return_value.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
