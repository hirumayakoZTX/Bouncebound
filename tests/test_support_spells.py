"""Cure, Cleanse, and Ward use the shared resource and status systems."""

import unittest

from src.entities import Enemy, EnemyType
from src.spells import SpellFailure
from src.states import GameState
from src.statuses import StatusEffect, StatusKind
from src.world import World


def caster():
    world = World(demo=False)
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    world.hp = 75
    return world


class SupportSpellTests(unittest.TestCase):
    def test_mend_restores_at_most_fifty_hp_and_reports_the_actual_amount(self):
        for hp, expected, healed in ((30, 80, 50), (80, 100, 20), (99, 100, 1)):
            world = caster()
            world.hp = hp
            result = world.execute_support_spell("mend-action", "mend")
            self.assertTrue(result.valid)
            self.assertEqual((world.hp, world.mp), (expected, 90))
            self.assertEqual(result.effects.healed, healed)

    def test_full_hp_mend_is_free_and_does_not_reserve_the_action_id(self):
        world = caster()
        world.hp = 100
        rejected = world.execute_support_spell("mend-action", "mend")
        self.assertIs(rejected.failure, SpellFailure.FULL_HP)
        self.assertEqual(world.mp, 100)
        world.hp = 90
        accepted = world.execute_support_spell("mend-action", "mend")
        self.assertTrue(accepted.valid)
        self.assertEqual(world.mp, 90)

    def test_cleanse_unlocks_in_stage_two_and_removes_only_poison(self):
        world = caster()
        world.apply_status(StatusKind.POISON, 3)
        locked = world.execute_support_spell("cleanse-action", "cleanse")
        self.assertIs(locked.failure, SpellFailure.STAGE_LOCKED)
        self.assertEqual(world.mp, 100)
        world.stage = 2
        world.statuses.put(StatusEffect(StatusKind.WARD, 1, world.turn_index,
                                        "fixture", charges=1))
        result = world.execute_support_spell("cleanse-action", "cleanse")
        self.assertTrue(result.valid)
        self.assertEqual([item.kind for item in result.effects.removed],
                         [StatusKind.POISON])
        self.assertIsNotNone(world.statuses.get(StatusKind.WARD))
        self.assertEqual(world.mp, 80)

    def test_barrier_grants_one_ward_that_blocks_one_damage_event(self):
        world = caster()
        result = world.execute_support_spell("barrier-action", "barrier")
        self.assertTrue(result.valid)
        self.assertEqual(result.effects.granted.kind, StatusKind.WARD)
        self.assertEqual(world.apply_player_damage(0), 0)
        self.assertEqual(world.apply_player_damage(7), 0)
        self.assertEqual(world.hp, 75)
        self.assertEqual(world.apply_player_damage(7), 7)
        self.assertEqual(world.hp, 68)

    def test_support_actions_preserve_combat_and_are_idempotent(self):
        world = caster()
        world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 4, 3))
        before = (world.enemies[1].hp, world.enemies[1].grid_col,
                  tuple(world.combat.death_events))
        self.assertTrue(world.execute_support_spell("barrier-action", "barrier").valid)
        duplicate = world.execute_support_spell("barrier-action", "barrier")
        self.assertIs(duplicate.failure, SpellFailure.ALREADY_COMMITTED)
        self.assertEqual((world.enemies[1].hp, world.enemies[1].grid_col,
                          tuple(world.combat.death_events)), before)
        self.assertEqual(world.mp, 70)


if __name__ == "__main__":
    unittest.main()
