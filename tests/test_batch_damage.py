"""Simultaneous direct damage before the established FIFO Bomb death pipeline."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

from src.combat import Combat
from src.entities import Crystal, Enemy, EnemyType


def enemy(enemy_id, col, row, *, kind=EnemyType.BASIC, hp=50):
    target = Enemy(enemy_id, kind, col, row)
    target.hp = target.max_hp = hp
    return target


class BatchDamageTests(unittest.TestCase):
    def test_direct_damage_is_sorted_and_duplicate_ids_are_applied_once(self):
        combat = Combat(enemies={i: enemy(i, i, 3) for i in (3, 1, 2)})
        result = combat.apply_damage_batch((i for i in (3, 1, 3, 2, 1)), 10)
        self.assertEqual([(c.enemy_id, c.hp_before, c.hp_after, c.direct_damage,
                           c.explosion_damage) for c in result.changes],
                         [(1, 50, 40, 10, 0), (2, 50, 40, 10, 0), (3, 50, 40, 10, 0)])
        self.assertEqual(result.deaths, ())

    def test_all_direct_damage_and_initial_deaths_exist_before_queue_drain(self):
        combat = Combat(enemies={
            3: enemy(3, 6, 4, kind=EnemyType.BOMB, hp=10),
            2: enemy(2, 6, 3, hp=15),
            1: enemy(1, 5, 3, kind=EnemyType.BOMB, hp=10),
        })
        drain = combat.resolve_deaths
        def observe():
            self.assertEqual([combat.enemies[i].hp for i in (1, 2, 3)], [0, 5, 0])
            self.assertEqual([(e.enemy_id, e.source) for e in combat.pending_deaths],
                             [(1, 'spell:starstorm'), (3, 'spell:starstorm')])
            drain()
        with patch.object(combat, 'resolve_deaths', side_effect=observe) as resolver:
            result = combat.apply_damage_batch((3, 2, 1), 10, 'spell:starstorm')
            resolver.assert_called_once_with()
        self.assertEqual([(e.enemy_id, e.source) for e in result.deaths],
                         [(1, 'spell:starstorm'), (3, 'spell:starstorm'), (2, 'explosion')])
        self.assertEqual([(c.enemy_id, c.direct_damage, c.explosion_damage)
                          for c in result.changes], [(1, 10, 0), (2, 10, 5), (3, 10, 0)])
        self.assertFalse(combat.pending_deaths)

    def test_all_initial_direct_kills_precede_new_chain_deaths(self):
        combat = Combat(enemies={
            8: enemy(8, 5, 3, kind=EnemyType.BOMB, hp=10),
            5: enemy(5, 6, 3, hp=5),
            10: enemy(10, 6, 4, kind=EnemyType.BOMB, hp=10),
            1: enemy(1, 4, 3, hp=5),
        })
        result = combat.apply_damage_batch((10, 8, 5), 10, 'spell:starstorm')
        self.assertEqual([(e.enemy_id, e.source) for e in result.deaths],
                         [(5, 'spell:starstorm'), (8, 'spell:starstorm'),
                          (10, 'spell:starstorm'), (1, 'explosion')])

    def test_nonlethal_explosion_damage_is_included_in_detached_result(self):
        combat = Combat(enemies={1: enemy(1, 5, 3, kind=EnemyType.BOMB, hp=10),
                                 2: enemy(2, 4, 3)})
        result = combat.apply_damage_batch((1,), 20, 'spell:fire')
        change = next(c for c in result.changes if c.enemy_id == 2)
        self.assertEqual((change.hp_before, change.hp_after, change.direct_damage,
                          change.explosion_damage), (50, 40, 0, 10))
        combat.enemies[2].take_damage(10)
        self.assertEqual(change.hp_after, 40)
        with self.assertRaises(FrozenInstanceError):
            result.changes = ()
        with self.assertRaises(FrozenInstanceError):
            change.hp_after = 0
        with self.assertRaises(FrozenInstanceError):
            result.deaths[0].source = 'changed'

    def test_dead_escaped_unknown_and_crystal_ids_are_ignored(self):
        dead = enemy(2, 6, 3, hp=5)
        dead.take_damage(5)
        escaped = enemy(3, 13, 3, kind=EnemyType.BOMB, hp=10)
        escaped.escape(2)
        combat = Combat(enemies={1: enemy(1, 5, 3), 2: dead, 3: escaped},
                        crystals={4: Crystal(4, 5, 3)})
        result = combat.apply_damage_batch((1, 2, 3, 4, 99), 10)
        self.assertEqual([c.enemy_id for c in result.changes], [1])
        self.assertEqual((dead.hp, escaped.hp, escaped.escape_turn), (0, 10, 2))
        self.assertFalse(combat.crystals[4].collected)
        self.assertEqual(combat.pending_bp, 0)
        self.assertEqual(result.deaths, ())

    def test_hp_clamps_and_repeated_lethal_batches_do_not_repeat_deaths(self):
        combat = Combat(enemies={1: enemy(1, 5, 3, hp=5)})
        first = combat.apply_damage_batch((1,), 20, 'spell:fire')
        before = deepcopy(combat)
        repeated = combat.apply_damage_batch((1,), 20, 'spell:fire')
        self.assertEqual(combat.enemies[1].hp, 0)
        self.assertEqual(first.changes[0].direct_damage, 5)
        self.assertEqual(len(first.deaths), 1)
        self.assertEqual((repeated.changes, repeated.deaths), ((), ()))
        self.assertEqual(combat, before)

    def test_result_contains_only_new_deaths_and_preserves_prior_archives(self):
        combat = Combat(enemies={1: enemy(1, 5, 3, hp=5), 9: enemy(9, 0, 0, hp=5)})
        combat.apply_damage(9, 5, 'projectile')
        old = combat.death_events[0]
        result = combat.apply_damage_batch((9, 1), 20, 'spell:fire')
        self.assertEqual([e.enemy_id for e in result.deaths], [1])
        self.assertIs(combat.death_events[0], old)
        self.assertEqual(set(combat.enemies), {1, 9})

    def test_invalid_damage_and_late_invalid_ids_leave_the_whole_batch_unchanged(self):
        combat = Combat(enemies={1: enemy(1, 5, 3)})
        for amount, ids in ((-1, (1,)), (True, (1,)), (1.5, (1,)),
                            (10, (1, 0)), (10, (1, True)), (10, (1, '2'))):
            with self.subTest(amount=amount, ids=ids):
                before = deepcopy(combat)
                with self.assertRaises(ValueError):
                    combat.apply_damage_batch(ids, amount)
                self.assertEqual(combat, before)

    def test_empty_and_zero_damage_batches_are_safe(self):
        combat = Combat(enemies={1: enemy(1, 5, 3)})
        before = deepcopy(combat)
        for ids, amount in (((), 10), ((1,), 0)):
            result = combat.apply_damage_batch(ids, amount)
            self.assertEqual((result.changes, result.deaths), ((), ()))
            self.assertEqual(combat, before)

    def test_batch_and_chain_results_are_independent_of_dictionary_and_input_order(self):
        results = []
        for order, targets in (((1, 2, 3, 4, 5), (3, 1, 2)),
                               ((5, 4, 3, 2, 1), (2, 3, 1)),
                               ((3, 5, 2, 1, 4), (1, 2, 3))):
            values = {1: enemy(1, 5, 3, kind=EnemyType.BOMB, hp=10),
                      2: enemy(2, 6, 3, hp=15),
                      3: enemy(3, 6, 4, kind=EnemyType.BOMB, hp=10),
                      4: enemy(4, 4, 3),
                      5: enemy(5, 4, 4, kind=EnemyType.BOMB, hp=10)}
            combat = Combat(enemies={i: values[i] for i in order})
            result = combat.apply_damage_batch(targets, 10, 'spell:starstorm')
            results.append(result)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        self.assertEqual([e.enemy_id for e in results[0].deaths], [1, 3, 2, 5])


if __name__ == '__main__':
    unittest.main()
