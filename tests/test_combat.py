"""Plain-model tests for static enemies, death queues, and blue crystals."""

import unittest

from src.collision import Bounds
from src.combat import Combat
from src.entities import Crystal, Enemy, EnemyType, cell_bounds
from src.projectile import HitEvent


def hit(target_id: int, damage: int = 5) -> HitEvent:
    return HitEvent(1, target_id, damage, (300, 240), (1, 0))


class CombatTests(unittest.TestCase):
    def test_enemy_defaults_and_type_specific_future_score_values(self) -> None:
        for kind, score in ((EnemyType.BASIC, 100), (EnemyType.BOMB, 200)):
            with self.subTest(kind=kind):
                enemy = Enemy(1, kind, 2, 3)
                self.assertEqual((enemy.hp, enemy.max_hp, enemy.contact_damage), (5, 5, 5))
                self.assertEqual(enemy.score_value, score)
                self.assertTrue(enemy.alive)

    def test_grid_centers_and_full_cell_collision_bounds(self) -> None:
        for col, row in ((0, 0), (4, 3), (13, 7)):
            with self.subTest(cell=(col, row)):
                enemy = Enemy(1, EnemyType.BASIC, col, row)
                self.assertEqual(enemy.position, (120 + 48 * col, 96 + 48 * row))
                self.assertEqual(enemy.bounds, Bounds(96 + 48 * col, 72 + 48 * row,
                                                     144 + 48 * col, 120 + 48 * row))
                self.assertEqual(Crystal(2, col, row).bounds, enemy.bounds)

    def test_invalid_grid_ids_and_enemy_types_are_rejected(self) -> None:
        for col, row in ((-1, 0), (14, 0), (0, -1), (0, 8), (True, 0)):
            with self.subTest(cell=(col, row)), self.assertRaises(ValueError):
                cell_bounds(col, row)
        with self.assertRaises(ValueError):
            Enemy(0, EnemyType.BASIC, 0, 0)
        with self.assertRaises(ValueError):
            Enemy(1, "unknown", 0, 0)

    def test_damage_clamps_hp_and_reports_only_the_first_death(self) -> None:
        enemy = Enemy(1, EnemyType.BASIC, 0, 0)
        self.assertFalse(enemy.take_damage(2))
        self.assertEqual(enemy.hp, 3)
        self.assertTrue(enemy.take_damage(100))
        self.assertEqual(enemy.hp, 0)
        self.assertFalse(enemy.alive)
        self.assertFalse(enemy.take_damage(100))
        self.assertEqual(enemy.hp, 0)
        with self.assertRaises(ValueError):
            enemy.take_damage(-1)

    def test_repeated_lethal_hits_process_one_death_and_remove_target(self) -> None:
        enemy = Enemy(1, EnemyType.BASIC, 4, 3)
        combat = Combat(enemies={1: enemy})
        self.assertEqual(len(combat.targets()), 1)
        combat.handle_hit(hit(1))
        combat.handle_hit(hit(1))
        combat.resolve_deaths()
        self.assertEqual(enemy.hp, 0)
        self.assertEqual([event.enemy_id for event in combat.death_events], [1])
        self.assertEqual(combat.death_events[0].source, "projectile")
        self.assertEqual(combat.targets(), ())

    def test_bomb_death_chains_to_adjacent_bomb_once(self) -> None:
        combat = Combat(enemies={
            1: Enemy(1, EnemyType.BOMB, 4, 3),
            2: Enemy(2, EnemyType.BOMB, 5, 3),
            3: Enemy(3, EnemyType.BASIC, 6, 4),
        })
        combat.handle_hit(hit(1))
        self.assertTrue(all(not enemy.alive and enemy.hp == 0 for enemy in combat.enemies.values()))
        self.assertEqual([event.enemy_id for event in combat.death_events], [1, 2, 3])
        self.assertEqual([event.source for event in combat.death_events],
                         ["projectile", "explosion", "explosion"])
        combat.handle_hit(hit(2))
        combat.resolve_deaths()
        self.assertEqual(len(combat.death_events), 3)
        self.assertFalse(combat.pending_deaths)

    def test_explosion_hits_eight_neighbors_but_not_center_or_distance_two(self) -> None:
        combat = Combat(enemies={1: Enemy(1, EnemyType.BOMB, 5, 3)})
        neighbors = [(col, row) for row in range(2, 5) for col in range(4, 7)
                     if (col, row) != (5, 3)]
        for enemy_id, (col, row) in enumerate(neighbors, 2):
            combat.add_enemy(Enemy(enemy_id, EnemyType.BASIC, col, row))
        combat.add_enemy(Enemy(10, EnemyType.BASIC, 5, 3))
        combat.add_enemy(Enemy(11, EnemyType.BASIC, 7, 3))
        combat.apply_damage(1, 5)
        self.assertTrue(all(not combat.enemies[enemy_id].alive for enemy_id in range(1, 10)))
        self.assertTrue(combat.enemies[10].alive)
        self.assertTrue(combat.enemies[11].alive)

    def test_explosion_deals_exactly_ten_damage(self) -> None:
        bomb = Enemy(1, EnemyType.BOMB, 4, 3)
        neighbor = Enemy(2, EnemyType.BASIC, 5, 3)
        neighbor.hp = neighbor.max_hp = 15
        combat = Combat(enemies={1: bomb, 2: neighbor})
        combat.apply_damage(1, 5)
        self.assertEqual(neighbor.hp, 5)
        self.assertTrue(neighbor.alive)

    def test_corner_explosion_does_not_wrap_grid_edges(self) -> None:
        combat = Combat(enemies={
            1: Enemy(1, EnemyType.BOMB, 0, 0),
            2: Enemy(2, EnemyType.BASIC, 1, 0),
            3: Enemy(3, EnemyType.BASIC, 0, 1),
            4: Enemy(4, EnemyType.BASIC, 1, 1),
            5: Enemy(5, EnemyType.BASIC, 13, 0),
            6: Enemy(6, EnemyType.BASIC, 0, 7),
        })
        combat.apply_damage(1, 5)
        self.assertEqual([event.enemy_id for event in combat.death_events], [1, 2, 3, 4])
        self.assertTrue(combat.enemies[5].alive)
        self.assertTrue(combat.enemies[6].alive)

    def test_chain_order_is_fifo_and_independent_of_dictionary_insertion(self) -> None:
        entries = [(10, EnemyType.BOMB, 5, 3), (7, EnemyType.BOMB, 6, 3),
                   (2, EnemyType.BASIC, 5, 4), (1, EnemyType.BOMB, 7, 3),
                   (3, EnemyType.BASIC, 8, 4)]
        histories = []
        for order in (entries, list(reversed(entries))):
            combat = Combat(enemies={item[0]: Enemy(*item) for item in order})
            combat.apply_damage(10, 5)
            histories.append(combat.death_events)
        self.assertEqual(histories[0], histories[1])
        self.assertEqual([event.enemy_id for event in histories[0]], [10, 2, 7, 1, 3])

    def test_large_cyclic_bomb_chain_terminates_without_recursion_or_duplicates(self) -> None:
        combat = Combat(enemies={
            row * 14 + col + 1: Enemy(row * 14 + col + 1, EnemyType.BOMB, col, row)
            for row in range(8) for col in range(14)
        })
        combat.apply_damage(1, 5)
        self.assertEqual(len(combat.death_events), 112)
        self.assertEqual(len({event.enemy_id for event in combat.death_events}), 112)
        self.assertFalse(combat.pending_deaths)
        self.assertTrue(all(enemy.hp == 0 for enemy in combat.enemies.values()))

    def test_entity_ids_share_one_collision_namespace(self) -> None:
        combat = Combat(enemies={1: Enemy(1, EnemyType.BASIC, 0, 0)})
        with self.assertRaises(ValueError):
            combat.add_enemy(Enemy(1, EnemyType.BOMB, 1, 0))
        with self.assertRaises(ValueError):
            combat.add_crystal(Crystal(1, 1, 0))
        with self.assertRaises(ValueError):
            Combat(enemies={2: Enemy(1, EnemyType.BASIC, 0, 0)})

    def test_crystal_collects_once_without_damage_or_immediate_bp_application(self) -> None:
        enemy = Enemy(1, EnemyType.BASIC, 4, 3)
        crystal = Crystal(2, 5, 3)
        combat = Combat(enemies={1: enemy}, crystals={2: crystal})
        combat.handle_hit(hit(2, 0))
        combat.handle_hit(hit(2, 0))
        self.assertTrue(crystal.collected)
        self.assertFalse(crystal.collect())
        self.assertEqual(combat.pending_bp, 1)
        self.assertEqual(enemy.hp, 5)
        self.assertEqual(combat.death_events, [])
        self.assertEqual([target.target_id for target in combat.targets()], [1])

    def test_pending_crystals_apply_once_and_bp_is_capped(self) -> None:
        combat = Combat(crystals={index: Crystal(index, index, 3) for index in range(1, 7)})
        for index in range(1, 7):
            combat.handle_hit(hit(index, 0))
        self.assertEqual(combat.pending_bp, 6)
        self.assertEqual(combat.finish_shot(4), 5)
        self.assertEqual(combat.pending_bp, 0)
        self.assertEqual(combat.finish_shot(5), 5)


if __name__ == "__main__":
    unittest.main()
