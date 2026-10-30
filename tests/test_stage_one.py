"""Canonical Stage 1: real World actions, posted controls, outcomes, and determinism."""

from copy import deepcopy
from dataclasses import asdict
import os
import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame

from config.prototype import PROTOTYPE
from src.combat import Combat
from src.encounter import Encounter, EncounterOutcome
from src.entities import Enemy, EnemyType
from src.game import Game
from src.renderer import Renderer
from src.stage_config import load_stage
from src.spells import SpellFailure
from src.states import GameState, GameOverReason
from src.statuses import StatusKind, StatusEventKind
from src.world import World, STAGE_ONE
from stage_one_fixtures import (
    OPENING_ROWS, DEFENSE_ROWS, boss_definition, clear_ordinary_waves, perform_action, playing,
)


class CanonicalStageOneTests(unittest.TestCase):
    def tearDown(self):
        pygame.quit()

    def test_default_stage_is_canonical_with_five_ramping_waves_and_two_mandatory_bosses(self):
        self.assertEqual(STAGE_ONE, load_stage('stage_01.json'))
        self.assertNotEqual(STAGE_ONE, PROTOTYPE)
        self.assertEqual([wave.turn for wave in STAGE_ONE.waves], [1, 3, 5, 7, 9])
        self.assertEqual([sum(s.kind != 'crystal' for s in wave.spawns) for wave in STAGE_ONE.waves],
                         [4, 5, 6, 6, 7])
        self.assertEqual(sum(s.kind == 'crystal' for wave in STAGE_ONE.waves for s in wave.spawns), 5)
        self.assertEqual(STAGE_ONE.capacity, 25)
        self.assertEqual(STAGE_ONE.boss_wave.escape_policy, 'contact_and_fail')
        self.assertEqual([(s.entity_id,s.kind,s.col,s.row) for s in STAGE_ONE.boss_wave.spawns],
                         [(100,'ultros',7,2),(101,'typhon',7,5)])
        self.assertEqual(len(STAGE_ONE.mandatory_ids), 30)
        self.assertTrue({100, 101} <= set(STAGE_ONE.mandatory_ids))
        self.assertEqual(dict(World(encounter=STAGE_ONE).stage_definitions), {1: STAGE_ONE})
        self.assertFalse(STAGE_ONE.final)

    def test_bosses_activate_after_final_scripted_action_and_never_during_its_animation(self):
        world = playing()
        for row in OPENING_ROWS[:-1]:perform_action(world, 'shot', row)
        self.assertFalse(world.encounter.boss_wave_spawned)
        perform_action(world, 'shot', OPENING_ROWS[-1], resolve=False)
        self.assertTrue(world.encounter.all_spawned)
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertIsNone(world.encounter.outcome(world.combat))
        self.assertFalse(world.check_stage_end())
        self.assertEqual(world.spawn_waves(), ())
        world.pause()
        self.assertEqual(world.spawn_waves(), ())
        self.assertFalse(world.resolve_turn())
        world.resume();self.assertTrue(world.resolve_turn())
        self.assertEqual(world.turn_index, 9)
        self.assertEqual(world.encounter.spawn_history,
                         list(range(1, 10)) + [11, 10] + list(range(12, 34)) + [100, 101])
        self.assertTrue(world.encounter.boss_wave_spawned)
        self.assertEqual(world.hp, 100)
        self.assertTrue(all(world.enemies[key].turns_alive == 0 for key in (100, 101)))
        self.assertEqual(world.spawn_waves(), ())

    def test_spell_clearing_scripted_fixture_waits_for_animation_before_bosses(self):
        world = playing(boss_definition(scripted=True))
        world.select_spell('fire');world.cast_selected_spell()
        self.assertIs(world.state, GameState.SPELL_ANIMATION)
        self.assertTrue(world.encounter.boss_wave_ready(world.combat))
        self.assertEqual(world.spawn_waves(), ())
        self.assertFalse(world.encounter.boss_wave_spawned)
        world.pause();before = deepcopy(vars(world))
        world.advance_time(1000);self.assertEqual(vars(world), before)
        world.resume();world.advance_time(.45)
        self.assertFalse(world.encounter.boss_wave_spawned)
        world.resolve_turn()
        self.assertTrue(world.encounter.boss_wave_spawned)
        self.assertEqual((world.hp,world.turn_index), (100,2))

    def test_either_living_boss_prevents_clear(self):
        for defeated, survivor in ((100, 101), (101, 100)):
            world = playing(boss_definition())
            world.combat.apply_damage(defeated, 15, 'fixture')
            perform_action(world, 'shot', 0)
            self.assertIs(world.state, GameState.PLAYER_AIM)
            self.assertEqual(world.enemies[survivor].hp, 15)
            self.assertIsNone(world.encounter.outcome(world.combat))

    def test_both_dead_bosses_do_not_clear_with_an_active_required_enemy(self):
        world = playing(boss_definition(scripted=True))
        perform_action(world, 'fire', 3)
        # Explicit completion-invariant fixture: restore a required ordinary actor.
        world.enemies[1].hp = 5
        world.combat.apply_damage(100, 15, 'fixture');world.combat.apply_damage(101, 15, 'fixture')
        perform_action(world, 'shot', 0)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertTrue(world.enemies[1].active)
        self.assertIsNone(world.encounter.outcome(world.combat))

    def test_dead_bosses_never_convert_a_mandatory_escape_into_success(self):
        definition = boss_definition(scripted=True)
        encounter = Encounter(definition);combat = Combat()
        encounter.spawn_due(1, combat)
        combat.enemies[1].grid_col = 13;combat.enemies[1].escape(1)
        # Archive fixture for the invariant, not a reachable boss-spawn shortcut.
        for key,kind,row in ((100,EnemyType.ULTROS,2),(101,EnemyType.TYPHON,5)):
            combat.add_enemy(Enemy(key, kind, 7, row));combat.apply_damage(key, 15, 'fixture')
        encounter.boss_wave_spawned = True
        self.assertIs(encounter.outcome(combat), EncounterOutcome.FAILED)

    def test_defeated_boss_objects_without_actual_group_spawn_do_not_count_as_completion(self):
        world = playing(boss_definition())
        world.combat.apply_damage(100, 15);world.combat.apply_damage(101, 15)
        world.encounter.boss_wave_spawned = False  # Invalid archive fixture; flag must still guard clear.
        self.assertIsNone(world.encounter.outcome(world.combat))
        self.assertTrue(world.encounter.all_spawned)
        self.assertTrue(all(not world.enemies[key].alive for key in world.encounter.definition.mandatory_ids))

    def test_mixed_normal_actions_clear_on_turn_eleven_without_extra_boss_attack(self):
        world = playing();clear_ordinary_waves(world)
        self.assertEqual((world.hp,world.bp), (100,5))
        perform_action(world, 'fire', 2)
        self.assertEqual((world.hp,world.mp), (95,70))
        self.assertEqual(world.enemies[100].hp, 0)
        self.assertEqual(world.enemies[101].hp, 15)
        perform_action(world, 'starstorm', 5)
        self.assertEqual((world.hp,world.mp), (90,30))
        self.assertEqual(world.enemies[101].hp, 5)
        hits = perform_action(world, 'shot', 5)
        self.assertTrue(any(event.target_id == 101 and event.damage == 4 for event in hits))
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual((world.turn_index,world.hp,world.mp,world.bp), (11,90,30,5))
        self.assertEqual(world.last_resolved_turn, 10)
        self.assertEqual(len(world.combat.death_events), 30)
        self.assertEqual(len({event.enemy_id for event in world.combat.death_events}), 30)
        self.assertEqual([event.enemy_id for event in world.combat.death_events[-2:]], [100,101])
        self.assertEqual(len([e for e in world.status_events if e.source_id == 'boss_attack']), 2)
        self.assertFalse(world.resolve_turn())
        self.assertFalse(world.can_advance_stage)
        self.assertFalse(world.advance_stage())
        self.assertFalse(world.transition_to(GameState.STAGE_INTRO))

    def test_shooting_only_clear_is_reachable_without_spending_mp(self):
        world = playing();clear_ordinary_waves(world)
        first = perform_action(world, 'shot', 2)
        self.assertGreaterEqual(len([hit for hit in first if hit.target_id == 100]), 3)
        perform_action(world, 'shot', 5)
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual((world.turn_index,world.hp,world.mp,world.bp), (10,95,100,5))

    def test_hp_defeat_is_reachable_with_ordinary_missed_shots(self):
        world = playing()
        for _ in range(30):
            if world.state is not GameState.PLAYER_AIM:break
            perform_action(world, 'shot', 0)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.HP_DEPLETED)
        self.assertEqual((world.hp,world.turn_index), (0,19))
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertEqual(sum(enemy.escaped for enemy in world.enemies.values()), 20)

    def test_defense_failure_is_reachable_without_hp_mutation_or_boss_softlock(self):
        world = playing()
        for row in DEFENSE_ROWS:perform_action(world, 'shot', row)
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertEqual((world.hp,world.turn_index,world.mp), (45,20,100))
        self.assertTrue(world.encounter.all_spawned)
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertFalse(any(enemy.active for enemy in world.enemies.values()))
        self.assertEqual((len(world.combat.death_events),sum(e.escaped for e in world.enemies.values())), (17,11))

    def test_boss_stage_clear_precedes_due_poison_doom_and_hazards(self):
        world = playing();clear_ordinary_waves(world)
        perform_action(world, 'fire', 2);perform_action(world, 'starstorm', 5)
        world.apply_status(StatusKind.POISON, 1)
        world.apply_status(StatusKind.DOOM, 1)
        world.place_poison_tile(5)
        # Make the fixtures due on the final player action.
        from dataclasses import replace
        for effect in world.statuses.snapshot():
            world.statuses.put(replace(effect, applied_turn=world.turn_index-1))
        tile = world.hazards.snapshot()[0]
        world.hazards.put(replace(tile, applied_turn=world.turn_index-1))
        before = world.snapshot()
        perform_action(world, 'shot', 5)
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual(world.hp, before.hp)
        self.assertEqual(world.snapshot().statuses, before.statuses)
        self.assertEqual(world.snapshot().hazards, before.hazards)

    def test_restart_clears_bosses_histories_resources_effects_and_completion_claim(self):
        world = playing();clear_ordinary_waves(world)
        perform_action(world, 'fire', 2);perform_action(world, 'starstorm', 5)
        perform_action(world, 'shot', 5)
        old = world.encounter
        world.apply_status(StatusKind.DOOM);world.place_poison_tile(3)
        self.assertTrue(world.restart())
        self.assertIs(world.state, GameState.STAGE_INTRO)
        self.assertEqual((world.stage,world.turn_index,world.hp,world.mp,world.bp), (1,1,100,100,1))
        self.assertIs(world.encounter.definition, STAGE_ONE)
        self.assertIsNot(world.encounter, old)
        self.assertEqual(world.encounter.spawn_history, [])
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertEqual(world.enemies, {})
        self.assertEqual(world.combat.death_events, [])
        self.assertEqual(world.status_events, ())
        self.assertEqual(world.projectiles, [])
        self.assertEqual(world.statuses.snapshot(), ())
        self.assertEqual(world.hazards.snapshot(), ())
        self.assertFalse(world.reraise_used)
        self.assertEqual(dict(world.spells.cooldowns), {})
        self.assertIsNone(world._pending_action)
        self.assertIsNone(world._cleared_stage)
        self.assertEqual((world._next_projectile_id,world._next_action_id,world._physics.accumulator), (1,1,0))
        self.assertIsNone(world.selected_spell)
        self.assertIsNone(world.last_spell_result)
        world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(list(world.enemies), [1,2,3,4])

    def test_restart_after_canonical_defeat_replays_canonical_not_prototype(self):
        world = playing()
        for row in DEFENSE_ROWS:perform_action(world, 'shot', row)
        self.assertTrue(world.restart())
        world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(world.encounter.definition, STAGE_ONE)
        self.assertEqual(world.snapshot().total_waves, 5)
        self.assertTrue(world.snapshot().has_boss_wave)
        self.assertFalse(world.encounter.boss_wave_spawned)

    def test_full_canonical_runs_match_across_frame_schedules(self):
        for scenario in ('clear', 'HP defeat', 'defense failure'):
            reference = None
            for schedule in ((1/30,), (1/60,), (1/144,), (.004,.041,.009,.024,.005,.017)):
                world = playing();history = []
                actions = ([('shot',row) for row in OPENING_ROWS] +
                           [('fire',2),('starstorm',5),('shot',5)] if scenario == 'clear' else
                           [('shot',0)]*19 if scenario == 'HP defeat' else
                           [('shot',row) for row in DEFENSE_ROWS])
                for kind,row in actions:
                    perform_action(world,kind,row,schedule)
                    history.append((world.snapshot(), tuple(world.combat.death_events),
                                    tuple((key,asdict(enemy)) for key,enemy in sorted(world.enemies.items())),
                                    tuple(world.encounter.spawn_history),
                                    tuple(world.spells.cooldowns.items())))
                if reference is None:reference=history
                self.assertEqual(history, reference, (scenario,schedule))

    def test_prototype_still_has_its_original_clear_path_and_no_boss_group(self):
        world = playing(PROTOTYPE)
        for row in (3,)*7:perform_action(world,'shot',row)
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual((world.turn_index,world.hp,world.mp,world.bp), (7,100,100,5))
        self.assertFalse(world.snapshot().has_boss_wave)
        self.assertEqual(len(world.combat.death_events), 24)

    def test_posted_game_events_complete_canonical_boss_encounter(self):
        pygame.display.init()
        game = Game();game.world = World(encounter=STAGE_ONE);game.running = True
        for key in (pygame.K_RETURN,pygame.K_RETURN):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=key))
        for event in pygame.event.get():game.handle_event(event)
        clear_ordinary_waves(game.world,game=game)
        for kind,row in (('fire',2),('starstorm',5),('shot',5)):
            perform_action(game.world,kind,row,game=game)
        self.assertIs(game.world.state, GameState.STAGE_CLEAR)
        self.assertEqual((game.world.hp,game.world.mp,game.world.bp), (90,30,5))
        before = deepcopy(vars(game.world))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertEqual(vars(game.world),before)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_r))
        self.assertIs(game.world.state, GameState.STAGE_INTRO)
        self.assertEqual(game.world.encounter.definition, STAGE_ONE)

    def test_boss_renderer_has_distinct_labels_and_is_read_only(self):
        pygame.display.init();pygame.font.init()
        screen = pygame.display.set_mode((960,576));renderer = Renderer()
        world = playing();clear_ordinary_waves(world)
        before = deepcopy(vars(world));snapshot = world.snapshot()
        self.assertTrue(snapshot.boss_wave_spawned)
        self.assertEqual((snapshot.bosses_remaining,snapshot.boss_total), (2,2))
        # Provided sprites use compact HP plates; missing art uses larger labels.
        with patch.object(renderer,'body_font', wraps=renderer.body_font) as font, \
                patch.object(renderer,'hud_font', wraps=renderer.hud_font) as hud_font:
            renderer.draw(screen,snapshot)
            labels=[call.args[0] for call in font.render.call_args_list + hud_font.render.call_args_list]
            self.assertIn('U15',labels);self.assertIn('T15',labels)
        self.assertEqual(vars(world),before)
        perform_action(world,'fire',2);perform_action(world,'starstorm',5);perform_action(world,'shot',5)
        with patch.object(renderer.screens,'_text',wraps=renderer.screens._text) as text:
            renderer.draw(screen,world.snapshot())
            labels=[call.args[1] for call in text.call_args_list]
        self.assertIn('Stage 1 encounter complete',labels)
        self.assertNotIn('Prototype encounter complete',labels)

    def test_meteor_remains_locked_and_selection_does_not_claim_boss_turn(self):
        world = playing();clear_ordinary_waves(world)
        self.assertIs(world.validate_spell('meteor').failure,SpellFailure.STAGE_LOCKED)
        self.assertFalse(world.select_spell('meteor'))
        self.assertIsNone(world._pending_action)
        self.assertEqual((world.hp,world.mp,world.turn_index),(100,100,9))


if __name__ == '__main__':
    unittest.main()
