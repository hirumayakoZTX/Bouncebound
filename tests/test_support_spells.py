"""Support effect execution uses direct model calls and explicit status fixtures."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import subprocess
import sys
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


def fixture(kind):
    return StatusEffect(kind, None if kind is StatusKind.RERAISE else 2, 1, 'fixture',
                        charges=1 if kind in (StatusKind.WARD, StatusKind.RERAISE) else None)


class SupportSpellTests(unittest.TestCase):
    def setUp(self):
        self.world = caster()

    def reject(self, action_id, spell_id, reason):
        before = deepcopy(vars(self.world))
        result = self.world.execute_support_spell(action_id, spell_id)
        self.assertFalse(result.valid)
        self.assertIs(result.failure, reason)
        self.assertIsNone(result.effects)
        self.assertEqual(vars(self.world), before)

    def test_cure_restores_fifty_and_reports_actual_healing_with_clamping(self):
        for hp, expected, healing in ((30,80,50), (80,100,20), (99,100,1), (1,51,50)):
            with self.subTest(hp=hp):
                world = caster()
                world.hp = hp
                result = world.execute_support_spell('heal', 'cure')
                self.assertTrue(result.valid)
                self.assertEqual((result.effects.hp_before, result.effects.hp_after,
                                  result.effects.healed), (hp,expected,healing))
                self.assertEqual((world.hp, world.mp, world.bp), (expected,90,1))
                self.assertEqual(result.cast.next_ready_turn, 3)
                self.assertEqual(result.effects.removed, ())
                self.assertIsNone(result.effects.granted)

    def test_cure_respects_authoritative_max_hp(self):
        self.world.hp, self.world.max_hp = 70, 80
        result = self.world.execute_support_spell('heal', 'cure')
        self.assertEqual((self.world.hp, result.effects.healed), (80,10))

    def test_cure_at_full_hp_is_invalid_and_does_not_reserve_action_id(self):
        self.world.hp = 100
        self.reject('heal', 'cure', SpellFailure.FULL_HP)
        self.world.hp = 90
        self.assertTrue(self.world.execute_support_spell('heal', 'cure').valid)
        self.assertEqual(self.world.mp, 90)

    def test_cure_does_not_revive_game_over_or_zero_hp_model_context(self):
        self.world.apply_player_damage(100)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.reject('revive', 'cure', SpellFailure.INVALID_STATE)
        self.world = caster()
        self.world.hp = 0  # Isolated inconsistent scene fixture still cannot revive through Cure.
        self.reject('revive', 'cure', SpellFailure.INVALID_STATE)

    def test_cure_retries_do_not_heal_or_pay_twice_even_after_cooldown_expiry(self):
        self.world.hp = 30
        first = self.world.execute_support_spell('once', 'cure')
        self.reject('once', 'cure', SpellFailure.ALREADY_COMMITTED)
        self.world.turn_index = 3
        self.reject('once', 'cure', SpellFailure.ALREADY_COMMITTED)
        self.assertEqual((self.world.hp, self.world.mp), (80,90))
        self.assertEqual(first.effects.hp_after, 80)

    def test_cure_preserves_statuses_and_combat_data(self):
        self.world.statuses.put(fixture(StatusKind.POISON))
        self.world.statuses.put(fixture(StatusKind.WARD))
        before = self.world.statuses.snapshot()
        combat = deepcopy(self.world.combat)
        self.world.execute_support_spell('heal', 'cure')
        self.assertEqual(self.world.statuses.snapshot(), before)
        self.assertEqual(self.world.combat, combat)

    def test_esuna_removes_poison_and_bind_but_preserves_doom_and_beneficial_effects(self):
        self.world.stage = 2  # Model-only unlock fixture; no extra stage is implemented.
        for kind in reversed(tuple(StatusKind)):
            self.world.statuses.put(fixture(kind))
        protected = tuple(e for e in self.world.statuses.snapshot()
                          if e.kind not in (StatusKind.POISON,StatusKind.BIND))
        result = self.world.execute_support_spell('cleanse', 'esuna')
        self.assertTrue(result.valid)
        self.assertEqual([e.kind for e in result.effects.removed], [StatusKind.BIND,StatusKind.POISON])
        self.assertEqual(self.world.statuses.snapshot(), protected)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp), (75,80,1))
        self.assertEqual(result.effects.healed, 0)
        self.assertIsNone(result.effects.granted)

    def test_esuna_deterministic_removed_order_is_independent_of_fixture_insertion(self):
        results = []
        for order in ((StatusKind.POISON,StatusKind.BIND), (StatusKind.BIND,StatusKind.POISON)):
            world = caster()
            world.stage = 2
            for kind in order:
                world.statuses.put(fixture(kind))
            results.append(world.execute_support_spell('cleanse', 'esuna'))
        self.assertEqual(results[0], results[1])

    def test_esuna_remains_valid_when_nothing_is_removable(self):
        self.world.stage = 2
        for kinds in ((), (StatusKind.DOOM,), (StatusKind.WARD,)):
            with self.subTest(kinds=kinds):
                world = caster()
                world.stage = 2
                for kind in kinds:
                    world.statuses.put(fixture(kind))
                before = world.statuses.snapshot()
                result = world.execute_support_spell('empty-cleanse', 'esuna')
                self.assertTrue(result.valid)
                self.assertEqual(result.effects.removed, ())
                self.assertEqual(world.statuses.snapshot(), before)
                self.assertEqual(world.mp, 80)

    def test_esuna_and_levitation_are_stage_locked_without_state_changes(self):
        self.world.statuses.put(fixture(StatusKind.POISON))
        for spell in ('esuna','levitation'):
            self.reject(spell, spell, SpellFailure.STAGE_LOCKED)

    def test_levitation_grants_one_effective_turn_with_application_turn_and_source(self):
        self.world.stage, self.world.turn_index = 2, 7
        result = self.world.execute_support_spell('hover', 'levitation')
        effect = result.effects.granted
        self.assertEqual(effect, self.world.statuses.get(StatusKind.LEVITATION))
        self.assertEqual((effect.remaining_turns,effect.applied_turn,effect.source_id,effect.charges),
                         (1,7,'hover',None))
        self.assertTrue(effect.beneficial)
        self.assertFalse(result.effects.refreshed)
        self.assertEqual(self.world.mp, 80)

    def test_levitation_refresh_does_not_stack_charges_or_records(self):
        self.world.stage = 2
        first = self.world.execute_support_spell('first', 'levitation')
        self.world.turn_index = 5
        second = self.world.execute_support_spell('refresh', 'levitation')
        self.assertTrue(second.valid)
        self.assertTrue(second.effects.refreshed)
        self.assertEqual(len(self.world.statuses.snapshot()), 1)
        self.assertEqual((second.effects.granted.applied_turn,second.effects.granted.remaining_turns), (5,1))
        self.assertIsNone(second.effects.granted.charges)
        self.assertEqual(first.effects.granted.applied_turn, 1)

    def test_levitation_does_not_intercept_ordinary_player_damage(self):
        self.world.stage = 2
        self.world.execute_support_spell('hover','levitation')
        self.assertEqual(self.world.apply_player_damage(7), 7)
        self.assertEqual(self.world.hp, 68)
        self.assertEqual(self.world.statuses.get(StatusKind.LEVITATION).remaining_turns, 1)

    def test_ward_grants_one_use_and_refreshes_without_additional_charges(self):
        first = self.world.execute_support_spell('barrier','ward')
        self.assertEqual((first.effects.granted.kind,first.effects.granted.remaining_turns,
                          first.effects.granted.charges,first.effects.granted.applied_turn),
                         (StatusKind.WARD,1,1,1))
        self.world.turn_index = 5
        second = self.world.execute_support_spell('refresh','ward')
        self.assertTrue(second.effects.refreshed)
        self.assertEqual(second.effects.granted.charges, 1)
        self.assertEqual(second.effects.granted.applied_turn, 5)
        self.assertEqual(len(self.world.statuses.snapshot()), 1)
        self.assertEqual(self.world.mp, 40)

    def test_ward_intercepts_once_and_is_consumed_by_live_damage(self):
        self.world.execute_support_spell('barrier','ward')
        self.assertEqual(self.world.apply_player_damage(5), 0)
        self.assertEqual(self.world.hp, 75)
        self.assertIsNone(self.world.statuses.get(StatusKind.WARD))
        self.world.apply_player_damage(100)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertEqual(self.world.hp, 0)

    def test_reraise_grants_pending_revival_at_fifty_without_healing(self):
        result = self.world.execute_support_spell('revival','reraise')
        effect = result.effects.granted
        self.assertEqual((effect.kind,effect.charges,effect.remaining_turns,effect.revival_hp),
                         (StatusKind.RERAISE,1,None,50))
        self.assertEqual(effect.applied_turn, 1)
        self.assertEqual((self.world.hp,self.world.mp), (75,50))
        self.assertTrue(self.world.reraise_used)
        self.assertTrue(result.effects.reraise_active)
        self.assertFalse(result.effects.reraise_available)

    def test_reraise_used_rule_outlives_cooldown_and_active_effect(self):
        self.world.execute_support_spell('first','reraise')
        self.world.turn_index, self.world.mp = 101, 100
        self.world.statuses.remove(StatusKind.RERAISE)  # Fixture for future consumption.
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.validate_spell('reraise').failure, SpellFailure.RERAISE_USED)
        self.assertIs(self.world.commit_spell('pay-again','reraise').failure, SpellFailure.RERAISE_USED)
        self.reject('second','reraise',SpellFailure.RERAISE_USED)
        self.assertEqual(vars(self.world), before)
        self.assertEqual(self.world.spells.next_ready_turn('reraise'), 101)
        self.world.statuses.reset()
        self.reject('third','reraise',SpellFailure.RERAISE_USED)

    def test_second_reraise_in_same_encounter_has_no_additional_mp_charge(self):
        self.world.execute_support_spell('first','reraise')
        self.reject('second','reraise',SpellFailure.RERAISE_USED)
        self.reject('first','reraise',SpellFailure.ALREADY_COMMITTED)
        self.assertEqual(self.world.mp, 50)

    def test_reraise_intercepts_one_knockout_and_is_consumed(self):
        self.world.execute_support_spell('revival','reraise')
        self.world.apply_player_damage(100)
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        self.assertEqual(self.world.hp, 50)
        self.assertIsNone(self.world.statuses.get(StatusKind.RERAISE))
        self.assertTrue(self.world.reraise_used)
        self.world.apply_player_damage(100)
        self.assertIs(self.world.state, GameState.GAME_OVER)

    def test_each_spell_uses_exact_existing_cost_and_absolute_cooldown(self):
        expected = {'cure':(10,3), 'esuna':(20,5), 'levitation':(20,5),
                    'ward':(30,5), 'reraise':(50,101)}
        for spell,(cost,ready) in expected.items():
            with self.subTest(spell=spell):
                world = caster()
                world.stage = 2
                result = world.execute_support_spell('one',spell)
                self.assertTrue(result.valid)
                self.assertEqual((world.mp,result.cast.mp_cost,result.cast.next_ready_turn),
                                 (100-cost,cost,ready))
                self.assertEqual(world.spells.next_ready_turn(spell),ready)
                self.assertEqual(world.bp, 1)
                self.assertEqual(result.cast.casting_turn, 1)

    def test_failed_affordability_does_not_change_effects_or_reserve_action_id(self):
        for spell,cost in (('cure',10),('esuna',20),('levitation',20),('ward',30),('reraise',50)):
            with self.subTest(spell=spell):
                self.world = caster()
                self.world.stage, self.world.mp = 2, cost-1
                self.world.statuses.put(fixture(StatusKind.POISON))
                self.reject('retry',spell,SpellFailure.INSUFFICIENT_MP)
                self.world.mp = cost
                self.assertTrue(self.world.execute_support_spell('retry',spell).valid)
                self.assertEqual(self.world.mp, 0)

    def test_repeated_action_ids_never_refresh_effects_or_recleanse(self):
        self.world.stage = 2
        self.world.statuses.put(fixture(StatusKind.POISON))
        self.world.execute_support_spell('cleanse','esuna')
        self.world.statuses.put(fixture(StatusKind.BIND))
        self.reject('cleanse','esuna',SpellFailure.ALREADY_COMMITTED)
        self.world.execute_support_spell('barrier','ward')
        self.world.turn_index = 5
        self.reject('barrier','ward',SpellFailure.ALREADY_COMMITTED)
        self.assertEqual(self.world.statuses.get(StatusKind.WARD).applied_turn, 1)
        self.assertIsNotNone(self.world.statuses.get(StatusKind.BIND))

    def test_payment_only_and_offensive_action_ids_cannot_be_reused(self):
        self.world.commit_spell('pay-only','ward')
        self.reject('pay-only','ward',SpellFailure.ALREADY_COMMITTED)
        self.assertIsNone(self.world.statuses.get(StatusKind.WARD))
        self.world.combat.add_enemy(Enemy(1,EnemyType.BASIC,6,3))
        self.world.execute_offensive_spell('attack','fire')
        self.reject('attack','cure',SpellFailure.ALREADY_COMMITTED)

    def test_support_action_ids_also_block_offensive_and_payment_only_replays(self):
        self.world.execute_support_spell('shared','ward')
        before = deepcopy(vars(self.world))
        self.assertIs(self.world.commit_spell('shared','cure').failure,SpellFailure.ALREADY_COMMITTED)
        self.assertIs(self.world.execute_offensive_spell('shared','fire').failure,SpellFailure.ALREADY_COMMITTED)
        self.assertEqual(vars(self.world), before)

    def test_offensive_spells_are_rejected_by_support_executor(self):
        self.world.stage = 3
        self.world.combat.add_enemy(Enemy(1,EnemyType.BASIC,6,3))
        for spell in ('fire','starstorm','meteor'):
            self.reject(spell,spell,SpellFailure.UNSUPPORTED_SUPPORT_EFFECT)

    def test_invalid_ids_and_forged_descriptions_cannot_authorize_effects(self):
        for spell in ('unknown',None,[],True):
            self.reject('bad',spell,SpellFailure.INVALID_SPELL)
        for action_id in ('','  ',None,[],False):
            self.reject(action_id,'cure',SpellFailure.INVALID_ACTION_ID)
        forged = replace(self.world.validate_spell('cure').cast,mp_cost=0)
        self.reject('forged',forged,SpellFailure.INVALID_SPELL)

    def test_revalidation_uses_current_hp_mp_and_status_fixture_values(self):
        self.assertTrue(self.world.validate_spell('cure').valid)
        self.world.hp = 100
        self.reject('heal','cure',SpellFailure.FULL_HP)
        self.world.hp,self.world.mp = 75,9
        self.reject('heal','cure',SpellFailure.INSUFFICIENT_MP)
        self.world.mp = 100
        self.world.stage = 2
        self.world.validate_spell('esuna')
        self.world.statuses.put(fixture(StatusKind.POISON))
        result = self.world.execute_support_spell('fresh','esuna')
        self.assertEqual([e.kind for e in result.effects.removed],[StatusKind.POISON])

    def test_status_hook_reads_immutable_status_snapshot_and_rejects_without_changes(self):
        self.world.statuses.put(fixture(StatusKind.POISON))
        def blocked(definition,context):
            self.assertEqual(context.statuses,self.world.snapshot().statuses)
            with self.assertRaises(FrozenInstanceError):
                context.statuses[0].remaining_turns = 0
            return SpellFailure.STATUS_RESTRICTED
        before = deepcopy(vars(self.world))
        result = self.world.execute_support_spell('blocked','ward',status_check=blocked)
        self.assertIs(result.failure,SpellFailure.STATUS_RESTRICTED)
        self.assertEqual(vars(self.world),before)

    def test_results_and_world_snapshots_are_immutable_and_detached(self):
        result = self.world.execute_support_spell('barrier','ward')
        snapshot = self.world.snapshot()
        self.world.statuses.remove(StatusKind.WARD)
        self.assertEqual(snapshot.statuses,(result.effects.granted,))
        self.assertEqual(result.effects.granted.charges,1)
        with self.assertRaises(FrozenInstanceError):
            result.effects.hp_after = 0
        with self.assertRaises(FrozenInstanceError):
            result.effects.granted.charges = 2
        with self.assertRaises(FrozenInstanceError):
            result.effects = None
        with self.assertRaises(FrozenInstanceError):
            snapshot.reraise_used = True

    def test_support_effects_do_not_claim_action_advance_turn_or_run_combat(self):
        self.world.stage = 2
        self.world.combat.add_enemy(Enemy(1,EnemyType.BASIC,6,3))
        combat_before = deepcopy(self.world.combat)
        for spell in ('cure','esuna','levitation','ward'):
            # Model-only boundary intentionally allows distinct spell actions in one turn.
            self.assertTrue(self.world.execute_support_spell(spell,spell).valid)
        self.assertEqual(self.world.combat,combat_before)
        self.assertEqual(self.world.turn_index,1)
        self.assertIsNone(self.world._pending_turn)
        self.assertIsNone(self.world.last_resolved_turn)
        self.assertEqual(self.world.projectiles,[])
        self.assertIs(self.world.state,GameState.PLAYER_AIM)
        self.assertFalse(self.world.resolve_turn())

    def test_new_run_and_restarts_clear_statuses_reraise_history_and_shared_ledger(self):
        for reset in ('reset','start_new_run','restart'):
            with self.subTest(reset=reset):
                world = caster()
                world.statuses.put(fixture(StatusKind.POISON))
                world.execute_support_spell('revival','reraise')
                if reset == 'restart':
                    world.apply_player_damage(100)
                    world.apply_player_damage(100)  # The first knockout consumes Reraise.
                    self.assertTrue(world.restart())
                else:
                    getattr(world,reset)()
                self.assertFalse(world.reraise_used)
                self.assertEqual(world.statuses.snapshot(),())
                self.assertEqual(dict(world.spells.cooldowns),{})
                self.assertEqual((world.hp,world.mp,world.bp),(100,100,1))
                if world.state is GameState.MENU:
                    world.start_new_run()
                world.transition_to(GameState.PLAYER_AIM)
                self.assertTrue(world.execute_support_spell('revival','reraise').valid)

    def test_effect_data_and_reraise_history_are_not_shared_across_worlds(self):
        self.world.execute_support_spell('revival','reraise')
        other = caster()
        self.assertFalse(other.reraise_used)
        self.assertEqual(other.statuses.snapshot(),())
        self.assertTrue(other.execute_support_spell('revival','reraise').valid)

    def test_support_modules_are_pygame_independent(self):
        result = subprocess.run([sys.executable,'-c',(
            "from src.world import World; import src.statuses, src.support_spells, sys; "
            "assert 'pygame' not in sys.modules"
        )],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
