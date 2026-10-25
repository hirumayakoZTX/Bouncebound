"""Physics/combat synchronization, multi-orb shots, and immutable display data."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from math import atan2, degrees, hypot
import os
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from src.collision import Bounds
from src.constants import LOGICAL_SIZE, PHYSICS_STEP
from src.entities import Crystal, Enemy, EnemyType
from src.projectile import HitEvent, Projectile, firing_velocities
from src.renderer import Renderer
from src.states import GameState
from src.world import World


class CombatIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World(demo=False)
        self.world.start_new_run()
        self.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self) -> None:
        pygame.quit()

    def finish_shot(self) -> None:
        for _ in range(21):
            self.world.advance_time(0.25)
        self.assertIs(self.world.state, GameState.TURN_RESOLVE)

    def install_orbs(self, orbs: list[Projectile]) -> None:
        self.world.set_aim_target((96, 240))
        self.assertTrue(self.world.fire())
        self.world.projectiles = orbs

    def test_projectile_damage_kills_and_disables_target_immediately(self) -> None:
        enemy = Enemy(1, EnemyType.BASIC, 4, 3)
        self.world.combat.add_enemy(enemy)
        orb = Projectile(1, (343, 240), (-520, 0))
        self.install_orbs([orb])
        events = self.world.advance_time(PHYSICS_STEP)
        self.assertEqual([(event.target_id, event.damage) for event in events], [(1, 5)])
        self.assertEqual(enemy.hp, 0)
        self.assertEqual(self.world.combat.targets(), ())
        self.assertEqual(self.world.snapshot().enemies, ())
        self.assertEqual(orb.hits, 1)

    def test_same_step_orbs_use_stable_ids_and_skip_an_enemy_killed_by_first_orb(self) -> None:
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.world.start_new_run()
                self.world.transition_to(GameState.PLAYER_AIM)
                self.world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 4, 3))
                orbs = [Projectile(index, (343, 240), (-520, 0)) for index in (1, 2)]
                self.install_orbs(list(reversed(orbs)) if reverse else orbs)
                events = self.world.advance_time(PHYSICS_STEP)
                self.assertEqual([event.projectile_id for event in events], [1])
                self.assertEqual(orbs[0].velocity, (520, 0))
                self.assertEqual(orbs[1].velocity, (-520, 0))
                self.assertEqual([orb.hits for orb in orbs], [1, 0])
                self.assertEqual(len(self.world.combat.death_events), 1)

    def test_dead_enemy_is_not_reused_by_later_substeps_in_the_same_frame(self) -> None:
        self.world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 4, 3))
        orb = Projectile(1, (343, 240), (-520, 0), arena=Bounds(280, 200, 380, 280))
        self.install_orbs([orb])
        events = self.world.advance_time(0.25)
        self.assertEqual(len(events), 1)
        self.assertEqual(orb.hits, 1)
        self.assertAlmostEqual(orb.position[0], 301)

    def test_bomb_chain_removes_targets_even_within_one_orb_substep(self) -> None:
        for enemy in (Enemy(1, EnemyType.BOMB, 4, 3), Enemy(2, EnemyType.BOMB, 5, 3)):
            self.world.combat.add_enemy(enemy)
        orb = Projectile(1, (281, 240), (100_000, 0))
        self.install_orbs([orb])
        events = self.world.advance_time(PHYSICS_STEP)
        self.assertEqual([event.target_id for event in events], [1])
        self.assertEqual(orb.hits, 1)
        self.assertAlmostEqual(orb.position[0], 758 + 1 / 3)
        self.assertTrue(all(not enemy.alive for enemy in self.world.enemies.values()))

    def test_simultaneous_contacts_skip_a_neighbor_killed_by_the_first_bomb(self) -> None:
        self.world.combat.add_enemy(Enemy(1, EnemyType.BOMB, 4, 3))
        self.world.combat.add_enemy(Enemy(2, EnemyType.BOMB, 4, 4))
        orb = Projectile(1, (281, 264), (520, 0))
        self.install_orbs([orb])
        events = self.world.advance_time(PHYSICS_STEP)
        self.assertEqual([event.target_id for event in events], [1])
        self.assertEqual(orb.hits, 1)
        self.assertEqual([event.enemy_id for event in self.world.combat.death_events], [1, 2])

    def test_sustained_contact_does_not_repeat_damage_and_return_after_separation_can_hit(self) -> None:
        enemy = Enemy(1, EnemyType.BASIC, 4, 3)
        enemy.hp = enemy.max_hp = 15
        self.world.combat.add_enemy(enemy)
        orb = Projectile(1, (343 + 520 * PHYSICS_STEP, 240), (-520, 0))
        self.install_orbs([orb])
        self.world.advance_time(PHYSICS_STEP)
        self.assertEqual(enemy.hp, 10)
        orb.velocity = (0, 0)
        self.world.advance_time(0.1)
        self.assertEqual(enemy.hp, 10)
        orb.velocity = (520, 0)
        for _ in range(8):
            self.world.advance_time(0.25)
        self.assertEqual(enemy.hp, 5)
        self.assertEqual(orb.hits, 2)

    def test_false_positive_contact_fix_still_prevents_combat_damage(self) -> None:
        enemy = Enemy(1, EnemyType.BASIC, 4, 3)
        self.world.combat.add_enemy(enemy)
        orb = Projectile(1, (343, 240), (520, 0))
        self.install_orbs([orb])
        self.assertEqual(self.world.advance_time(PHYSICS_STEP), ())
        self.assertEqual(enemy.hp, 5)
        self.assertEqual(orb.hits, 0)

    def test_bombs_never_change_player_resources_or_collect_crystals(self) -> None:
        self.world.hp, self.world.mp = 78, 40
        self.world.combat.add_enemy(Enemy(1, EnemyType.BOMB, 13, 3))
        self.world.combat.add_enemy(Enemy(2, EnemyType.BOMB, 12, 3))
        self.world.combat.add_crystal(Crystal(3, 12, 4))
        self.world.combat.apply_damage(1, 5)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp,
                          self.world.turn_index, self.world.pending_bp), (78, 40, 1, 1, 0))
        self.assertFalse(self.world.crystals[3].collected)

    def test_two_orbs_collect_one_crystal_once_without_reflection_or_hit_cost(self) -> None:
        self.world.combat.add_crystal(Crystal(1, 4, 3))
        orbs = [Projectile(index, (343, 240), (-520, 0)) for index in (1, 2)]
        self.install_orbs(orbs)
        events = self.world.advance_time(PHYSICS_STEP)
        self.assertEqual([(event.projectile_id, event.damage) for event in events], [(1, 0)])
        self.assertEqual([orb.velocity for orb in orbs], [(-520, 0), (-520, 0)])
        self.assertEqual([orb.hits for orb in orbs], [0, 0])
        self.assertEqual(self.world.pending_bp, 1)
        self.assertEqual(self.world.bp, 1)
        self.finish_shot()
        self.assertEqual(self.world.bp, 2)
        self.assertEqual(self.world.pending_bp, 0)

    def test_collected_bp_only_changes_the_next_shot_count(self) -> None:
        self.world.combat.add_crystal(Crystal(1, 11, 3))
        self.world.set_aim_target((96, 240))
        self.world.fire()
        self.world.advance_time(0.25)
        self.assertEqual(self.world.bp, 1)
        self.assertEqual(self.world.pending_bp, 1)
        self.assertEqual(len(self.world.projectiles), 1)
        self.finish_shot()
        self.assertEqual(self.world.bp, 2)
        self.assertTrue(self.world.resolve_turn())
        self.assertTrue(self.world.fire())
        self.assertEqual([orb.projectile_id for orb in self.world.projectiles], [2, 3])
        self.assertEqual(self.world.bp, 2)
        self.finish_shot()
        self.assertEqual(self.world.bp, 2)
        self.assertEqual(self.world.turn_index, 2)

    def test_requested_fans_have_correct_counts_symmetry_speed_and_unique_ids(self) -> None:
        expected = {1: [0], 2: [-2.5, 2.5], 3: [-5, 0, 5],
                    4: [-7.5, -2.5, 2.5, 7.5], 5: [-10, -5, 0, 5, 10]}
        for bp, angles in expected.items():
            with self.subTest(bp=bp):
                world = World(demo=False)
                world.start_new_run()
                world.transition_to(GameState.PLAYER_AIM)
                world.bp = bp
                world.set_aim_target((96, 240))
                self.assertTrue(world.fire())
                self.assertEqual(len(world.projectiles), bp)
                self.assertEqual(len({orb.projectile_id for orb in world.projectiles}), bp)
                for orb, angle in zip(world.projectiles, angles):
                    self.assertAlmostEqual(hypot(*orb.velocity), 520)
                    self.assertAlmostEqual(degrees(atan2(orb.velocity[1], -orb.velocity[0])), angle)
                self.assertEqual(world.bp, bp)

    def test_steep_fans_remain_symmetric_leftward_and_enter_the_arena(self) -> None:
        for row, target in ((0, (768, 456)), (7, (768, 72))):
            with self.subTest(row=row):
                world = World(demo=False)
                world.start_new_run()
                world.transition_to(GameState.PLAYER_AIM)
                world.player_row, world.bp = row, 5
                world.set_aim_target(target)
                world.fire()
                angles = [atan2(orb.velocity[1], -orb.velocity[0]) for orb in world.projectiles]
                center = atan2(target[1] - world.aim_origin[1], world.aim_origin[0] - target[0])
                self.assertAlmostEqual(sum(angles) / 5, center)
                self.assertAlmostEqual(angles[0] + angles[-1], 2 * center)
                self.assertTrue(all(orb.velocity[0] < 0 for orb in world.projectiles))
                for _ in range(8):
                    world.advance_time(0.25)
                self.assertTrue(all(orb.entered_arena for orb in world.projectiles))

    def test_invalid_bp_does_not_create_a_fan(self) -> None:
        for bp in (0, 6, 1.5, True):
            with self.subTest(bp=bp), self.assertRaises(ValueError):
                firing_velocities((808, 240), (300, 240), bp)

    def test_orb_lifetimes_and_pending_bp_wait_for_the_last_orb(self) -> None:
        self.world.bp = 5
        self.world.set_aim_target((96, 240))
        self.world.fire()
        self.world.combat.add_crystal(Crystal(1, 4, 3))
        self.world.combat.handle_hit(HitEvent(1, 1, 0, (300, 240), (1, 0)))
        for index, orb in enumerate(self.world.projectiles):
            orb.max_lifetime = PHYSICS_STEP if index < 4 else 0.1
        self.world.advance_time(PHYSICS_STEP)
        self.assertEqual(len(self.world.projectiles), 1)
        self.assertEqual(self.world.pending_bp, 1)
        self.assertIs(self.world.state, GameState.SHOT_ANIMATION)
        self.world.advance_time(0.1)
        self.assertIs(self.world.state, GameState.TURN_RESOLVE)
        self.assertEqual(self.world.bp, 5)
        self.assertEqual(self.world.pending_bp, 0)

    def test_demo_shot_chains_bombs_collects_crystal_and_preserves_turn_boundary(self) -> None:
        world = World(demo=True)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.set_aim_target((96, 240))
        world.fire()
        for _ in range(20):
            world.advance_time(0.25)
        self.assertIs(world.state, GameState.TURN_RESOLVE)
        self.assertEqual(len(world.combat.death_events), 3)
        self.assertEqual(world.snapshot().enemies, ())
        self.assertEqual(world.snapshot().crystals, ())
        self.assertEqual((world.bp, world.hp, world.mp, world.turn_index), (2, 100, 100, 1))
        self.assertFalse(world.fire())
        world.advance_time(1)
        self.assertIs(world.state, GameState.TURN_RESOLVE)

    def test_hit_limit_finishes_only_after_bomb_queue_and_pending_bp_are_resolved(self) -> None:
        world = World(demo=True)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.set_aim_target((96, 240))
        world.fire()
        world.projectiles[0].max_hits = 1
        for _ in range(4):
            world.advance_time(0.25)
        self.assertIs(world.state, GameState.TURN_RESOLVE)
        self.assertEqual(world.projectiles, [])
        self.assertEqual([event.enemy_id for event in world.combat.death_events], [2, 3])
        self.assertFalse(world.combat.pending_deaths)
        self.assertTrue(world.enemies[1].alive)
        self.assertEqual((world.bp, world.pending_bp, world.turn_index), (2, 0, 1))

    def test_reset_restores_fresh_demo_and_clears_all_pending_effects(self) -> None:
        world = World(demo=True)
        original = world.snapshot()
        world.combat.apply_damage(2, 5)
        world.crystals[4].collect()
        world.combat.pending_bp, world.bp = 2, 4
        world.reset()
        self.assertEqual(world.snapshot(), original)
        self.assertEqual(world.combat.death_events, [])
        self.assertFalse(world.combat.pending_deaths)
        self.assertEqual(world.pending_bp, 0)

    def test_rendering_snapshots_are_detached_frozen_and_do_not_mutate_combat(self) -> None:
        world = World()
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        snapshot = world.snapshot()
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        before = deepcopy(vars(world))
        renderer.draw(screen, snapshot)
        self.assertEqual(vars(world), before)
        world.combat.apply_damage(1, 5)
        self.assertEqual(snapshot.enemies[0].hp, 5)
        with self.assertRaises(FrozenInstanceError):
            snapshot.enemies[0].hp = 0
        with self.assertRaises(FrozenInstanceError):
            snapshot.crystals[0].grid_row = 0


if __name__ == "__main__":
    unittest.main()
