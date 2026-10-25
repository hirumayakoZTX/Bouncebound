"""Deterministic state and run-data tests without Pygame initialization."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import subprocess
import sys
import unittest

from src.states import GameState
from src.world import World


class WorldTests(unittest.TestCase):
    def aiming_world(self) -> World:
        world = World()
        world.start_new_run()
        self.assertTrue(world.transition_to(GameState.PLAYER_AIM))
        return world

    def test_initial_state_and_run_values(self) -> None:
        world = World()
        self.assertIs(world.state, GameState.MENU)
        self.assertIsNone(world.paused_state)
        self.assertEqual((world.stage, world.turn_index), (1, 1))
        self.assertEqual((world.hp, world.max_hp, world.mp, world.max_mp, world.bp),
                         (100, 100, 100, 100, 1))

    def test_controller_import_does_not_import_pygame(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", (
                "from src.world import World; import sys; "
                "World().start_new_run(); assert 'pygame' not in sys.modules"
            )], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_valid_phase_order_and_reserved_end_states(self) -> None:
        world = World()
        for target in (
            GameState.STAGE_INTRO, GameState.PLAYER_AIM,
            GameState.SHOT_ANIMATION, GameState.TURN_RESOLVE, GameState.PLAYER_AIM,
            GameState.SPELL_ANIMATION, GameState.TURN_RESOLVE,
        ):
            with self.subTest(target=target):
                self.assertTrue(world.transition_to(target))
                self.assertIs(world.state, target)
                self.assertEqual(world.turn_index, 1)
        for reserved in (GameState.STAGE_CLEAR, GameState.VICTORY, GameState.RESULTS):
            before = deepcopy(vars(world))
            self.assertFalse(world.transition_to(reserved))
            self.assertEqual(vars(world), before)

    def test_invalid_transitions_are_atomic(self) -> None:
        world = World()
        for target in (GameState.MENU, GameState.PLAYER_AIM, GameState.PAUSED,
                       GameState.VICTORY, "PLAYER_AIM", None, []):
            with self.subTest(target=target):
                before = deepcopy(vars(world))
                self.assertFalse(world.transition_to(target))
                self.assertEqual(vars(world), before)
        world = self.aiming_world()
        before = deepcopy(vars(world))
        self.assertFalse(world.transition_to(GameState.TURN_RESOLVE))
        self.assertEqual(vars(world), before)

    def test_pause_resumes_each_exact_active_phase_without_changing_data(self) -> None:
        for phase in (GameState.PLAYER_AIM, GameState.SHOT_ANIMATION,
                      GameState.SPELL_ANIMATION, GameState.TURN_RESOLVE):
            with self.subTest(phase=phase):
                world = self.aiming_world()
                if phase is GameState.TURN_RESOLVE:
                    world.transition_to(GameState.SHOT_ANIMATION)
                if phase is not GameState.PLAYER_AIM:
                    self.assertTrue(world.transition_to(phase))
                world.turn_index = 7
                before = world.snapshot()
                for _ in range(2):
                    self.assertTrue(world.pause())
                    self.assertIs(world.paused_state, phase)
                    paused = deepcopy(vars(world))
                    self.assertFalse(world.pause())
                    self.assertFalse(world.transition_to(GameState.STAGE_INTRO))
                    wrong_phase = (GameState.SHOT_ANIMATION
                                   if phase is GameState.PLAYER_AIM
                                   else GameState.PLAYER_AIM)
                    self.assertFalse(world.transition_to(wrong_phase))
                    self.assertEqual(vars(world), paused)
                    self.assertTrue(world.resume())
                    self.assertIsNone(world.paused_state)
                    self.assertEqual(world.snapshot(), before)
                self.assertFalse(world.resume())

    def test_non_active_scenes_cannot_pause_or_resume(self) -> None:
        world = World()
        for state in (GameState.MENU, GameState.STAGE_INTRO):
            with self.subTest(state=state):
                if state is GameState.STAGE_INTRO:
                    world.start_new_run()
                before = deepcopy(vars(world))
                self.assertFalse(world.pause())
                self.assertFalse(world.resume())
                self.assertEqual(vars(world), before)

    def test_reset_and_new_run_restore_all_owned_data_and_pause_state(self) -> None:
        world = self.aiming_world()
        world.stage = 3
        world.turn_index = 12
        world.hp, world.max_hp = 10, 80
        world.mp, world.max_mp = 20, 90
        world.bp = 5
        world.pause()
        world.reset()
        self.assertEqual(vars(world), vars(World()))

        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.hp, world.mp, world.bp, world.turn_index = 30, 0, 4, 8
        world.pause()
        world.start_new_run()
        expected = World()
        expected.transition_to(GameState.STAGE_INTRO)
        self.assertEqual(vars(world), vars(expected))

    def test_worlds_and_snapshots_do_not_share_mutable_run_data(self) -> None:
        world = World()
        snapshot = world.snapshot()
        world.hp = 50
        self.assertEqual(snapshot.hp, 100)
        self.assertEqual(World().hp, 100)
        with self.assertRaises(FrozenInstanceError):
            snapshot.hp = 0


if __name__ == "__main__":
    unittest.main()
