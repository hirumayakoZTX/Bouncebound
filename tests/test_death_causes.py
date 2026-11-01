"""Specific defeat causes are captured by World and shown as read-only UI data."""

import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

from src.constants import LOGICAL_SIZE
from src.entities import Enemy, EnemyType
from src.screens import ScreenRenderer
from src.states import GameOverReason, GameState
from src.world import World
from stage_one_fixtures import perform_action


class SpecificDeathCauseTests(unittest.TestCase):
    @staticmethod
    def playing_world(*, hp=100):
        world = World(demo=True)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.enemies.clear()
        world.hp = hp
        return world

    def test_poison_records_the_named_enemy_that_caused_defeat(self):
        world = self.playing_world(hp=3)
        source = Enemy(17, EnemyType.MAWROOT, 0, 0)
        source.turns_alive = 2
        world.combat.add_enemy(source)

        perform_action(world, "shot", 3)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        perform_action(world, "shot", 3)

        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertEqual(world.death_cause, "Poison from Bigmouth Flower dealt the final damage.")

    def test_heavy_blow_is_nonlethal_at_full_hp_and_has_a_specific_lethal_cause(self):
        healthy = self.playing_world()
        boss = Enemy(500, EnemyType.IRON_REGENT, 0, 6)
        boss.boss_phase = 2
        healthy.combat.add_enemy(boss)
        perform_action(healthy, "shot", 0)
        self.assertEqual(healthy.hp, 50)
        self.assertIs(healthy.state, GameState.PLAYER_AIM)

        defeated = self.playing_world()
        boss = Enemy(500, EnemyType.IRON_REGENT, 0, 6)
        defeated.combat.add_enemy(boss)
        perform_action(defeated, "shot", 0)
        perform_action(defeated, "shot", 0)
        self.assertEqual(defeated.hp, 20)
        perform_action(defeated, "shot", 0)
        self.assertIs(defeated.state, GameState.GAME_OVER)
        self.assertEqual(defeated.death_cause,
                         "Iron Knight's heavy blow dealt the final damage.")

    def test_named_enemy_attack_and_defense_contact_are_specific(self):
        attacked = self.playing_world(hp=5)
        needleling = Enemy(23, EnemyType.NEEDLELING, 0, attacked.player_row)
        attacked.combat.add_enemy(needleling)
        perform_action(attacked, "shot", attacked.player_row)
        self.assertIs(attacked.state, GameState.GAME_OVER)
        self.assertEqual(attacked.death_cause,
                         "Cactus's needle attack dealt the final damage.")

        breached = self.playing_world(hp=5)
        slimer = Enemy(24, EnemyType.BASIC, 13, breached.player_row)
        breached.combat.add_enemy(slimer)
        perform_action(breached, "shot", breached.player_row)
        self.assertIs(breached.state, GameState.GAME_OVER)
        self.assertEqual(breached.death_cause,
                         "Slime's defense-line contact dealt the final damage.")

    def test_game_over_screen_separates_defeat_type_from_specific_cause(self):
        pygame.font.init()
        surface = pygame.Surface(LOGICAL_SIZE)
        renderer = ScreenRenderer()
        renderer._text = Mock(wraps=renderer._text)
        snapshot = self.playing_world().snapshot()
        from dataclasses import replace
        snapshot = replace(snapshot, state=GameState.GAME_OVER,
                           game_over_reason=GameOverReason.HP_DEPLETED,
                           death_cause="Iron Knight's heavy blow dealt the final damage.")

        renderer.terminal(surface, snapshot)
        displayed = [call.args[1] for call in renderer._text.call_args_list]
        self.assertIn("Player HP depleted", displayed)
        self.assertIn("Iron Knight's heavy blow dealt the final damage.", displayed)
        self.assertFalse(any("Doom" in text for text in displayed))


if __name__ == "__main__":
    unittest.main()
