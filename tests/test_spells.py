"""Spell definitions, deterministic validation, payment, and cooldown rules."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import subprocess
import sys
import unittest

from src.collision import Bounds
from src.entities import Enemy, EnemyType
from src.spells import (
    SPELLS, SpellFailure, SpellId, TargetKind, get_spell, select_targets,
)
from src.states import GameState
from src.world import World


EXPECTED = {
    'fire': ('Pom Fire', 30, 3, 1),
    'starstorm': ('Pom Starstorm', 40, 4, 1),
    'meteor': ('Pom Meteor', 80, 10, 3),
    'cure': ('Pom Cure', 10, 1, 1),
    'esuna': ('Pom Esuna', 20, 3, 2),
    'levitation': ('Pom Levitation', 20, 3, 2),
    'ward': ('Pom Ward', 30, 3, 1),
    'reraise': ('Pom Reraise', 50, 99, 1),
}


def caster() -> World:
    world = World(demo=False)
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    world.hp = 75
    world.combat.add_enemy(Enemy(9, EnemyType.BASIC, 6, 3))
    return world


class SpellDefinitionTests(unittest.TestCase):
    def test_all_eight_definitions_have_exact_catalog_values(self) -> None:
        self.assertEqual(len(SPELLS), 8)
        self.assertEqual({spell.value for spell in SpellId}, set(EXPECTED))
        for spell_id, expected in EXPECTED.items():
            with self.subTest(spell=spell_id):
                definition = get_spell(spell_id)
                self.assertIs(definition, get_spell(SpellId(spell_id)))
                self.assertEqual((definition.name, definition.mp_cost, definition.cooldown,
                                  definition.unlock_stage), expected)

    def test_definition_mapping_and_values_are_immutable(self) -> None:
        with self.assertRaises(TypeError):
            SPELLS[SpellId.FIRE] = get_spell('ward')
        with self.assertRaises(FrozenInstanceError):
            get_spell('fire').mp_cost = 0

    def test_lookup_rejects_unknown_and_malformed_identifiers(self) -> None:
        for spell_id in ('Fire', 'starstorm ', '', 'boss', None, True, 1, [], {}):
            with self.subTest(spell_id=spell_id):
                self.assertIsNone(get_spell(spell_id))

    def test_import_and_model_validation_do_not_import_pygame(self) -> None:
        result = subprocess.run([sys.executable, '-c', (
            "from src.world import World; from src.spells import SPELLS; import sys; "
            "World().validate_spell('ward'); assert 'pygame' not in sys.modules"
        )], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class SpellValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = caster()

    def assert_failure(self, spell_id, failure) -> None:
        before = deepcopy(vars(self.world))
        result = self.world.validate_spell(spell_id)
        self.assertFalse(result.valid)
        self.assertIsNone(result.cast)
        self.assertIs(result.failure, failure)
        self.assertEqual(vars(self.world), before)

    def test_invalid_spell_validation_and_commit_do_not_mutate_any_world_data(self) -> None:
        for spell_id in ('missing', None, [], True):
            with self.subTest(spell_id=spell_id):
                self.assert_failure(spell_id, SpellFailure.INVALID_SPELL)
                before = deepcopy(vars(self.world))
                result = self.world.commit_spell('invalid-request', spell_id)
                self.assertIs(result.failure, SpellFailure.INVALID_SPELL)
                self.assertEqual(vars(self.world), before)

    def test_every_spell_requires_its_exact_mp_threshold(self) -> None:
        self.world.stage = 3
        for spell_id, (_, cost, _, _) in EXPECTED.items():
            with self.subTest(spell=spell_id):
                self.world.mp = cost - 1
                self.assert_failure(spell_id, SpellFailure.INSUFFICIENT_MP)
                self.world.mp = cost
                before = deepcopy(vars(self.world))
                self.assertTrue(self.world.validate_spell(spell_id).valid)
                self.assertEqual(vars(self.world), before)

    def test_unlock_stages_are_enforced_for_every_spell(self) -> None:
        for stage in (1, 2, 3):
            self.world.stage = stage
            for spell_id, (_, _, _, unlock) in EXPECTED.items():
                with self.subTest(stage=stage, spell=spell_id):
                    result = self.world.validate_spell(spell_id)
                    if stage < unlock:
                        self.assertIs(result.failure, SpellFailure.STAGE_LOCKED)
                    else:
                        self.assertTrue(result.valid)

    def test_non_aiming_states_reject_validation_and_payment(self) -> None:
        context = self.world.spell_context()
        for state in GameState:
            if state is GameState.PLAYER_AIM:
                continue
            with self.subTest(state=state):
                before = deepcopy(vars(self.world))
                result = self.world.spells.validate('ward', replace(context, state=state))
                self.assertIs(result.failure, SpellFailure.INVALID_STATE)
                self.assertEqual(vars(self.world), before)
        self.world.pause()
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.commit_spell('paused', 'ward').failure, SpellFailure.INVALID_STATE)
        self.assertEqual(vars(self.world), before)

    def test_pending_shot_blocks_spells_even_after_a_manual_scene_edge(self) -> None:
        self.world.set_aim_target((96, 240))
        self.world.fire()
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.world.transition_to(GameState.PLAYER_AIM)
        self.assert_failure('ward', SpellFailure.INVALID_STATE)

    def test_fire_chooses_nearest_active_enemy_in_current_row(self) -> None:
        self.world.combat.add_enemy(Enemy(3, EnemyType.BOMB, 10, 3))
        self.world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 13, 2))
        result = self.world.validate_spell('fire')
        self.assertEqual(result.cast.targets.enemy_ids, (3,))
        self.assertIs(result.cast.targets.kind, TargetKind.NEAREST_IN_ROW)
        self.assertEqual(self.world.enemies[3].hp, 5)

    def test_fire_with_no_enemy_in_current_row_is_invalid(self) -> None:
        self.world.move_player(-1)
        self.assert_failure('fire', SpellFailure.NO_TARGET)

    def test_fire_ties_use_stable_ids_independent_of_insertion_order(self) -> None:
        self.world.combat.add_enemy(Enemy(7, EnemyType.BOMB, 10, 3))
        self.world.combat.add_enemy(Enemy(2, EnemyType.BOMB, 10, 3))
        context = self.world.spell_context()
        for enemies in (context.enemies, tuple(reversed(context.enemies))):
            result = self.world.spells.validate('fire', replace(context, enemies=enemies))
            self.assertEqual(result.cast.targets.enemy_ids, (2,))

    def test_dead_and_escaped_enemies_are_excluded_from_all_offensive_targets(self) -> None:
        dead = Enemy(1, EnemyType.BASIC, 12, 3)
        dead.take_damage(5)
        escaped = Enemy(2, EnemyType.BOMB, 13, 3)
        escaped.escape(1)
        self.world.combat.add_enemy(dead)
        self.world.combat.add_enemy(escaped)
        self.world.stage = 3
        for spell_id in ('fire', 'starstorm', 'meteor'):
            with self.subTest(spell=spell_id):
                self.assertEqual(self.world.validate_spell(spell_id).cast.targets.enemy_ids, (9,))
        self.assertEqual(dead.hp, 0)
        self.assertTrue(escaped.escaped)
        self.assertEqual(escaped.hp, 5)

    def test_starstorm_uses_clamped_circle_and_sorted_enemy_centers(self) -> None:
        for enemy in (Enemy(7, EnemyType.BASIC, 8, 3),
                      Enemy(2, EnemyType.BASIC, 7, 4),
                      Enemy(4, EnemyType.BASIC, 5, 3),
                      Enemy(1, EnemyType.BASIC, 4, 3),
                      Enemy(3, EnemyType.BASIC, 8, 5)):
            self.world.combat.add_enemy(enemy)
        result = self.world.validate_spell('starstorm')
        self.assertEqual(result.cast.targets.center, (440, 240))
        self.assertEqual(result.cast.targets.radius, 96)
        self.assertEqual(result.cast.targets.enemy_ids, (2, 4, 7, 9))
        context = self.world.spell_context()
        for position, center in (((0, 0), (96, 72)), ((2000, 2000), (768, 456))):
            # Inspect selection directly when a clamped circle contains no enemies.
            targets = select_targets(get_spell('starstorm'), replace(context, player_position=position))
            self.assertEqual(targets.center, center)

    def test_starstorm_includes_exact_radius_boundary_and_excludes_outside(self) -> None:
        enemy = self.world.spell_context().enemies[0]
        context = self.world.spell_context()
        boundary = replace(enemy, enemy_id=1, bounds=Bounds(512, 216, 560, 264))
        outside = replace(enemy, enemy_id=2, bounds=Bounds(512.001, 216, 560.001, 264))
        result = self.world.spells.validate('starstorm', replace(context, enemies=(outside, boundary)))
        self.assertEqual(result.cast.targets.enemy_ids, (1,))

    def test_empty_starstorm_area_and_empty_meteor_are_invalid(self) -> None:
        self.world.enemies.clear()
        self.world.stage = 3
        self.assert_failure('starstorm', SpellFailure.NO_TARGET)
        self.assert_failure('meteor', SpellFailure.NO_TARGET)

    def test_meteor_requires_stage_three_and_targets_all_active_enemies_by_id(self) -> None:
        self.world.combat.add_enemy(Enemy(1, EnemyType.BOMB, 0, 7))
        self.assert_failure('meteor', SpellFailure.STAGE_LOCKED)
        self.world.stage = 3
        result = self.world.validate_spell('meteor')
        self.assertEqual(result.cast.targets.enemy_ids, (1, 9))
        self.assertIs(result.cast.targets.kind, TargetKind.ALL_ENEMIES)

    def test_cure_is_invalid_at_full_hp_and_never_heals_on_validation(self) -> None:
        self.world.hp = 100
        self.assert_failure('cure', SpellFailure.FULL_HP)
        self.world.hp = 99
        self.assertTrue(self.world.validate_spell('cure').valid)
        self.assertEqual(self.world.hp, 99)

    def test_self_target_spells_need_no_enemies_or_invented_status_conditions(self) -> None:
        self.world.enemies.clear()
        self.world.stage = 3
        for spell_id in ('cure', 'esuna', 'levitation', 'ward', 'reraise'):
            with self.subTest(spell=spell_id):
                result = self.world.validate_spell(spell_id)
                self.assertTrue(result.valid)
                self.assertIs(result.cast.targets.kind, TargetKind.SELF)
                self.assertEqual(result.cast.targets.enemy_ids, ())
                self.assertEqual(self.world.hp, 75)

    def test_future_status_hook_can_reject_without_state_mutation(self) -> None:
        before = deepcopy(vars(self.world))
        def restricted(definition, context):
            self.assertIs(definition.spell_id, SpellId.RERAISE)
            with self.assertRaises(FrozenInstanceError):
                context.mp = 0
            with self.assertRaises(FrozenInstanceError):
                context.enemies[0].hp = 0
            return SpellFailure.STATUS_RESTRICTED
        result = self.world.validate_spell('reraise', status_check=restricted)
        self.assertIs(result.failure, SpellFailure.STATUS_RESTRICTED)
        result = self.world.commit_spell('restricted', 'reraise', status_check=restricted)
        self.assertIs(result.failure, SpellFailure.STATUS_RESTRICTED)
        self.assertEqual(vars(self.world), before)

    def test_context_and_cast_descriptions_are_detached_immutable_values(self) -> None:
        context = self.world.spell_context()
        result = self.world.validate_spell('fire')
        self.world.enemies[9].take_damage(5)
        self.world.mp = 0
        self.assertEqual(context.enemies[0].hp, 5)
        self.assertEqual(context.mp, 100)
        self.assertEqual(result.cast.targets.enemy_ids, (9,))
        with self.assertRaises(FrozenInstanceError):
            result.cast.mp_cost = 0
        with self.assertRaises(FrozenInstanceError):
            result.cast.targets.enemy_ids = ()
        with self.assertRaises(FrozenInstanceError):
            result.failure = SpellFailure.NO_TARGET


class SpellCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = caster()

    def test_every_successful_commit_charges_exact_cost_and_records_absolute_readiness(self) -> None:
        for spell_id, (_, cost, cooldown, _) in EXPECTED.items():
            with self.subTest(spell=spell_id):
                world = caster()
                world.stage = 3
                world.mp = cost
                combat_before = deepcopy(world.combat)
                result = world.commit_spell('one-action', spell_id)
                self.assertTrue(result.valid)
                self.assertEqual(world.mp, 0)
                self.assertEqual(result.cast.mp_cost, cost)
                self.assertEqual(result.cast.casting_turn, 1)
                self.assertEqual(result.cast.next_ready_turn, 1 + cooldown + 1)
                self.assertEqual(world.spells.next_ready_turn(spell_id), 1 + cooldown + 1)
                self.assertEqual(world.combat, combat_before)
                self.assertEqual((world.hp, world.bp, world.turn_index), (75, 1, 1))
                self.assertIs(world.state, GameState.PLAYER_AIM)
                self.assertEqual(world.projectiles, [])
                self.assertIsNone(world._pending_turn)

    def test_duplicate_submission_never_charges_or_changes_history_twice(self) -> None:
        self.assertTrue(self.world.commit_spell('same-action', 'fire').valid)
        before = deepcopy(vars(self.world))
        for spell_id in ('fire', 'ward', 'missing'):
            result = self.world.commit_spell('same-action', spell_id)
            self.assertIs(result.failure, SpellFailure.ALREADY_COMMITTED)
            self.assertFalse(result.valid)
            self.assertEqual(vars(self.world), before)
        self.assertEqual(self.world.mp, 70)

    def test_invalid_action_ids_never_reserve_payment_or_history(self) -> None:
        for action_id in ('', '  ', 0, True, None, [], {}):
            with self.subTest(action_id=action_id):
                before = deepcopy(vars(self.world))
                result = self.world.commit_spell(action_id, 'ward')
                self.assertIs(result.failure, SpellFailure.INVALID_ACTION_ID)
                self.assertEqual(vars(self.world), before)

    def test_failed_validation_preserves_mp_cooldowns_and_retry_id(self) -> None:
        self.world.mp = 29
        before = deepcopy(vars(self.world))
        result = self.world.commit_spell('retry', 'fire')
        self.assertIs(result.failure, SpellFailure.INSUFFICIENT_MP)
        self.assertEqual(vars(self.world), before)
        self.world.mp = 30
        self.assertTrue(self.world.commit_spell('retry', 'fire').valid)
        self.assertEqual(self.world.mp, 0)

    def test_fire_cast_on_turn_one_is_not_ready_until_turn_five(self) -> None:
        self.world.commit_spell('first', 'fire')
        self.assertEqual(self.world.spells.next_ready_turn('fire'), 5)
        for turn in (1, 2, 3, 4):
            self.world.turn_index = turn
            before = deepcopy(vars(self.world))
            result = self.world.commit_spell(f'blocked-{turn}', 'fire')
            self.assertIs(result.failure, SpellFailure.COOLDOWN)
            self.assertEqual(vars(self.world), before)
        self.world.turn_index = 5
        self.assertTrue(self.world.commit_spell('ready', 'fire').valid)
        self.assertEqual((self.world.mp, self.world.spells.next_ready_turn('fire')), (40, 9))

    def test_cooldowns_for_different_spells_are_independent(self) -> None:
        self.world.commit_spell('fire', 'fire')
        self.world.commit_spell('cure', 'cure')
        self.assertEqual(self.world.spells.next_ready_turn('fire'), 5)
        self.assertEqual(self.world.spells.next_ready_turn('cure'), 3)
        self.assertEqual(self.world.spells.next_ready_turn('ward'), 1)
        for spell_id in ('fire', 'cure'):
            self.assertIs(self.world.validate_spell(spell_id).failure, SpellFailure.COOLDOWN)
        self.assertTrue(self.world.validate_spell('ward').valid)

    def test_commit_revalidates_mp_instead_of_trusting_an_old_description(self) -> None:
        self.assertTrue(self.world.validate_spell('fire').valid)
        self.world.mp = 29
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.commit_spell('stale', 'fire').failure, SpellFailure.INSUFFICIENT_MP)
        self.assertEqual(vars(self.world), before)

    def test_commit_revalidates_current_targets_state_and_cooldown(self) -> None:
        self.assertTrue(self.world.validate_spell('fire').valid)
        self.world.combat.apply_damage(9, 5)
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.commit_spell('dead-target', 'fire').failure, SpellFailure.NO_TARGET)
        self.assertEqual(vars(self.world), before)
        self.world.combat.add_enemy(Enemy(10, EnemyType.BOMB, 7, 3))
        self.assertEqual(self.world.commit_spell('new-target', 'fire').cast.targets.enemy_ids, (10,))
        self.world.pause()
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.commit_spell('paused', 'ward').failure, SpellFailure.INVALID_STATE)
        self.assertEqual(vars(self.world), before)

    def test_cooldown_view_is_detached_and_read_only(self) -> None:
        old_view = self.world.spells.cooldowns
        self.world.commit_spell('one', 'fire')
        self.assertEqual(dict(old_view), {})
        with self.assertRaises(TypeError):
            self.world.spells.cooldowns[SpellId.FIRE] = 0
        with self.assertRaisesRegex(ValueError, 'Unknown spell'):
            self.world.spells.next_ready_turn('missing')

    def test_reset_clears_cooldowns_and_duplicate_action_history(self) -> None:
        self.world.commit_spell('reusable', 'ward')
        self.world.spells.reset()
        self.assertEqual(dict(self.world.spells.cooldowns), {})
        self.assertTrue(self.world.commit_spell('reusable', 'ward').valid)
        self.assertEqual(self.world.mp, 40)

    def test_world_reset_and_restart_restore_resources_and_spell_history(self) -> None:
        for reset in ('reset', 'start_new_run', 'restart'):
            with self.subTest(reset=reset):
                world = caster()
                world.commit_spell('run-action', 'ward')
                if reset == 'restart':
                    world.apply_player_damage(100)
                    self.assertTrue(world.restart())
                else:
                    getattr(world, reset)()
                self.assertEqual(world.mp, 100)
                self.assertEqual(dict(world.spells.cooldowns), {})
                if world.state is GameState.MENU:
                    world.start_new_run()
                world.transition_to(GameState.PLAYER_AIM)
                self.assertTrue(world.commit_spell('run-action', 'ward').valid)
                self.assertEqual(world.mp, 70)

    def test_worlds_do_not_share_cooldowns_or_payment_history(self) -> None:
        other = caster()
        self.world.commit_spell('same-id', 'ward')
        self.assertEqual(other.mp, 100)
        self.assertEqual(dict(other.spells.cooldowns), {})
        self.assertTrue(other.commit_spell('same-id', 'ward').valid)

    def test_render_frame_time_does_not_expire_a_cooldown(self) -> None:
        self.world.commit_spell('fire', 'fire')
        for dt in (0, 1/144, 1/60, 1/30, 1000):
            self.world.advance_time(dt)
            self.assertEqual(self.world.turn_index, 1)
            self.assertEqual(self.world.spells.next_ready_turn('fire'), 5)
            self.assertIs(self.world.validate_spell('fire').failure, SpellFailure.COOLDOWN)


if __name__ == '__main__':
    unittest.main()
