"""Score ownership, action boundaries, retry policy, and campaign regression."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import os
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

from src.encounter import EncounterDefinition, Spawn, Wave
from src.entities import Enemy, EnemyType
from src.projectile import HitEvent
from src.scoring import ScoreBreakdown, ScoreManager
from src.states import GameState
from src.statuses import StatusKind
from src.world import World
from stage_one_fixtures import OPENING_ROWS, perform_action
from stage_two_fixtures import definition, playing
from test_gr02_balance import STAGE_ONE_ROWS, STAGE_TWO_ROWS, STAGE_THREE_ROWS, run_defended_campaign


def encounter(*spawns):
    return EncounterDefinition(1, (Wave(1, tuple(Spawn(*spawn) for spawn in spawns)),))


def start(config):
    world = World(encounter=config)
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    return world


class ScoringTests(unittest.TestCase):
    def test_existing_enemy_categories_and_once_only_deaths(self):
        score = ScoreManager()
        for index, kind in enumerate(EnemyType, 1):
            enemy = Enemy(index, kind, 0, 0)
            expected = 100 if kind is EnemyType.BASIC else 1000 if enemy.is_boss else 200
            self.assertEqual(enemy.score_value, expected)
            score.record_death(index, enemy.score_value, 'projectile')
            score.record_death(index, enemy.score_value, 'explosion')
        self.assertEqual(score.snapshot().breakdown.defeats,
                         sum(100 if k is EnemyType.BASIC else 1000 if Enemy(i, k, 0, 0).is_boss
                             else 200 for i, k in enumerate(EnemyType, 1)))
        self.assertEqual(score.snapshot().breakdown.chains, 0)
        self.assertEqual(len(score.snapshot().events), len(EnemyType))

    def test_fire_bomb_chain_scores_real_death_causes_once(self):
        world = start(encounter((1, 'bomb', 6, 3), (2, 'bomb', 5, 3), (3, 'basic', 5, 4)))
        self.assertTrue(world.select_spell('ember_lance'))
        self.assertTrue(world.cast_selected_spell().valid)
        snap = world.snapshot().score
        self.assertEqual(snap.breakdown, ScoreBreakdown(500, 100, 0, 0))
        self.assertEqual([(e.enemy_id, e.source) for e in world.combat.death_events],
                         [(1, 'spell:ember_lance'), (2, 'explosion'), (3, 'explosion')])
        world._sync_score_deaths()
        self.assertEqual(world.snapshot().score, snap)
        world.advance_time(.45)
        self.assertTrue(world.resolve_turn())
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual(world.snapshot().score.breakdown, ScoreBreakdown(500, 100, 0, 21500))
        self.assertFalse(world.resolve_turn())
        self.assertEqual(world.snapshot().score.total, 22100)

    def test_skyfall_scores_actual_stage_three_multi_kills(self):
        world = World(demo=False)
        world.start_new_run(); world.transition_to(GameState.PLAYER_AIM)
        world.stage = 3
        for i, col in enumerate((6, 7, 8), 1):
            world.combat.add_enemy(Enemy(i, EnemyType.BASIC, col, 3))
        self.assertTrue(world.select_spell('skyfall'))
        self.assertTrue(world.cast_selected_spell().valid)
        self.assertEqual(world.snapshot().score.breakdown.defeats, 300)
        self.assertEqual(world.snapshot().score.breakdown.combos, 0)
        world.advance_time(.45)
        self.assertTrue(world.resolve_turn())
        self.assertEqual(world.snapshot().score.breakdown.defeats, 300)

    def test_two_orbs_hit_one_enemy_without_duplicate_death_points(self):
        world = World(demo=False)
        world.start_new_run(); world.transition_to(GameState.PLAYER_AIM)
        enemy = Enemy(1, EnemyType.BASIC, 4, 3)
        world.combat.add_enemy(enemy)
        world.set_aim_target((96, 240)); self.assertTrue(world.fire())
        for projectile_id in (1, 2, 3):
            world._handle_projectile_hit(HitEvent(projectile_id, 1, 4, enemy.position, (1, 0)))
        self.assertEqual(len(world.combat.death_events), 1)
        self.assertEqual(world.snapshot().score.breakdown.defeats, 100)
        self.assertEqual(len(world.snapshot().score.events), 1)

    def test_combo_counts_distinct_direct_contacts_only_at_volley_completion(self):
        world = World(demo=False)
        world.start_new_run(); world.transition_to(GameState.PLAYER_AIM)
        for i in (1, 2, 3):
            enemy = Enemy(i, EnemyType.BASIC, i, 3)
            enemy.hp = enemy.max_hp = 100
            world.combat.add_enemy(enemy)
        world.set_aim_target((96, 240)); self.assertTrue(world.fire())
        def hit(target):
            world._handle_projectile_hit(HitEvent(1, target, 4, (200, 240), (1, 0)))
        for target in (1, 1, 2): hit(target)
        self.assertEqual(world.snapshot().score.breakdown.combos, 0)
        hit(3)
        self.assertEqual(world.snapshot().score.breakdown.combos, 0)
        world.projectiles[0].max_lifetime = .001
        world.advance_time(.1)
        self.assertEqual(world.snapshot().score.breakdown.combos, 100)
        self.assertTrue(world.resolve_turn())
        self.assertEqual(world.snapshot().score.breakdown.combos, 100)

    def test_fewer_than_three_distinct_hits_never_earns_combo(self):
        score = ScoreManager()
        score.complete_shot('a', {1, 2})
        score.complete_shot('b', {1})
        score.complete_shot('a', {1, 2, 3})
        self.assertEqual(score.snapshot().total, 0)
        score.complete_shot('c', {1, 2, 3, 4})
        score.complete_shot('c', {1, 2, 3, 4})
        self.assertEqual(score.snapshot().breakdown.combos, 100)

    def test_explosion_splash_is_not_a_direct_shot_combo(self):
        world = World(demo=False)
        world.start_new_run(); world.transition_to(GameState.PLAYER_AIM)
        for enemy in (Enemy(1, EnemyType.BOMB, 6, 3), Enemy(2, EnemyType.BOMB, 5, 3),
                      Enemy(3, EnemyType.BASIC, 5, 4)):
            world.combat.add_enemy(enemy)
        world.enemies[1].hp = 4
        world.set_aim_target((96, 240)); self.assertTrue(world.fire())
        world._handle_projectile_hit(HitEvent(1, 1, 4, world.enemies[1].position, (1, 0)))
        self.assertEqual(world.snapshot().score.breakdown, ScoreBreakdown(500, 100, 0, 0))
        world.projectiles[0].max_lifetime = .001
        world.advance_time(.1)
        self.assertEqual(world.snapshot().score.breakdown.combos, 0)

    def test_full_resources_and_no_damage_bonus_finalize_once(self):
        world = start(encounter((1, 'basic', 7, 3)))
        perform_action(world, 'shot', 3)
        self.assertEqual(world.snapshot().score.breakdown, ScoreBreakdown(100, 0, 0, 24500))
        before = world.snapshot().score
        self.assertFalse(world.resolve_turn())
        world.score.finalize_stage(100, 100, 100, 100)
        self.assertEqual(world.snapshot().score, before)

    def test_healing_does_not_restore_no_damage_eligibility(self):
        world = start(encounter((1, 'basic', 7, 3)))
        self.assertEqual(world.apply_player_damage(5), 5)
        perform_action(world, 'mend', 3)
        self.assertEqual(world.hp, 100)
        perform_action(world, 'ember_lance', 3)
        self.assertEqual(world.snapshot().score.breakdown, ScoreBreakdown(100, 0, 0, 1500))

    def test_ward_block_does_not_count_as_damage(self):
        world = start(encounter((1, 'basic', 7, 3)))
        world.apply_status(StatusKind.WARD)
        self.assertEqual(world.apply_player_damage(20), 0)
        perform_action(world, 'shot', 3)
        self.assertEqual(world.snapshot().score.breakdown.stage_bonuses, 24500)

    def test_escape_and_game_over_do_not_award_defeat_or_clear_bonus(self):
        world = start(encounter((1, 'basic', 13, 3)))
        perform_action(world, 'shot', 0)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertEqual(world.snapshot().score.total, 0)

    def test_retry_discards_failed_attempt_but_keeps_previous_stage(self):
        world = playing(definition((1, 'bomb', 4, 3), (2, 'basic', 0, 0), boss=(100, 7, 3)))
        accepted = world.snapshot().score.total
        self.assertGreater(accepted, 0)
        self.assertTrue(world.execute_offensive_spell('test-fire', 'ember_lance').valid)
        self.assertEqual(world.snapshot().score.total, accepted + 200)
        world.apply_player_damage(100)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertTrue(world.retry_current_stage())
        self.assertEqual(world.snapshot().score.total, accepted)
        self.assertEqual(world.snapshot().score.attempt_total, 0)
        world.transition_to(GameState.PLAYER_AIM)
        self.assertTrue(world.execute_offensive_spell('test-fire', 'ember_lance').valid)
        self.assertEqual(world.snapshot().score.total, accepted + 200)
        world.apply_player_damage(100)
        self.assertTrue(world.restart())
        self.assertEqual(world.snapshot().score.total, 0)

    def test_score_snapshot_is_detached_and_immutable(self):
        world = start(encounter((1, 'basic', 7, 3)))
        snapshot = world.snapshot().score
        with self.assertRaises(FrozenInstanceError):
            snapshot.breakdown.defeats = 5
        before = deepcopy(vars(world))
        for _ in range(10): world.snapshot()
        self.assertEqual(vars(world), before)
        perform_action(world, 'shot', 3)
        self.assertEqual(snapshot.total, 0)

    def test_full_campaign_breakdown_and_event_order_match_four_frame_schedules(self):
        reference = None
        for schedule in ((1/30,), (1/60,), (1/144,), (.003, .071, .19, .016, .11)):
            world, completed = run_defended_campaign(schedule)
            self.assertTrue(completed)
            score = world.snapshot().score
            self.assertEqual(score.breakdown, ScoreBreakdown(21300, 1850, 1600, 6000))
            self.assertEqual(score.total, 30750)
            if reference is None: reference = score
            self.assertEqual(score, reference)




if __name__ == '__main__':
    unittest.main()
