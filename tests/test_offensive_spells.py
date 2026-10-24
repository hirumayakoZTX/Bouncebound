"""Model-only offensive spells; HP and geometry fixtures isolate exact effects."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import subprocess
import sys
import unittest
from unittest.mock import patch

from src.collision import Bounds
from src.entities import Crystal, Enemy, EnemyType
from src.offensive_spells import OFFENSIVE_DAMAGE
from src.spells import SpellFailure, SpellId
from src.states import GameState
from src.world import World


class OffensiveSpellTests(unittest.TestCase):
    def setUp(self):
        self.world = World(demo=False)
        self.world.start_new_run()
        self.world.transition_to(GameState.PLAYER_AIM)

    def add_enemy(self, enemy_id=1, col=6, row=3, *, hp=50, kind=EnemyType.BASIC):
        enemy = Enemy(enemy_id, kind, col, row)
        # Increased HP is a test fixture, not a change to standard enemy balance.
        enemy.hp = enemy.max_hp = hp
        self.world.combat.add_enemy(enemy)
        return enemy

    def assert_rejected(self, action_id, spell_id, failure):
        before = deepcopy(vars(self.world))
        result = self.world.execute_offensive_spell(action_id, spell_id)
        self.assertFalse(result.valid)
        self.assertIs(result.failure, failure)
        self.assertIsNone(result.effects)
        self.assertEqual(vars(self.world), before)
        return result

    def test_offensive_damage_definitions_are_exact_and_immutable(self):
        self.assertEqual(dict(OFFENSIVE_DAMAGE),
                         {SpellId.FIRE: 20, SpellId.STARSTORM: 10, SpellId.METEOR: 15})
        with self.assertRaises(TypeError):
            OFFENSIVE_DAMAGE[SpellId.FIRE] = 999

    def test_fire_deals_twenty_to_nearest_enemy_and_pays_correct_cost_once(self):
        far = self.add_enemy(1, 2, 3)
        nearest = self.add_enemy(9, 10, 3)
        other_row = self.add_enemy(3, 13, 2)
        result = self.world.execute_offensive_spell('fire', 'fire')
        self.assertTrue(result.valid)
        self.assertEqual(result.cast.targets.enemy_ids, (9,))
        self.assertEqual((nearest.hp, far.hp, other_row.hp), (30, 50, 50))
        self.assertEqual([(c.enemy_id, c.direct_damage) for c in result.effects.changes], [(9, 20)])
        self.assertEqual((self.world.mp, result.cast.next_ready_turn), (70, 5))

    def test_fire_without_target_is_rejected_without_cost_or_history(self):
        self.add_enemy(row=2)
        self.assert_rejected('missing', 'fire', SpellFailure.NO_TARGET)
        self.world.move_player(-1)
        self.assertTrue(self.world.execute_offensive_spell('missing', 'fire').valid)

    def test_fire_excludes_dead_and_escaped_enemies_and_preserves_archives(self):
        dead = self.add_enemy(1, 12, 3, hp=5)
        self.world.combat.apply_damage(1, 5)
        escaped = self.add_enemy(2, 13, 3, hp=5, kind=EnemyType.BOMB)
        escaped.escape(1)
        alive = self.add_enemy(3, 6, 3)
        old_deaths = self.world.combat.death_events[:]
        result = self.world.execute_offensive_spell('fire', 'fire')
        self.assertEqual(result.cast.targets.enemy_ids, (3,))
        self.assertEqual((dead.hp, escaped.hp, alive.hp), (0, 5, 30))
        self.assertEqual(escaped.escape_turn, 1)
        self.assertEqual(self.world.combat.death_events, old_deaths)
        self.assertEqual(set(self.world.enemies), {1, 2, 3})

    def test_starstorm_deals_ten_to_each_center_in_the_existing_circle(self):
        inside = [self.add_enemy(9, 8, 3), self.add_enemy(2, 7, 4), self.add_enemy(5, 5, 3)]
        outside = [self.add_enemy(1, 9, 3), self.add_enemy(3, 6, 5)]
        result = self.world.execute_offensive_spell('area', 'starstorm')
        self.assertEqual((result.cast.targets.center, result.cast.targets.radius), ((440, 240), 96))
        self.assertEqual(result.cast.targets.enemy_ids, (2, 5, 9))
        self.assertTrue(all(e.hp == 40 for e in inside))
        self.assertTrue(all(e.hp == 50 for e in outside))
        self.assertEqual([c.direct_damage for c in result.effects.changes], [10, 10, 10])
        self.assertEqual((self.world.mp, result.cast.next_ready_turn), (60, 6))

    def test_starstorm_inclusive_boundary_and_just_outside_use_model_geometry_fixtures(self):
        inside = self.add_enemy(1, 8, 3)
        outside = self.add_enemy(2, 9, 3)
        context = self.world.spell_context()
        targets = tuple(replace(e, bounds=Bounds(512 + (0.001 if e.enemy_id == 2 else 0), 216,
                                                560 + (0.001 if e.enemy_id == 2 else 0), 264))
                        for e in context.enemies)
        # Grid centers cannot land exactly on this particular circle's boundary.
        with patch.object(self.world, 'spell_context', return_value=replace(context, enemies=targets)):
            result = self.world.execute_offensive_spell('boundary', 'starstorm')
        self.assertEqual(result.cast.targets.enemy_ids, (1,))
        self.assertEqual((inside.hp, outside.hp), (40, 50))

    def test_starstorm_without_selected_enemies_is_rejected(self):
        self.add_enemy(col=0)
        self.assert_rejected('empty-area', 'starstorm', SpellFailure.NO_TARGET)

    def test_meteor_deals_fifteen_to_all_active_enemies_in_stable_order(self):
        self.world.stage = 3  # Isolated unlock context; no stage progression is implemented.
        targets = [self.add_enemy(9, 0, 0), self.add_enemy(1, 13, 7), self.add_enemy(5, 6, 3)]
        result = self.world.execute_offensive_spell('meteor', 'meteor')
        self.assertEqual(result.cast.targets.enemy_ids, (1, 5, 9))
        self.assertTrue(all(e.hp == 35 for e in targets))
        self.assertEqual([c.enemy_id for c in result.effects.changes], [1, 5, 9])
        self.assertEqual((self.world.mp, result.cast.next_ready_turn), (20, 12))

    def test_meteor_rejects_stages_one_and_two(self):
        self.add_enemy()
        for stage in (1, 2):
            self.world.stage = stage
            self.assert_rejected(f'stage-{stage}', 'meteor', SpellFailure.STAGE_LOCKED)

    def test_meteor_excludes_dead_and_escaped_enemies(self):
        self.world.stage = 3
        dead = self.add_enemy(1, 4, 3, hp=5)
        self.world.combat.apply_damage(1, 5)
        escaped = self.add_enemy(2, 13, 3, hp=5)
        escaped.escape(1)
        living = self.add_enemy(3, 0, 7)
        result = self.world.execute_offensive_spell('meteor', 'meteor')
        self.assertEqual(result.cast.targets.enemy_ids, (3,))
        self.assertEqual((dead.hp, escaped.hp, living.hp), (0, 5, 35))
        self.assertEqual(result.effects.deaths, ())

    def test_meteor_with_no_active_targets_is_rejected(self):
        self.world.stage = 3
        self.assert_rejected('empty', 'meteor', SpellFailure.NO_TARGET)

    def test_each_spell_clamps_hp_and_emits_one_distinct_spell_death_event(self):
        for spell in ('fire', 'starstorm', 'meteor'):
            with self.subTest(spell=spell):
                self.setUp()
                self.world.stage = 3
                target = self.add_enemy(hp=5)
                result = self.world.execute_offensive_spell('lethal', spell)
                self.assertEqual(target.hp, 0)
                self.assertEqual([(e.enemy_id, e.source) for e in result.effects.deaths],
                                 [(1, f'spell:{spell}')])
                self.assertEqual(len(self.world.combat.death_events), 1)
                self.assertEqual(self.world.combat.targets(), ())
                self.assert_rejected('lethal', spell, SpellFailure.ALREADY_COMMITTED)

    def test_fire_triggers_normal_bomb_chain_without_player_or_crystal_damage(self):
        first = self.add_enemy(1, 7, 3, hp=5, kind=EnemyType.BOMB)
        second = self.add_enemy(2, 6, 3, hp=5, kind=EnemyType.BOMB)
        third = self.add_enemy(3, 5, 3, hp=5)
        self.world.combat.add_crystal(Crystal(4, 7, 4))
        result = self.world.execute_offensive_spell('chain', 'fire')
        self.assertEqual([first.hp, second.hp, third.hp], [0, 0, 0])
        self.assertEqual([(e.enemy_id, e.source) for e in result.effects.deaths],
                         [(1, 'spell:fire'), (2, 'explosion'), (3, 'explosion')])
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp, self.world.pending_bp),
                         (100, 70, 1, 0))
        self.assertFalse(self.world.crystals[4].collected)
        self.assertFalse(self.world.combat.pending_deaths)

    def test_starstorm_lands_all_direct_hits_before_multiple_bomb_explosions(self):
        self.add_enemy(3, 6, 4, hp=5, kind=EnemyType.BOMB)
        self.add_enemy(2, 6, 3, hp=15)
        self.add_enemy(1, 5, 3, hp=5, kind=EnemyType.BOMB)
        outside = self.add_enemy(4, 4, 3)
        result = self.world.execute_offensive_spell('area', 'starstorm')
        self.assertEqual(result.cast.targets.enemy_ids, (1, 2, 3))
        self.assertEqual([(e.enemy_id, e.source) for e in result.effects.deaths],
                         [(1, 'spell:starstorm'), (3, 'spell:starstorm'), (2, 'explosion')])
        self.assertEqual([(c.enemy_id, c.direct_damage, c.explosion_damage)
                          for c in result.effects.changes],
                         [(1, 5, 0), (2, 10, 5), (3, 5, 0), (4, 0, 10)])
        self.assertEqual(outside.hp, 40)

    def test_meteor_triggers_large_finite_bomb_chain_after_direct_damage(self):
        self.world.stage = 3
        for row in range(8):
            for col in range(8):
                enemy_id = row * 8 + col + 1
                self.add_enemy(enemy_id, col, row, hp=5 if enemy_id == 1 else 20,
                               kind=EnemyType.BOMB)
        result = self.world.execute_offensive_spell('large-chain', 'meteor')
        self.assertEqual(len(result.effects.deaths), 64)
        self.assertEqual(len({e.enemy_id for e in result.effects.deaths}), 64)
        self.assertEqual(result.effects.deaths[0].source, 'spell:meteor')
        self.assertTrue(all(e.source == 'explosion' for e in result.effects.deaths[1:]))
        self.assertTrue(all(e.hp == 0 for e in self.world.enemies.values()))
        self.assertFalse(self.world.combat.pending_deaths)
        before = deepcopy(vars(self.world))
        self.world.combat.resolve_deaths()
        self.assertEqual(vars(self.world), before)

    def test_area_results_are_independent_of_dictionary_insertion_order(self):
        results = []
        for order in ((3, 2, 1), (1, 2, 3), (2, 1, 3)):
            self.setUp()
            values = {1: (5, 3, 5, EnemyType.BOMB), 2: (6, 3, 15, EnemyType.BASIC),
                      3: (6, 4, 5, EnemyType.BOMB)}
            for enemy_id in order:
                col, row, hp, kind = values[enemy_id]
                self.add_enemy(enemy_id, col, row, hp=hp, kind=kind)
            results.append(self.world.execute_offensive_spell('area', 'starstorm'))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_repeated_action_id_cannot_repeat_damage_even_after_cooldown_expiry(self):
        target = self.add_enemy()
        self.world.execute_offensive_spell('same', 'fire')
        self.assertEqual(target.hp, 30)
        self.assert_rejected('same', 'fire', SpellFailure.ALREADY_COMMITTED)
        self.world.turn_index = 5
        self.assert_rejected('same', 'meteor', SpellFailure.ALREADY_COMMITTED)
        self.assert_rejected('same', 'fire', SpellFailure.ALREADY_COMMITTED)
        self.assertEqual((target.hp, self.world.mp), (30, 70))

    def test_pay_only_commit_cannot_be_replayed_as_an_effect(self):
        target = self.add_enemy()
        self.world.commit_spell('reserved', 'fire')
        self.assert_rejected('reserved', 'fire', SpellFailure.ALREADY_COMMITTED)
        self.assertEqual((target.hp, self.world.mp), (50, 70))
        result = self.world.execute_offensive_spell('other', 'starstorm')
        self.assertTrue(result.valid)
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.commit_spell('other', 'ward').failure, SpellFailure.ALREADY_COMMITTED)
        self.assertEqual(vars(self.world), before)

    def test_missing_mp_invalid_id_and_invalid_action_ids_never_damage_or_pay(self):
        self.add_enemy()
        self.assert_rejected('invalid', 'unknown', SpellFailure.INVALID_SPELL)
        for action_id in ('', '  ', True, [], None):
            self.assert_rejected(action_id, 'fire', SpellFailure.INVALID_ACTION_ID)
        self.world.mp = 29
        self.assert_rejected('too-poor', 'fire', SpellFailure.INSUFFICIENT_MP)

    def test_forged_cast_description_is_not_accepted_as_execution_authority(self):
        self.add_enemy()
        forged = replace(self.world.validate_spell('fire').cast, mp_cost=0, next_ready_turn=1)
        self.assert_rejected('forged', forged, SpellFailure.INVALID_SPELL)

    def test_changed_targets_are_revalidated_at_execution(self):
        self.add_enemy(1, 5, 3)
        self.assertEqual(self.world.validate_spell('fire').cast.targets.enemy_ids, (1,))
        nearer = self.add_enemy(2, 10, 3)
        result = self.world.execute_offensive_spell('fresh', 'fire')
        self.assertEqual(result.cast.targets.enemy_ids, (2,))
        self.assertEqual(nearer.hp, 30)
        self.assertEqual(self.world.enemies[1].hp, 50)

    def test_all_offensive_spells_preserve_player_resources_and_crystals_except_mp_cost(self):
        for spell, cost in (("fire", 30), ("starstorm", 40), ("meteor", 80)):
            with self.subTest(spell=spell):
                self.setUp()
                self.world.stage = 3
                self.world.hp, self.world.bp = 83, 4
                self.add_enemy()
                self.world.combat.add_crystal(Crystal(99, 6, 3))
                self.world.combat.pending_bp = 2
                result = self.world.execute_offensive_spell("resources", spell)
                self.assertTrue(result.valid)
                self.assertEqual((self.world.hp, self.world.mp, self.world.bp,
                                  self.world.pending_bp, self.world.turn_index),
                                 (83, 100 - cost, 4, 2, 1))
                self.assertFalse(self.world.crystals[99].collected)
                self.assertEqual(self.world.projectiles, [])

    def test_cooldown_failure_never_repeats_damage_and_readiness_is_unchanged(self):
        target = self.add_enemy()
        self.world.execute_offensive_spell('first', 'fire')
        self.assert_rejected('second', 'fire', SpellFailure.COOLDOWN)
        self.world.turn_index = 5
        self.assertTrue(self.world.execute_offensive_spell('ready', 'fire').valid)
        self.assertEqual((target.hp, self.world.mp, self.world.spells.next_ready_turn('fire')),
                         (10, 40, 9))

    def test_support_spells_are_rejected_without_implementing_effects(self):
        self.world.hp, self.world.stage = 75, 3
        for spell in ('cure', 'esuna', 'levitation', 'ward', 'reraise'):
            self.assert_rejected(spell, spell, SpellFailure.UNSUPPORTED_EFFECT)

    def test_status_hook_failure_remains_structured_and_side_effect_free(self):
        self.add_enemy()
        before = deepcopy(vars(self.world))
        result = self.world.execute_offensive_spell(
            'restricted', 'fire', status_check=lambda definition, context: SpellFailure.STATUS_RESTRICTED)
        self.assertIs(result.failure, SpellFailure.STATUS_RESTRICTED)
        self.assertIsNone(result.effects)
        self.assertEqual(vars(self.world), before)

    def test_model_execution_does_not_claim_turn_or_change_resources_beyond_cost(self):
        target = self.add_enemy()
        self.world.hp, self.world.bp = 77, 3
        result = self.world.execute_offensive_spell('fire', 'fire')
        self.assertTrue(result.valid)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp, self.world.turn_index), (77,70,3,1))
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        self.assertEqual(self.world.projectiles, [])
        self.assertIsNone(self.world._pending_turn)
        self.assertIsNone(self.world.last_resolved_turn)
        self.assertEqual(target.turns_alive, 0)
        self.assertFalse(self.world.resolve_turn())

    def test_different_spells_can_still_execute_same_turn_until_main_action_integration(self):
        target = self.add_enemy(hp=100)
        self.world.execute_offensive_spell('first', 'fire')
        self.world.execute_offensive_spell('second', 'starstorm')
        self.assertEqual((target.hp, self.world.mp, self.world.turn_index), (70, 30, 1))
        self.assertIs(self.world.state, GameState.PLAYER_AIM)

    def test_execution_and_effect_results_are_immutable_and_detached(self):
        target = self.add_enemy()
        result = self.world.execute_offensive_spell('fire', 'fire')
        target.take_damage(10)
        self.assertEqual(result.effects.changes[0].hp_after, 30)
        with self.assertRaises(FrozenInstanceError):
            result.effects = None
        with self.assertRaises(FrozenInstanceError):
            result.cast.mp_cost = 0
        with self.assertRaises(FrozenInstanceError):
            result.effects.changes[0].direct_damage = 0

    def test_world_reset_and_restart_clear_shared_execution_history(self):
        self.add_enemy()
        self.world.execute_offensive_spell('reused', 'fire')
        self.world.apply_player_damage(100)
        self.assertTrue(self.world.restart())
        self.world.transition_to(GameState.PLAYER_AIM)
        target = self.add_enemy()
        self.assertTrue(self.world.execute_offensive_spell('reused', 'fire').valid)
        self.assertEqual((target.hp, self.world.mp), (30, 70))
        self.assertEqual(self.world.turn_index, 1)

    def test_offensive_modules_import_without_pygame(self):
        result = subprocess.run([sys.executable, '-c', (
            "from src.world import World; import src.offensive_spells, sys; "
            "assert 'pygame' not in sys.modules"
        )], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
