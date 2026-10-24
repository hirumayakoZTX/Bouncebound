"""Deterministic movement and aim rules without Pygame dependencies."""

from copy import deepcopy
import unittest

from src.states import GameState
from src.world import World


class PlayerInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World()
        self.world.start_new_run()
        self.world.transition_to(GameState.PLAYER_AIM)

    def test_initial_position_and_aim_origin(self) -> None:
        snapshot = self.world.snapshot()
        self.assertEqual(snapshot.player_row, 3)
        self.assertEqual(snapshot.player_position, (824, 240))
        self.assertEqual(snapshot.aim_origin, (808, 240))
        self.assertIsNone(snapshot.aim_target)

    def test_move_up_one_row(self) -> None:
        self.assertTrue(self.world.move_player(-1))
        self.assertEqual(self.world.player_row, 2)
        self.assertEqual(self.world.player_position, (824, 192))

    def test_move_down_one_row(self) -> None:
        self.assertTrue(self.world.move_player(1))
        self.assertEqual(self.world.player_row, 4)
        self.assertEqual(self.world.player_position, (824, 288))

    def test_upper_boundary(self) -> None:
        for _ in range(3):
            self.assertTrue(self.world.move_player(-1))
        before = self.world.snapshot()
        for _ in range(10):
            self.assertFalse(self.world.move_player(-1))
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(self.world.player_position, (824, 96))

    def test_lower_boundary_and_all_row_centers(self) -> None:
        for _ in range(3):
            self.world.move_player(-1)
        for row in range(8):
            self.assertEqual(self.world.player_row, row)
            self.assertEqual(self.world.player_position, (824, 96 + 48 * row))
            if row < 7:
                self.assertTrue(self.world.move_player(1))
        before = self.world.snapshot()
        for _ in range(10):
            self.assertFalse(self.world.move_player(1))
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(self.world.player_position, (824, 432))

    def test_invalid_movement_steps_are_ignored(self) -> None:
        before = deepcopy(vars(self.world))
        for delta in (0, -2, 2, 1.0, True, None, "up"):
            with self.subTest(delta=delta):
                self.assertFalse(self.world.move_player(delta))
                self.assertEqual(vars(self.world), before)

    def test_model_rejects_input_outside_player_aim(self) -> None:
        for state in (GameState.MENU, GameState.STAGE_INTRO, GameState.SHOT_ANIMATION):
            with self.subTest(state=state):
                world = World()
                if state is not GameState.MENU:
                    world.start_new_run()
                if state is GameState.SHOT_ANIMATION:
                    world.transition_to(GameState.PLAYER_AIM)
                    world.set_aim_target((300, 200))
                    world.transition_to(GameState.SHOT_ANIMATION)
                before = deepcopy(vars(world))
                self.assertFalse(world.move_player(-1))
                self.assertFalse(world.set_aim_target((200, 100)))
                self.assertEqual(vars(world), before)

    def test_pause_ignores_input_and_resume_preserves_position_and_aim(self) -> None:
        self.world.move_player(1)
        self.world.set_aim_target((300, 200))
        before = self.world.snapshot()
        self.assertTrue(self.world.pause())
        paused = deepcopy(vars(self.world))
        self.assertFalse(self.world.move_player(-1))
        self.assertFalse(self.world.set_aim_target((400, 300)))
        self.assertFalse(self.world.set_aim_target((-1, -1)))
        self.assertEqual(vars(self.world), paused)
        self.assertTrue(self.world.resume())
        self.assertEqual(self.world.snapshot(), before)

    def test_reset_and_new_run_restore_row_and_clear_aim(self) -> None:
        for reset in (self.world.reset, self.world.start_new_run):
            with self.subTest(reset=reset.__name__):
                self.world.start_new_run()
                self.world.transition_to(GameState.PLAYER_AIM)
                self.world.move_player(-1)
                self.world.set_aim_target((200, 150))
                self.world.pause()
                reset()
                self.assertEqual(self.world.player_row, 3)
                self.assertEqual(self.world.player_position, (824, 240))
                self.assertIsNone(self.world.aim_target)
                self.assertIsNone(self.world.paused_state)

    def test_valid_targets_include_exact_field_edges(self) -> None:
        for target in ((96, 72), (768, 72), (96, 456), (768, 456),
                       (400, 250), (200.5, 150.25)):
            with self.subTest(target=target):
                self.assertTrue(self.world.set_aim_target(target))
                self.assertEqual(self.world.snapshot().aim_target, target)
                self.assertIsInstance(self.world.aim_target, tuple)

    def test_outside_targets_clear_previous_valid_aim(self) -> None:
        for target in ((95, 200), (769, 200), (300, 71), (300, 457),
                       (824, 240), (900, 240), (-1, -1)):
            with self.subTest(target=target):
                self.world.set_aim_target((300, 200))
                self.assertFalse(self.world.set_aim_target(target))
                self.assertIsNone(self.world.snapshot().aim_target)

    def test_malformed_and_nonfinite_targets_do_not_create_aim(self) -> None:
        for target in (None, "target", (), (300,), (300, 200, 1), [300, 200],
                       (True, 200), ("300", 200),
                       (float("nan"), 200), (300, float("inf"))):
            with self.subTest(target=target):
                self.world.set_aim_target((300, 200))
                self.assertFalse(self.world.set_aim_target(target))
                self.assertIsNone(self.world.aim_target)

    def test_aim_origin_updates_immediately_after_movement(self) -> None:
        self.world.set_aim_target((200, 150))
        before = self.world.snapshot()
        self.world.move_player(-1)
        after = self.world.snapshot()
        self.assertEqual(before.aim_origin, (808, 240))
        self.assertEqual(after.aim_origin, (808, 192))
        self.assertEqual(after.aim_target, before.aim_target)
        self.assertEqual(before.player_position, (824, 240))

    def test_movement_and_aim_preserve_turn_resources_and_scene(self) -> None:
        self.world.stage, self.world.turn_index = 2, 9
        self.world.hp, self.world.mp, self.world.bp = 83, 42, 4
        for _ in range(10):
            self.world.move_player(-1)
            self.world.set_aim_target((300, 200))
            self.world.move_player(1)
            self.world.set_aim_target((900, 200))
        self.assertEqual((self.world.stage, self.world.turn_index), (2, 9))
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp), (83, 42, 4))
        self.assertIs(self.world.state, GameState.PLAYER_AIM)


if __name__ == "__main__":
    unittest.main()
