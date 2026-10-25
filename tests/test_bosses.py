"""Stage 1 boss values, shared combat, defensive resolution, and atomic spawning."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest
from unittest.mock import patch

from src.combat import Combat
from src.encounter import Encounter, EncounterOutcome
from src.entities import Enemy, EnemyType, EnemyTurnContext, cell_bounds
from src.projectile import HitEvent
from src.stage_config import StageConfigurationError, parse_stage
from src.states import GameState, GameOverReason
from src.statuses import StatusKind, StatusEventKind
from src.turns import resolve_enemy_phase
from src.world import World
from stage_one_fixtures import boss_definition, perform_action, playing
from test_stage_config import stage_data


class BossModelTests(unittest.TestCase):
    def test_exact_boss_hp_attack_contact_and_geometry(self):
        for kind in (EnemyType.ULTROS, EnemyType.TYPHON):
            enemy = Enemy(100, kind, 7, 2)
            self.assertEqual((enemy.hp, enemy.max_hp, enemy.attack_damage, enemy.contact_damage),
                             (15, 15, 5, 5))
            self.assertTrue(enemy.is_boss)
            self.assertEqual(enemy.bounds, cell_bounds(7, 2))
            self.assertEqual(enemy.position, (456, 192))
            snapshot = enemy.snapshot()
            with self.assertRaises(FrozenInstanceError):snapshot.hp = 0
            enemy.take_damage(5)
            self.assertEqual(snapshot.hp, 15)
            self.assertEqual(enemy.hp, 10)

    def test_boss_death_clamps_and_disables_collision_exactly_once(self):
        boss = Enemy(100, EnemyType.ULTROS, 7, 2)
        combat = Combat(enemies={100: boss})
        self.assertTrue(combat.apply_damage(100, 100, 'spell:fire'))
        self.assertEqual((boss.hp, len(combat.death_events)), (0, 1))
        self.assertFalse(combat.apply_damage(100, 100))
        self.assertEqual(combat.targets(), ())
        self.assertEqual(len(combat.death_events), 1)

    def test_bomb_explosion_deals_ten_to_boss_and_keeps_crystal_uncollected(self):
        boss = Enemy(100, EnemyType.ULTROS, 7, 2)
        bomb = Enemy(1, EnemyType.BOMB, 8, 2)
        combat = Combat(enemies={100: boss, 1: bomb})
        from src.entities import Crystal
        crystal = Crystal(2, 8, 2);combat.add_crystal(crystal)
        combat.apply_damage(1, 5)
        self.assertEqual(boss.hp, 5)
        self.assertFalse(crystal.collected)
        self.assertEqual(combat.pending_bp, 0)
        combat.handle_hit(HitEvent(1, 100, 5, boss.position, (1., 0.)))
        self.assertEqual([event.enemy_id for event in combat.death_events], [1, 100])

    def test_bosses_use_stable_action_then_movement_order(self):
        bosses = [Enemy(101, EnemyType.TYPHON, 7, 5), Enemy(100, EnemyType.ULTROS, 7, 2)]
        observed = []
        def damage(amount):
            observed.append((amount, tuple(enemy.grid_col for enemy in bosses)))
            return amount
        context = EnemyTurnContext(1, damage, lambda: False)
        resolve_enemy_phase(bosses, context)
        self.assertEqual(observed, [(5, (7, 7)), (5, (7, 8))])
        self.assertEqual([enemy.grid_col for enemy in bosses], [8, 8])
        self.assertEqual([enemy.turns_alive for enemy in bosses], [1, 1])
        resolve_enemy_phase(bosses, context)
        self.assertEqual(len(observed), 2)

    def test_dead_and_escaped_bosses_never_attack_move_or_take_more_damage(self):
        dead = Enemy(100, EnemyType.ULTROS, 7, 2);dead.take_damage(15)
        escaped = Enemy(101, EnemyType.TYPHON, 13, 5);escaped.escape(1)
        context = EnemyTurnContext(2, lambda amount: self.fail('Inactive boss attacked'), lambda: False)
        resolve_enemy_phase([dead, escaped], context)
        self.assertEqual((dead.grid_col, escaped.grid_col), (7, 13))
        self.assertEqual((dead.turns_alive, escaped.turns_alive), (0, 0))
        self.assertFalse(escaped.take_damage(100))
        self.assertEqual(escaped.hp, 15)

    def test_boss_escape_is_distinct_from_death_and_follows_contact_policy(self):
        world = playing(boss_definition(col=13))
        perform_action(world, 'shot', 0)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertEqual(world.hp, 80)  # Two 5-damage attacks and two 5-damage contacts.
        self.assertEqual(world.combat.death_events, [])
        self.assertTrue(all(enemy.escaped and enemy.hp == 15 for enemy in world.enemies.values()))
        self.assertFalse(any(target.target_id in (100, 101) for target in world.combat.targets()))


class BossCombatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.world = playing(boss_definition())

    def test_single_orb_hit_deals_five_without_changing_spell_or_player_resources(self):
        self.world.move_player(-1)
        self.world.set_aim_target((96, 192));self.world.fire()
        hits = []
        for _ in range(3):hits.extend(self.world.advance_time(.25))
        self.assertEqual([(event.target_id, event.damage) for event in hits], [(100, 5)])
        self.assertEqual(self.world.enemies[100].hp, 10)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp, self.world.turn_index), (100, 100, 1, 1))

    def test_three_orbs_can_damage_the_same_boss_independently_in_one_shot(self):
        self.world.bp = 3  # Isolated collision fixture; full runs earn BP normally.
        self.world.move_player(-1);self.world.set_aim_target((96, 192));self.world.fire()
        hits = []
        for _ in range(3):hits.extend(self.world.advance_time(.25))
        boss_hits = [event for event in hits if event.target_id == 100]
        self.assertEqual(len(boss_hits), 3)
        self.assertEqual({event.projectile_id for event in boss_hits}, {1, 2, 3})
        self.assertTrue(all(event.damage == 5 for event in boss_hits))
        self.assertEqual(self.world.enemies[100].hp, 0)
        self.assertEqual([event.enemy_id for event in self.world.combat.death_events], [100])
        self.assertNotIn(100, [target.target_id for target in self.world.combat.targets()])

    def test_fire_targets_nearest_boss_and_charges_unchanged_cost_once(self):
        self.world.move_player(-1);self.world.select_spell('fire')
        result = self.world.cast_selected_spell()
        self.assertEqual(result.cast.targets.enemy_ids, (100,))
        self.assertEqual(self.world.enemies[100].hp, 0)
        self.assertEqual(self.world.enemies[101].hp, 15)
        self.assertEqual(self.world.mp, 70)
        self.assertEqual(self.world.spells.next_ready_turn('fire'), 5)
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.cast_selected_spell().valid)
        self.assertFalse(self.world.fire())
        self.assertEqual(vars(self.world), before)
        self.world.advance_time(.45);self.world.resolve_turn()
        self.assertEqual(self.world.hp, 95)
        self.assertEqual(self.world.enemies[101].turns_alive, 1)

    def test_starstorm_lands_direct_damage_before_bomb_chain_kills_bosses(self):
        world = playing(boss_definition(rows=(2, 4)))
        world.combat.add_enemy(Enemy(3, EnemyType.BOMB, 8, 3))
        world.select_spell('starstorm');self.assertTrue(world.cast_selected_spell().valid)
        changes = {item.enemy_id: item for item in world.last_spell_result.effects.changes}
        for enemy_id in (100, 101):
            self.assertEqual(changes[enemy_id].direct_damage, 10)
            self.assertEqual(changes[enemy_id].explosion_damage, 5)
        self.assertEqual([event.enemy_id for event in world.combat.death_events], [3, 100, 101])
        self.assertEqual([event.source for event in world.combat.death_events],
                         ['spell:starstorm', 'explosion', 'explosion'])
        self.assertFalse(world.crystals[2].collected)
        self.assertEqual((world.mp, world.bp, world.pending_bp), (60, 1, 0))

    def test_ward_blocks_one_boss_attack_not_the_entire_phase(self):
        perform_action(self.world, 'ward', 3)
        self.assertEqual((self.world.hp, self.world.mp), (95, 70))
        self.assertIsNone(self.world.statuses.get(StatusKind.WARD))
        blocks = [event for event in self.world.status_events if event.kind is StatusEventKind.WARD_BLOCKED]
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].source_id, blocks[0].attempted_damage), ('boss_attack', 5))
        self.assertEqual([enemy.grid_col for enemy in self.world.enemies.values()], [8, 8])

    def test_reraise_resolves_lethal_boss_attack_before_next_boss_acts(self):
        self.world.hp = 5  # Lethal-damage fixture, not a reachability demonstration.
        perform_action(self.world, 'reraise', 3)
        self.assertEqual(self.world.hp, 45)
        self.assertTrue(self.world.reraise_used)
        self.assertIsNone(self.world.statuses.get(StatusKind.RERAISE))
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        events = [event for event in self.world.status_events if event.kind in (
            StatusEventKind.DAMAGE, StatusEventKind.RERAISE_ACTIVATED)]
        self.assertEqual([event.hp_after for event in events], [0, 50, 45])
        self.assertTrue(all(enemy.turns_alive == 1 for enemy in self.world.enemies.values()))

    def test_knockout_stops_later_boss_and_turn_advancement(self):
        self.world.hp = 5
        perform_action(self.world, 'shot', 0)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertIs(self.world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertEqual((self.world.hp, self.world.turn_index), (0, 1))
        self.assertEqual(self.world.enemies[100].turns_alive, 1)
        self.assertEqual(self.world.enemies[101].turns_alive, 0)
        self.assertEqual(self.world.enemies[100].grid_col, 7)

    def test_pause_and_incomplete_animation_never_run_boss_actions(self):
        self.world.select_spell('ward');self.world.cast_selected_spell()
        self.world.advance_time(.1);self.world.pause()
        before = deepcopy(vars(self.world))
        for _ in range(5):self.world.advance_time(10000);self.assertFalse(self.world.resolve_turn())
        self.assertEqual(vars(self.world), before)
        self.world.resume();self.world.advance_time(.35)
        self.assertEqual(self.world.hp, 100)
        self.assertTrue(self.world.resolve_turn())
        self.assertFalse(self.world.resolve_turn())
        self.assertEqual(self.world.hp, 95)


class BossSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.definition = boss_definition(scripted=True)
        self.combat = Combat()
        self.encounter = Encounter(self.definition)
        self.encounter.spawn_due(1, self.combat)

    def test_live_stage_one_and_odin_boss_kinds_register_with_strict_validation(self):
        self.assertTrue(self.definition.playable)
        self.assertIsNotNone(World(encounter=self.definition))
        for stage, kind in ((3, 'odin'),):
            data = stage_data(stage)
            data['boss_wave'] = {'when': 'after_scripted_waves_cleared', 'spawns': [
                {'id': 100, 'kind': kind, 'col': 0, 'row': 3}]}
            data['completion']['mandatory_enemy_ids'].append(100)
            definition = parse_stage(data)
            self.assertTrue(definition.playable)
            self.assertIsNotNone(World(stages={1: self.definition, stage: definition}))
            data['boss_wave']['spawns'][0]['kind'] = 'unknown'
            with self.assertRaises(StageConfigurationError):parse_stage(data)

    def test_group_spawns_once_in_configured_order_only_after_scripted_defeat(self):
        self.assertFalse(self.encounter.boss_wave_spawned)
        self.assertEqual(self.encounter.spawn_due(2, self.combat), ())
        self.combat.apply_damage(1, 5)
        self.assertIsNone(self.encounter.outcome(self.combat))
        self.assertEqual(self.encounter.spawn_due(2, self.combat), (100, 101))
        first = self.combat.enemies[100]
        self.assertTrue(self.encounter.boss_wave_spawned)
        self.assertEqual(self.encounter.spawn_history, [1, 2, 100, 101])
        self.assertEqual(self.encounter.spawn_due(3, self.combat), ())
        self.assertIs(self.combat.enemies[100], first)
        self.assertFalse(self.encounter.boss_wave_ready(self.combat))
        reverse = Encounter(boss_definition(scripted=True, reverse=True)); combat = Combat()
        reverse.spawn_due(1, combat);combat.apply_damage(1, 5)
        self.assertEqual(reverse.spawn_due(2, combat), (101, 100))

    def test_no_boss_group_until_future_scripted_wave_and_partial_entries_finish(self):
        from dataclasses import replace
        from src.encounter import Spawn, Wave
        definition = replace(self.definition, waves=self.definition.waves + (Wave(3, (Spawn(3, 'basic', 0, 4),)),),
                             mandatory_enemy_ids=(1, 3, 100, 101))
        encounter = Encounter(definition);combat = Combat()
        encounter.spawn_due(1, combat);combat.apply_damage(1, 5)
        self.assertEqual(encounter.spawn_due(2, combat), ())
        self.assertFalse(encounter.boss_wave_ready(combat))
        self.assertEqual(encounter.spawn_due(3, combat), (3,))
        self.assertFalse(encounter.boss_wave_ready(combat))
        combat.apply_damage(3, 5)
        self.assertEqual(encounter.spawn_due(4, combat), (100, 101))

    def test_mandatory_escape_prevents_activation_and_terminates_failed_defense(self):
        self.combat.enemies[1].grid_col = 13;self.combat.enemies[1].escape(1)
        self.assertFalse(self.encounter.boss_wave_ready(self.combat))
        self.assertEqual(self.encounter.spawn_due(2, self.combat), ())
        self.assertIs(self.encounter.outcome(self.combat), EncounterOutcome.FAILED)
        self.assertFalse(self.encounter.boss_wave_spawned)

    def test_atomic_group_defers_at_capacity_or_occupied_cells(self):
        from dataclasses import replace
        for reason in ('capacity', 'occupied'):
            definition = replace(self.definition, capacity=2)
            encounter = Encounter(definition);combat = Combat()
            encounter.spawn_due(1, combat);combat.apply_damage(1, 5)
            blocker = Enemy(99, EnemyType.BASIC, 7 if reason == 'occupied' else 0, 2)
            combat.add_enemy(blocker)
            before = deepcopy(vars(combat));history = encounter.spawn_history[:]
            # Isolate preflight checks independently of the ordinary-enemy readiness gate.
            with patch.object(encounter, 'boss_wave_ready', return_value=True):
                self.assertEqual(encounter.spawn_due(2, combat), ())
            self.assertEqual(vars(combat), before)
            self.assertEqual(encounter.spawn_history, history)
            self.assertFalse(encounter.boss_wave_spawned)
            combat.apply_damage(99, 5)
            self.assertEqual(encounter.spawn_due(3, combat), (100, 101))

    def test_atomic_group_does_not_reuse_archived_reserved_ids(self):
        self.combat.apply_damage(1, 5)
        conflict = Enemy(101, EnemyType.BASIC, 0, 0);conflict.take_damage(5)
        self.combat.add_enemy(conflict)
        self.assertEqual(self.encounter.spawn_due(2, self.combat), ())
        self.assertNotIn(100, self.combat.enemies)
        self.assertIs(self.combat.enemies[101], conflict)
        self.assertFalse(self.encounter.boss_wave_spawned)

    def test_pending_deaths_or_bp_must_settle_before_boss_activation(self):
        self.combat._damage(1, 5, 'fixture')
        self.assertEqual(self.encounter.spawn_due(2, self.combat), ())
        self.combat.resolve_deaths();self.combat.pending_bp = 1
        self.assertEqual(self.encounter.spawn_due(2, self.combat), ())
        self.combat.finish_shot(1)
        self.assertEqual(self.encounter.spawn_due(2, self.combat), (100, 101))

    def test_escape_policy_is_strictly_validated(self):
        data = stage_data()
        data['boss_wave'] = {'when': 'after_scripted_waves_cleared', 'escape_policy': 'ignore',
                            'spawns': [{'id': 100, 'kind': 'ultros', 'col': 0, 'row': 3}]}
        data['completion']['mandatory_enemy_ids'].append(100)
        with self.assertRaisesRegex(StageConfigurationError, 'escape policy'):parse_stage(data)


if __name__ == '__main__':
    unittest.main()
