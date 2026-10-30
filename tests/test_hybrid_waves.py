"""Hybrid scheduled/empty-board wave progression through authoritative boundaries."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from src.combat import Combat
from src.encounter import Encounter, Spawn, Wave
from src.renderer import Renderer
from src.stage_config import parse_stage
from src.states import GameState, GameOverReason
from src.turns import resolve_enemy_phase
from src.world import World
from test_stage_config import stage_data


def definition(stage=1):
    data = stage_data(stage)
    data["waves"].extend((
        {"turn": 3, "spawns": [
            {"id": 3, "kind": "basic", "col": 0, "row": 4},
            {"id": 4, "kind": "crystal", "col": 0, "row": 4},
        ]},
        {"turn": 5, "spawns": [
            {"id": 5, "kind": "basic", "col": 1, "row": 5},
            {"id": 6, "kind": "crystal", "col": 1, "row": 5},
        ]},
    ))
    data["completion"]["mandatory_enemy_ids"].extend((3, 5))
    return parse_stage(data)


def aiming_world(config=None):
    world = World(encounter=config or definition())
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    return world


def finish_spell(world):
    assert world.select_spell("fire")
    assert world.cast_selected_spell().valid
    world.advance_time(1.0)
    assert world.state is GameState.TURN_RESOLVE


class HybridWaveTests(unittest.TestCase):
    def tearDown(self):
        pygame.quit()

    def test_fire_clearing_board_accelerates_one_wave_after_exactly_one_enemy_phase(self):
        world = aiming_world()
        self.assertEqual(world.encounter.spawn_history, [1, 2])
        finish_spell(world)
        self.assertEqual(world.snapshot().spawned_waves, 1)
        self.assertEqual(world.spawn_waves(), ())  # Pending spell action blocks scheduling.

        with patch("src.world.resolve_enemy_phase", wraps=resolve_enemy_phase) as phase:
            self.assertTrue(world.resolve_turn())

        self.assertEqual(phase.call_count, 1)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual(world.turn_index, 2)
        self.assertEqual(world.mp, 70)
        self.assertEqual(world.snapshot().spawned_waves, 2)
        self.assertEqual(world.encounter.spawn_history, [1, 2, 3, 4])
        self.assertEqual({enemy.enemy_id for enemy in world.snapshot().enemies}, {3})
        self.assertEqual(world.enemies[3].turns_alive, 0)
        self.assertIsNone(world.enemies[3].last_action_turn)
        self.assertEqual(world.spells.next_ready_turn(world.selected_spell), 5)

    def test_early_wave_is_recorded_once_and_not_repeated_at_its_configured_turn(self):
        encounter = Encounter(definition())
        combat = Combat()
        self.assertEqual(encounter.spawn_due(1, combat), (1, 2))
        combat.apply_damage(1, 5)
        self.assertEqual(encounter.spawn_due(2, combat, accelerate_if_empty=True), (3, 4))
        history = tuple(encounter.spawn_history)
        self.assertEqual(encounter.spawned_waves, {0, 1})
        # Turn 3 is the original schedule for Wave 2; it cannot publish it twice.
        self.assertEqual(encounter.spawn_due(3, combat), ())
        self.assertEqual(tuple(encounter.spawn_history), history)
        self.assertEqual(set(combat.enemies), {1, 3})
        self.assertEqual(set(combat.crystals), {2, 4})

    def test_only_one_future_wave_accelerates_at_an_empty_boundary(self):
        world = aiming_world()
        finish_spell(world)
        world.resolve_turn()
        self.assertEqual(world.encounter.spawned_waves, {0, 1})
        self.assertNotIn(5, world.enemies)
        self.assertEqual(world.encounter.spawn_history, [1, 2, 3, 4])

    def test_stage_two_and_three_encounters_use_the_same_single_wave_scheduler(self):
        for stage in (2, 3):
            with self.subTest(stage=stage):
                encounter = Encounter(definition(stage))
                combat = Combat()
                encounter.spawn_due(1, combat)
                combat.apply_damage(1, 5)
                spawned = encounter.spawn_due(2, combat, accelerate_if_empty=True)
                self.assertEqual(spawned, (3, 4))
                self.assertEqual(encounter.spawned_waves, {0, 1})
                self.assertNotIn(5, combat.enemies)

    def test_surviving_enemies_keep_configured_turn_schedule(self):
        encounter = Encounter(definition())
        combat = Combat()
        encounter.spawn_due(1, combat)
        self.assertEqual(encounter.spawn_due(2, combat, accelerate_if_empty=True), ())
        self.assertEqual(encounter.spawned_waves, {0})
        self.assertEqual(encounter.spawn_due(3, combat), (3, 4))
        self.assertEqual(encounter.spawned_waves, {0, 1})

    def test_bomb_chain_finishes_before_the_next_wave_is_published(self):
        data = stage_data()
        data["waves"][0]["spawns"][0].update(kind="bomb", col=5, row=3)
        data["waves"][0]["spawns"][1].update(col=0, row=7)
        data["waves"][0]["spawns"].append(
            {"id": 3, "kind": "bomb", "col": 4, "row": 3}
        )
        data["waves"].append({"turn": 3, "spawns": [
            {"id": 4, "kind": "basic", "col": 0, "row": 4}
        ]})
        data["completion"]["mandatory_enemy_ids"].extend((3, 4))
        world = aiming_world(parse_stage(data))
        self.assertTrue(world.set_aim_target((96, 240)))
        self.assertTrue(world.fire())
        elapsed = 0.0
        while world.state is GameState.SHOT_ANIMATION and elapsed < 6.0:
            world.advance_time(0.25)
            elapsed += 0.25
        self.assertIs(world.state, GameState.TURN_RESOLVE)
        self.assertEqual({event.enemy_id for event in world.combat.death_events}, {1, 3})
        self.assertNotIn(4, world.enemies)
        world.resolve_turn()
        self.assertEqual(world.encounter.spawned_waves, {0, 1})
        self.assertEqual(world.encounter.spawn_history, [1, 2, 3, 4])
        self.assertEqual(world.enemies[4].turns_alive, 0)

    def test_spell_animation_pause_and_pending_action_block_early_spawning(self):
        world = aiming_world()
        self.assertTrue(world.select_spell("fire"))
        self.assertTrue(world.cast_selected_spell().valid)
        remaining = world.snapshot().spell_remaining
        self.assertEqual(world.spawn_waves(), ())
        self.assertTrue(world.pause())
        world.advance_time(20.0)
        self.assertEqual(world.snapshot().spell_remaining, remaining)
        self.assertEqual(world.spawn_waves(), ())
        self.assertTrue(world.resume())
        world.advance_time(1.0)
        self.assertIs(world.state, GameState.TURN_RESOLVE)
        self.assertEqual(world.spawn_waves(), ())
        self.assertEqual(world.snapshot().spawned_waves, 1)
        world.resolve_turn()
        self.assertEqual(world.snapshot().spawned_waves, 2)

    def test_projectile_flight_and_pause_cannot_accelerate_a_wave(self):
        world = aiming_world()
        self.assertTrue(world.set_aim_target((96, 240)))
        self.assertTrue(world.fire())
        self.assertEqual(world.spawn_waves(), ())
        self.assertEqual(world._spawn_after_resolved_turn(), ())
        self.assertEqual(world.snapshot().spawned_waves, 1)
        self.assertTrue(world.pause())
        world.advance_time(10.0)
        self.assertEqual(world.spawn_waves(), ())
        self.assertEqual(world.snapshot().spawned_waves, 1)

    def test_repeated_rendering_of_an_empty_board_does_not_spawn_waves(self):
        world = aiming_world()
        world.combat.apply_damage(1, 5)
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode((960, 576))
        renderer = Renderer()
        before = tuple(world.encounter.spawn_history)
        for _ in range(5):
            renderer.draw(screen, world.snapshot())
        self.assertEqual(tuple(world.encounter.spawn_history), before)
        self.assertEqual(world.encounter.spawned_waves, {0})

    def test_mandatory_escape_takes_precedence_over_empty_board_acceleration(self):
        data = stage_data()
        data["waves"][0]["spawns"][0]["col"] = 13
        world = aiming_world(parse_stage(data))
        self.assertTrue(world.select_spell("ward"))
        self.assertTrue(world.cast_selected_spell().valid)
        world.advance_time(1.0)
        world.resolve_turn()
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertEqual(world.encounter.spawned_waves, {0})
        self.assertEqual(world.encounter.spawn_history, [1, 2])


if __name__ == "__main__":
    unittest.main()
