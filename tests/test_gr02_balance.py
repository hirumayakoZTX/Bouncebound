"""Focused damage-balance tests and a legitimate Candidate B campaign route."""

import unittest

from src.combat import Combat
from src.constants import ORB_DAMAGE, ORB_RADIUS, ORB_SPEED
from src.entities import Crystal, ENEMY_STATS, Enemy, EnemyType
from src.offensive_spells import OFFENSIVE_DAMAGE
from src.projectile import HitEvent, Projectile
from src.spells import SpellId
from src.states import GameState
from src.world import World
from stage_one_fixtures import perform_action


STAGE_ONE_ROWS = (3, 3, 2, 2, 4, 2, 1, 5, 2, 5)
STAGE_TWO_ROWS = (3, 3, 2, 2, 4, 3, 1, 1, 5, 5, 3, 3, 3)
STAGE_THREE_ROWS = (3, 3, 3, 2, 2, 3, 4, 4, 5, 1, 1, 5, 5, 2, 2, 3, 3, 3)


def run_defended_campaign(schedule):
    """Play all stages using shots, then Ward/Reraise for Odin's last cycle."""
    world = World()
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)

    for row in STAGE_ONE_ROWS:
        perform_action(world, "shot", row, schedule)
    if world.state is not GameState.STAGE_CLEAR:
        return world, False
    if not world.advance_stage():
        return world, False
    world.transition_to(GameState.PLAYER_AIM)

    for row in STAGE_TWO_ROWS:
        perform_action(world, "shot", row, schedule)
    if world.state is not GameState.STAGE_CLEAR:
        return world, False
    if not world.advance_stage():
        return world, False
    world.transition_to(GameState.PLAYER_AIM)

    for row in STAGE_THREE_ROWS:
        perform_action(world, "shot", row, schedule)
    if world.state is not GameState.PLAYER_AIM or world.turn_index != 19:
        return world, False
    perform_action(world, "ward", 3, schedule)
    perform_action(world, "reraise", 3, schedule)
    perform_action(world, "shot", 3, schedule)
    if world.state is GameState.VICTORY:
        world.transition_to(GameState.RESULTS)
    return world, world.state is GameState.RESULTS


class DamageBalanceTests(unittest.TestCase):
    def test_candidate_b_values_are_authoritative_and_other_stats_are_unchanged(self):
        self.assertEqual((ENEMY_STATS[EnemyType.BOMB][0], ORB_DAMAGE, 10), (10, 4, 10))
        self.assertEqual(ENEMY_STATS[EnemyType.BASIC], (5, 0))
        self.assertEqual(OFFENSIVE_DAMAGE[SpellId.FIRE], 20)
        self.assertEqual(OFFENSIVE_DAMAGE[SpellId.STARSTORM], 10)
        self.assertEqual(OFFENSIVE_DAMAGE[SpellId.METEOR], 15)

    def test_three_valid_four_damage_hits_are_needed_to_destroy_a_full_bomb(self):
        bomb = Enemy(1, EnemyType.BOMB, 4, 3)
        combat = Combat({1: bomb})
        for expected_hp in (6, 2):
            combat.handle_hit(HitEvent(1, 1, ORB_DAMAGE, bomb.position, (1, 0)))
            self.assertEqual(bomb.hp, expected_hp)
            self.assertEqual(combat.death_events, [])
        combat.handle_hit(HitEvent(1, 1, ORB_DAMAGE, bomb.position, (1, 0)))
        self.assertEqual(bomb.hp, 0)
        self.assertEqual([event.enemy_id for event in combat.death_events], [1])

    def test_single_real_bomb_explosion_kills_adjacent_full_bomb_once(self):
        source = Enemy(1, EnemyType.BOMB, 4, 3)
        source.hp = 4  # Earlier direct hits leave it one orb impact from defeat.
        neighbor = Enemy(2, EnemyType.BOMB, 5, 3)
        crystal = Crystal(3, 5, 4)
        combat = Combat({1: source, 2: neighbor}, {3: crystal})
        combat.handle_hit(HitEvent(1, 1, ORB_DAMAGE, source.position, (1, 0)))
        self.assertEqual((source.hp, neighbor.hp), (0, 0))
        self.assertEqual([(event.enemy_id, event.source) for event in combat.death_events],
                         [(1, "projectile"), (2, "explosion")])
        self.assertFalse(crystal.collected)
        self.assertEqual(combat.pending_bp, 0)
        combat.resolve_deaths()
        self.assertEqual(len(combat.death_events), 2)

    def test_projectile_geometry_and_speed_are_unchanged(self):
        orb = Projectile.launch(1, (808, 240), (96, 240))
        self.assertEqual((orb.damage, orb.radius, orb.max_hits, orb.max_lifetime),
                         (4, ORB_RADIUS, 12, 5.0))
        self.assertAlmostEqual((orb.velocity[0] ** 2 + orb.velocity[1] ** 2) ** 0.5,
                               ORB_SPEED)

    def test_hybrid_scheduler_waits_for_a_wounded_bomb_to_die(self):
        from src.stage_config import parse_stage

        definition = parse_stage({
            "schema_version": 1,
            "stage": 1,
            "capacity": 25,
            "waves": [
                {"turn": 1, "spawns": [{"id": 1, "kind": "bomb", "col": 4, "row": 3}]},
                {"turn": 3, "spawns": [{"id": 2, "kind": "basic", "col": 0, "row": 3}]},
            ],
            "completion": {"mandatory_enemy_ids": [1, 2], "final": False},
        })
        world = World(encounter=definition)
        world.start_new_run()
        world.transition_to(GameState.PLAYER_AIM)
        world.set_aim_target((96, 240))
        self.assertTrue(world.fire())
        self.assertEqual(world.projectiles[0].damage, 4)
        world.projectiles[0].max_hits = 1
        elapsed = 0.0
        while world.state is GameState.SHOT_ANIMATION and elapsed < 6.0:
            world.advance_time(0.05)
            elapsed += 0.05
        self.assertEqual(world.enemies[1].hp, 6)
        self.assertTrue(world.resolve_turn())
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual(world.encounter.spawned_waves, {0})
        self.assertNotIn(2, world.enemies)

    def test_stage_retry_restores_a_fresh_candidate_b_bomb(self):
        from stage_two_fixtures import definition, playing

        world = playing(definition((1, "bomb", 4, 3), boss=(100, 7, 3)))
        self.assertEqual((world.stage, world.enemies[1].hp, world.enemies[1].max_hp),
                         (2, 10, 10))
        world.combat.apply_damage(1, 4)
        self.assertEqual(world.enemies[1].hp, 6)
        world.apply_player_damage(100)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertTrue(world.retry_current_stage())
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.stage, world.turn_index), (2, 1))
        self.assertTrue(world.transition_to(GameState.PLAYER_AIM))
        self.assertEqual((world.enemies[1].hp, world.enemies[1].max_hp), (10, 10))
        self.assertEqual(world.encounter.spawned_waves, {0})
        self.assertEqual(world.combat.death_events, [])

    def test_candidate_b_full_campaign_is_frame_schedule_invariant_and_winnable(self):
        schedules = (
            (1 / 30,),
            (1 / 60,),
            (1 / 144,),
            (0.003, 0.071, 0.19, 0.016, 0.11),
        )
        results = []
        for schedule in schedules:
            with self.subTest(schedule=schedule):
                world, completed = run_defended_campaign(schedule)
                self.assertTrue(completed, (world.stage, world.turn_index, world.hp,
                                            world.mp, world.bp, world.state))
                self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp),
                                 (3, 21, 50, 20, 5))
                self.assertEqual(len(world.combat.death_events), 40)
                results.append((world.stage, world.turn_index, world.hp, world.mp, world.bp,
                                tuple(world.encounter.spawn_history),
                                tuple(world.combat.death_events), tuple(world.status_events)))
        self.assertTrue(all(result == results[0] for result in results[1:]))


if __name__ == "__main__":
    unittest.main()
