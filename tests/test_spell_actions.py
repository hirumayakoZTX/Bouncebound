"""Main-action ownership and real turn resolution for spells and shots.

Higher stages, extra HP, statuses, and defense-edge enemies are explicit model
fixtures. Full prototype outcome regressions remain in the encounter tests.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import math
import unittest
from unittest.mock import patch

from src.encounter import EncounterDefinition, Spawn, Wave
from src.entities import Enemy, EnemyType
from src.player_actions import ActionKind, SPELL_ANIMATION_SECONDS
from src.spells import SpellFailure, SpellId
from src.states import GameOverReason, GameState
from src.statuses import StatusEventKind, StatusKind
from src.world import World


def aiming(**kwargs):
    owner = World(**kwargs) if kwargs else World(demo=False)
    owner.start_new_run()
    owner.transition_to(GameState.PLAYER_AIM)
    return owner


def finish_action(owner, *, resolve=True):
    if owner.state is GameState.SHOT_ANIMATION:
        for _ in range(21):
            owner.advance_time(.25)
    else:
        owner.advance_time(SPELL_ANIMATION_SECONDS)
    assert owner.state is GameState.TURN_RESOLVE
    if resolve:
        assert owner.resolve_turn()


class SpellActionTests(unittest.TestCase):
    def setUp(self):
        self.world = aiming()

    def add_enemy(self, enemy_id=1, col=4, row=3, hp=30, kind=EnemyType.BASIC):
        enemy = Enemy(enemy_id, kind, col, row)
        enemy.hp = enemy.max_hp = hp
        self.world.combat.add_enemy(enemy)
        return enemy

    def cast(self, spell):
        self.assertTrue(self.world.select_spell(spell))
        return self.world.cast_selected_spell()

    def test_initial_selection_feedback_and_pending_action_are_empty(self):
        snapshot = self.world.snapshot()
        self.assertIsNone(snapshot.selected_spell)
        self.assertIsNone(snapshot.pending_action)
        self.assertEqual((snapshot.spell_feedback, snapshot.spell_remaining), ('', 0))

    def test_selection_is_free_even_when_unaffordable_or_without_target(self):
        self.world.mp = 0
        before = deepcopy(vars(self.world))
        self.assertTrue(self.world.select_spell('ember_lance'))
        self.assertEqual((self.world.mp, self.world.turn_index), (0, 1))
        self.assertEqual(self.world.combat, before['combat'])
        self.assertEqual(self.world.spells, before['spells'])
        self.assertEqual(self.world._next_action_id, 1)
        self.assertIsNone(self.world._pending_turn)


    def test_no_selection_is_structured_and_does_not_claim_an_action(self):
        result = self.world.cast_selected_spell()
        self.assertIs(result.failure, SpellFailure.NO_SELECTION)
        self.assertEqual(self.world.spell_feedback, 'Select a spell with 1-5')
        self.assertIsNone(self.world._pending_turn)
        self.assertFalse(self.world.resolve_turn())

    def test_invalid_casts_preserve_everything_except_feedback(self):
        cases = [('ember_lance', 100, 100, SpellFailure.NO_TARGET),
                 ('barrier', 29, 100, SpellFailure.INSUFFICIENT_MP),
                 ('mend', 100, 100, SpellFailure.FULL_HP)]
        for spell, mp, hp, failure in cases:
            with self.subTest(spell=spell):
                self.world = aiming()
                self.world.mp, self.world.hp = mp, hp
                self.world.select_spell(spell)
                before = deepcopy(vars(self.world))
                self.assertIs(self.world.cast_selected_spell().failure, failure)
                after = deepcopy(vars(self.world))
                after['spell_feedback'] = before['spell_feedback']
                self.assertEqual(after, before)

    def test_ember_lance_commits_damage_mp_cooldown_and_one_pending_spell(self):
        enemy = self.add_enemy()
        result = self.cast('ember_lance')
        self.assertTrue(result.valid)
        self.assertEqual((enemy.hp, self.world.mp), (10, 70))
        self.assertEqual(self.world.spells.next_ready_turn('ember_lance'), 5)
        snapshot = self.world.snapshot()
        self.assertIs(snapshot.state, GameState.SPELL_ANIMATION)
        self.assertIs(snapshot.pending_action.kind, ActionKind.SPELL)
        self.assertFalse(snapshot.pending_action.completed)
        self.assertEqual(snapshot.spell_remaining, SPELL_ANIMATION_SECONDS)
        self.assertEqual(snapshot.spell_feedback, 'Cast: Fire')
        self.assertEqual(snapshot.projectiles, ())
        self.assertEqual(self.world.last_spell_result.effects.changes[0].direct_damage, 20)

    def test_skyfall_hits_all_enemies_with_one_simultaneous_damage_batch(self):
        self.world.stage = 3
        self.add_enemy(1, 7, 3, 10, EnemyType.BOMB)
        self.add_enemy(2, 8, 3, 10, EnemyType.BOMB)
        self.add_enemy(3, 9, 3, 15)
        result = self.cast('skyfall')
        self.assertTrue(result.valid)
        self.assertEqual(self.world.mp, 20)
        self.assertEqual([e.enemy_id for e in self.world.combat.death_events], [1, 2, 3])
        self.assertEqual([e.source for e in self.world.combat.death_events],
                         ['spell:skyfall', 'spell:skyfall', 'spell:skyfall'])
        before = deepcopy(self.world.combat)
        self.world.cast_selected_spell()
        self.assertEqual(self.world.combat, before)

    def test_mend_heals_and_uses_the_normal_action_flow(self):
        self.world.hp = 80
        self.assertTrue(self.cast('mend').valid)
        self.assertEqual((self.world.hp, self.world.mp), (100, 90))
        self.assertEqual(self.world.last_spell_result.effects.healed, 20)
        finish_action(self.world)
        self.assertEqual(self.world.turn_index, 2)

    def test_one_turn_ward_covers_contact_of_its_cast_before_expiring(self):
        self.add_enemy(col=13, row=0)
        self.assertTrue(self.cast('barrier').valid)
        finish_action(self.world)
        self.assertEqual((self.world.hp, self.world.mp, self.world.turn_index), (100, 70, 2))
        self.assertIsNone(self.world.statuses.get(StatusKind.WARD))
        self.assertEqual(len([e for e in self.world.status_events
                              if e.kind is StatusEventKind.WARD_BLOCKED]), 1)


    def test_animation_claims_completion_once_without_resolving_the_turn(self):
        self.cast('barrier')
        self.world.advance_time(SPELL_ANIMATION_SECONDS / 2)
        self.assertIs(self.world.state, GameState.SPELL_ANIMATION)
        self.assertFalse(self.world.resolve_turn())
        finish_action(self.world, resolve=False)
        self.assertTrue(self.world.snapshot().pending_action.completed)
        before = deepcopy(vars(self.world))
        self.world.advance_time(1000)
        self.assertEqual(vars(self.world), before)
        self.assertTrue(self.world.resolve_turn())
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual(self.world.turn_index, 2)


    def test_shot_then_cast_is_rejected_even_after_manual_scene_return(self):
        self.world.select_spell('barrier')
        self.world.set_aim_target((96, 240))
        self.assertTrue(self.world.fire())
        self.assertIs(self.world.snapshot().pending_action.kind, ActionKind.SHOT)
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.world.transition_to(GameState.PLAYER_AIM)
        self.assertFalse(self.world.cast_selected_spell().valid)
        self.assertFalse(self.world.fire())
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual(self.world.mp, 100)

    def test_invalid_cast_leaves_movement_and_shooting_available(self):
        self.assertFalse(self.cast('ember_lance').valid)
        self.assertTrue(self.world.move_player(-1))
        self.assertTrue(self.world.set_aim_target((96, 192)))
        self.assertTrue(self.world.fire())
        finish_action(self.world)
        self.assertEqual((self.world.mp, self.world.turn_index), (100, 2))

    def test_invalid_shot_and_full_hp_mend_leave_barrier_available(self):
        self.assertFalse(self.world.fire())
        self.assertFalse(self.cast('mend').valid)
        self.assertTrue(self.cast('barrier').valid)
        self.assertEqual(self.world._next_action_id, 2)

    def test_manual_spell_scene_and_completion_cannot_authorize_an_enemy_phase(self):
        enemy = self.add_enemy()
        self.world.transition_to(GameState.SPELL_ANIMATION)
        self.world.advance_time(1000)
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual((enemy.grid_col, enemy.turns_alive, self.world.turn_index), (4, 0, 1))

    def test_manual_early_resolution_cannot_complete_a_real_spell(self):
        self.cast('barrier')
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.assertFalse(self.world.resolve_turn())
        self.assertFalse(self.world.snapshot().pending_action.completed)
        self.assertEqual(self.world.turn_index, 1)

    def test_spell_turn_processes_each_surviving_enemy_once(self):
        enemies = [self.add_enemy(2, 1, 0), self.add_enemy(1, 2, 1)]
        self.cast('barrier')
        for _ in range(10):
            self.world.advance_time(.1)
            self.world.resolve_turn()
        self.assertEqual([(e.grid_col, e.turns_alive) for e in enemies], [(2, 1), (3, 1)])
        self.assertEqual((self.world.turn_index, self.world.last_resolved_turn), (2, 1))

    def test_pause_freezes_spell_remaining_resources_and_effect_outcome(self):
        self.cast('barrier')
        self.world.advance_time(.1)
        self.world.pause()
        before = deepcopy(vars(self.world))
        for _ in range(10):
            self.world.advance_time(1000)
            self.world.resolve_turn()
            self.world.cast_selected_spell()
        self.assertEqual(vars(self.world), before)
        self.world.resume()
        self.assertAlmostEqual(self.world.snapshot().spell_remaining, .35)
        self.world.advance_time(.349)
        self.assertIs(self.world.state, GameState.SPELL_ANIMATION)
        self.world.advance_time(.001)
        self.assertIs(self.world.state, GameState.TURN_RESOLVE)

    def test_animation_elapsed_validation_is_atomic(self):
        self.cast('barrier')
        for dt in (-1, math.inf, math.nan, '1', True):
            before = deepcopy(vars(self.world))
            with self.assertRaises(ValueError):
                self.world.advance_time(dt)
            self.assertEqual(vars(self.world), before)





    def test_isolated_stage_three_skyfall_uses_the_shared_flow(self):
        enemy = self.add_enemy(hp=30)
        self.world.stage = 3
        self.assertTrue(self.cast('skyfall').valid)
        finish_action(self.world)
        self.assertEqual((enemy.hp, self.world.mp, self.world.turn_index), (15, 20, 2))


    def test_spell_can_be_followed_by_hp_based_defeat(self):
        self.world.hp = 5
        self.add_enemy(1, 13, 0)
        self.add_enemy(2, 4, 3, 5)
        self.cast('ember_lance')
        finish_action(self.world)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertIs(self.world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertEqual((self.world.hp, self.world.turn_index), (0, 1))



    def test_ember_lance_readiness_turn_five_across_real_consecutive_actions(self):
        enemy = self.add_enemy(col=0, hp=100)
        self.cast('ember_lance')
        finish_action(self.world)
        for turn in (2, 3, 4):
            self.assertEqual(self.world.turn_index, turn)
            self.assertIs(self.world.cast_selected_spell().failure, SpellFailure.COOLDOWN)
            self.assertEqual(self.world.spell_feedback, 'Spell on cooldown')
            while self.world.player_row:
                self.world.move_player(-1)
            self.world.set_aim_target((96, 96))
            self.assertTrue(self.world.fire())
            finish_action(self.world)
        while self.world.player_row < 3:
            self.world.move_player(1)
        self.assertTrue(self.world.cast_selected_spell().valid)
        self.assertEqual((enemy.hp, self.world.mp, self.world.turn_index), (60, 40, 5))


    def test_animation_cannot_restart_and_pending_snapshot_is_frozen(self):
        self.cast('barrier')
        self.assertFalse(self.world.restart())
        snapshot = self.world.snapshot()
        with self.assertRaises(FrozenInstanceError):
            snapshot.pending_action.completed = True
        with self.assertRaises(FrozenInstanceError):
            snapshot.spell_result.effects.hp_after = 0

    def test_generated_id_avoids_preexisting_low_level_commit_ids(self):
        self.add_enemy()
        self.assertTrue(self.world.commit_spell('player-action:1', 'ember_lance').valid)
        self.assertTrue(self.cast('barrier').valid)
        self.assertEqual(self.world.snapshot().pending_action.action_id, 'player-action:2')



    def test_next_turn_spawns_wave_once_after_spell_and_never_during_animation(self):
        definition = EncounterDefinition(1, (
            Wave(1, (Spawn(1, 'basic', 0, 0),)),
            Wave(2, (Spawn(2, 'bomb', 0, 1),)),
        ))
        owner = aiming(encounter=definition)
        owner.select_spell('barrier')
        owner.cast_selected_spell()
        self.assertEqual(owner.spawn_waves(), ())
        self.assertEqual(owner.encounter.spawned_waves, {0})
        finish_action(owner)
        self.assertEqual(owner.encounter.spawned_waves, {0, 1})
        self.assertEqual(owner.spawn_waves(), ())
        self.assertFalse(owner.resolve_turn())
        self.assertEqual((len(owner.enemies), owner.turn_index), (2, 2))


if __name__ == '__main__':
    unittest.main()
