"""Fixture-only multi-stage progression and deterministic scheduler extensions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import os
import unittest

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame

from src.combat import Combat
from src.encounter import Encounter, EncounterOutcome, Spawn, Wave
from src.entities import Enemy, EnemyType
from src.game import Game
from src.hazards import HazardState
from src.renderer import Renderer
from src.spells import SpellFailure
from src.stage_config import parse_stage
from src.states import GameState, GameOverReason
from src.statuses import StatusKind, StatusState
from src.world import World
from config.prototype import PROTOTYPE
from test_stage_config import stage_data


def definition(stage=1):
    return parse_stage(stage_data(stage))


def playing(stages=None):
    result = World(stages=stages) if stages is not None else World()
    result.start_new_run()
    result.transition_to(GameState.PLAYER_AIM)
    return result


def clear_stage(world):
    """Use real Fire commit, animation, and resolution against a one-enemy fixture."""
    assert world.select_spell('fire')
    assert world.cast_selected_spell().valid
    world.advance_time(.45)
    assert world.resolve_turn()


class StageSchedulerTests(unittest.TestCase):
    def test_capacity_defers_enemies_but_not_crystals_without_partial_completion(self):
        data = stage_data()
        data['capacity'] = 1
        data['waves'][0]['spawns'].insert(1, {'id': 3, 'kind': 'bomb', 'col': 1, 'row': 3})
        data['completion']['mandatory_enemy_ids'].append(3)
        encounter = Encounter(parse_stage(data)); combat = Combat()
        self.assertEqual(encounter.spawn_due(1, combat), (1, 2))
        self.assertEqual(list(combat.enemies), [1])
        self.assertEqual(list(combat.crystals), [2])
        self.assertEqual(encounter.spawned_waves, set())
        self.assertIsNone(encounter.outcome(combat))
        self.assertEqual(encounter.spawn_due(1, combat), ())
        combat.apply_damage(1, 5)
        self.assertEqual(encounter.spawn_due(2, combat), (3,))
        self.assertEqual(encounter.spawn_history, [1, 2, 3])
        self.assertTrue(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(3, combat), ())

    def test_capacity_counts_only_active_enemies_and_retry_order_is_stable(self):
        data = stage_data(); data['capacity'] = 1
        for entity_id, row in ((3, 4), (4, 5)):
            data['waves'][0]['spawns'].append({'id': entity_id, 'kind': 'basic', 'col': 0, 'row': row})
        definition = parse_stage(data)
        histories = []
        for reverse in (False, True):
            combat = Combat()
            dead = Enemy(90, EnemyType.BASIC, 0, 0); dead.take_damage(5)
            escaped = Enemy(91, EnemyType.BASIC, 13, 0); escaped.escape(1)
            for enemy in ([escaped, dead] if reverse else [dead, escaped]):combat.add_enemy(enemy)
            encounter = Encounter(definition)
            self.assertEqual(encounter.spawn_due(1, combat), (1, 2))
            combat.apply_damage(1, 5)
            self.assertEqual(encounter.spawn_due(2, combat), (3,))
            combat.apply_damage(3, 5)
            self.assertEqual(encounter.spawn_due(3, combat), (4,))
            histories.append(encounter.spawn_history)
        self.assertEqual(histories, [[1, 2, 3, 4], [1, 2, 3, 4]])

    def test_occupied_cell_deferral_does_not_overwrite_and_retries(self):
        encounter = Encounter(definition()); combat = Combat()
        blocker = Enemy(99, EnemyType.BASIC, 0, 3); combat.add_enemy(blocker)
        self.assertEqual(encounter.spawn_due(1, combat), (2,))
        self.assertFalse(encounter.all_spawned)
        self.assertIs(combat.enemies[99], blocker)
        blocker.advance_one_cell()
        self.assertEqual(encounter.spawn_due(2, combat), (1,))
        self.assertTrue(encounter.all_spawned)
        self.assertEqual(encounter.spawn_history, [2, 1])

    def test_optional_enemy_must_leave_play_before_clear_and_its_escape_is_not_mandatory(self):
        data = stage_data()
        data['waves'][0]['spawns'].append({'id': 3, 'kind': 'basic', 'col': 13, 'row': 0})
        encounter = Encounter(parse_stage(data)); combat = Combat()
        encounter.spawn_due(1, combat)
        combat.apply_damage(1, 5)
        self.assertIsNone(encounter.outcome(combat))
        combat.enemies[3].escape(1)
        self.assertIs(encounter.outcome(combat), EncounterOutcome.CLEARED)

    def test_mandatory_escape_is_failure_even_after_all_other_enemies_are_defeated(self):
        data = stage_data(); data['waves'][0]['spawns'][0]['col'] = 13
        world = playing({1: parse_stage(data)})
        world.select_spell('ward'); world.cast_selected_spell()
        world.advance_time(.45); world.resolve_turn()
        self.assertIs(world.state, GameState.GAME_OVER)
        self.assertIs(world.game_over_reason, GameOverReason.DEFENSE_FAILED)
        self.assertEqual(world.hp, 100)
        self.assertEqual(world.combat.death_events, [])

    def test_future_wave_accelerates_after_last_enemy_dies_without_premature_clear(self):
        data = stage_data()
        data['waves'].append({'turn': 3, 'spawns': [{'id': 3, 'kind': 'basic', 'col': 0, 'row': 4}]})
        data['completion']['mandatory_enemy_ids'].append(3)
        world = playing({1: parse_stage(data)})
        clear_stage(world)
        self.assertIs(world.state, GameState.PLAYER_AIM)
        self.assertEqual(world.turn_index, 2)
        self.assertEqual(world.snapshot().spawned_waves, 2)
        self.assertIn(3, world.enemies)
        self.assertEqual(world.enemies[3].turns_alive, 0)


class StageProgressionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {stage: definition(stage) for stage in (1, 2, 3)}
        self.world = playing(self.catalog)

    def tearDown(self):
        pygame.quit()

    def test_nonfinal_clear_waits_for_explicit_progression(self):
        clear_stage(self.world)
        self.assertIs(self.world.state, GameState.STAGE_CLEAR)
        self.assertEqual((self.world.stage, self.world.turn_index), (1, 1))
        self.assertTrue(self.world.can_advance_stage)
        self.assertTrue(self.world.snapshot().next_stage_available)
        self.assertFalse(self.world.resolve_turn())

    def test_advance_loads_registered_next_stage_and_initial_wave_only_after_intro(self):
        clear_stage(self.world)
        previous = self.world.encounter
        self.assertTrue(self.world.advance_stage())
        self.assertIs(self.world.state, GameState.STAGE_INTRO)
        self.assertEqual(self.world.stage, 2)
        self.assertEqual(self.world.encounter.definition, self.catalog[2])
        self.assertEqual(self.world.encounter.spawn_history, [])
        self.assertEqual(self.world.enemies, {})
        self.assertFalse(self.world.advance_stage())
        self.world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(self.world.encounter.spawn_history, [1, 2])
        self.assertEqual(previous.spawn_history, [1, 2])
        self.assertIsNot(self.world.encounter, previous)

    def test_missing_next_stage_keeps_clear_screen_atomic(self):
        world = playing({1: definition(1), 3: definition(3)})
        clear_stage(world)
        before = deepcopy(vars(world))
        self.assertFalse(world.advance_stage())
        self.assertFalse(world.transition_to(GameState.STAGE_INTRO))
        self.assertEqual(vars(world), before)
        self.assertFalse(world.snapshot().next_stage_available)

    def test_stage_transition_resets_resources_effects_cooldowns_histories_and_ids(self):
        world = self.world
        world.execute_support_spell('ward-fixture', 'ward')
        world.execute_support_spell('revival-fixture', 'reraise')
        world.apply_status(StatusKind.BIND)
        world.apply_status(StatusKind.POISON)
        world.apply_status(StatusKind.DOOM)
        world.place_poison_tile(3)
        world.hp = 17; world.bp = 5; world.player_row = 3
        world.aim_target = (96., 240.)
        world._physics.accumulator = .004
        world._next_projectile_id = 90
        world.mp = 30  # Exact Fire threshold in this resource/reset fixture.
        archived = Enemy(99, EnemyType.BOMB, 13, 0)
        archived.escape(1)
        world.combat.add_enemy(archived)
        clear_stage(world)
        self.assertTrue(world.reraise_used)
        previous_encounter = world.encounter
        previous_combat = world.combat
        self.assertTrue(world.advance_stage())
        self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp), (2, 1, 100, 100, 1))
        self.assertEqual(world.statuses, StatusState())
        self.assertEqual(world.hazards, HazardState())
        self.assertEqual(world.status_events, ())
        self.assertFalse(world.reraise_used)
        self.assertEqual(dict(world.spells.cooldowns), {})
        self.assertEqual(world.spells._committed_actions, {})
        self.assertIsNone(world.selected_spell)
        self.assertEqual(world.spell_feedback, '')
        self.assertIsNone(world.last_spell_result)
        self.assertEqual(world.projectiles, [])
        self.assertEqual(world._physics.accumulator, 0)
        self.assertEqual((world._next_projectile_id, world._next_action_id), (1, 1))
        self.assertIsNone(world._pending_turn)
        self.assertIsNone(world.last_resolved_turn)
        self.assertIsNone(world.game_over_reason)
        self.assertEqual(world.combat.death_events, [])
        self.assertEqual(world.enemies, {})
        self.assertTrue(previous_combat.enemies[99].escaped)
        self.assertEqual(world.encounter.spawn_history, [])
        self.assertIsNot(world.encounter, previous_encounter)
        self.assertEqual(len(previous_combat.death_events), 1)
        self.assertEqual(world.player_row, 3)
        self.assertIsNone(world.aim_target)
        world.transition_to(GameState.PLAYER_AIM)
        self.assertTrue(world.execute_support_spell('revival-fixture', 'reraise').valid)

    def test_every_main_action_and_pause_state_rejects_stage_advancement(self):
        for spell in (False, True):
            world = playing(self.catalog)
            if spell:
                world.select_spell('ward'); world.cast_selected_spell()
            else:
                world.set_aim_target((96, 240)); world.fire()
            self.assertEqual(world.spawn_waves(), ())
            for paused in (False, True):
                if paused:world.pause()
                before = deepcopy(vars(world))
                self.assertFalse(world.advance_stage())
                self.assertFalse(world.transition_to(GameState.STAGE_CLEAR))
                self.assertFalse(world.transition_to(GameState.VICTORY))
                self.assertEqual(vars(world), before)
            world.resume()
            if spell:world.advance_time(.45)
            else:
                for _ in range(20):world.advance_time(.25)
            before = deepcopy(vars(world))
            self.assertFalse(world.advance_stage())
            self.assertEqual(world.spawn_waves(), ())
            self.assertEqual(vars(world), before)

    def test_manual_scene_edges_never_authorize_clear_or_victory(self):
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.transition_to(GameState.STAGE_CLEAR))
        self.assertFalse(self.world.transition_to(GameState.VICTORY))
        self.assertEqual(vars(self.world), before)
        self.world.transition_to(GameState.SHOT_ANIMATION)
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.assertFalse(self.world.resolve_turn())
        self.assertFalse(self.world.transition_to(GameState.STAGE_CLEAR))
        self.assertFalse(self.world.transition_to(GameState.VICTORY))
        self.assertFalse(self.world.advance_stage())

    def test_defeating_every_enemy_without_a_main_action_cannot_authorize_progression(self):
        self.world.combat.apply_damage(1, 5)
        self.world.transition_to(GameState.SPELL_ANIMATION)
        self.world.transition_to(GameState.TURN_RESOLVE)
        self.assertTrue(self.world.check_stage_end())
        self.assertFalse(self.world.resolve_turn())
        self.assertFalse(self.world.transition_to(GameState.STAGE_CLEAR))
        self.assertFalse(self.world.advance_stage())
        self.assertEqual(self.world.stage, 1)

    def test_restart_from_later_clear_or_defeat_returns_to_stage_one(self):
        for defeated in (False, True):
            world = playing(self.catalog)
            clear_stage(world); world.advance_stage()
            world.transition_to(GameState.PLAYER_AIM)
            if defeated:
                world.apply_player_damage(100)
            else:
                clear_stage(world)
            self.assertTrue(world.restart())
            self.assertEqual((world.stage, world.turn_index), (1, 1))
            self.assertIs(world.state, GameState.STAGE_INTRO)
            self.assertEqual(world.encounter.definition, self.catalog[1])

    def test_posted_results_and_restart_controls_with_final_stage_fixture(self):
        pygame.display.init()
        world = self.world
        for stage in (1, 2, 3):
            clear_stage(world)
            if stage < 3:
                world.advance_stage(); world.transition_to(GameState.PLAYER_AIM)
        game = Game(); game.running = True; game.world = world
        for key in (pygame.K_RETURN, pygame.K_r):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key))
            for event in pygame.event.get():game.handle_event(event)
            self.assertIs(world.state, GameState.RESULTS if key == pygame.K_RETURN else GameState.STAGE_INTRO)
        self.assertEqual(world.stage, 1)

    def test_stage_clear_precedes_harm_and_enemy_phase(self):
        self.world.apply_status(StatusKind.POISON, 1)
        self.world.apply_status(StatusKind.DOOM, 1)
        self.world.place_poison_tile(3)
        self.world.turn_index = 2; self.world.hp = 3
        before = self.world.snapshot()
        clear_stage(self.world)
        self.assertIs(self.world.state, GameState.STAGE_CLEAR)
        self.assertEqual(self.world.hp, 3)
        self.assertEqual(self.world.snapshot().statuses, before.statuses)
        self.assertEqual(self.world.snapshot().hazards, before.hazards)
        self.assertIsNone(self.world.last_resolved_turn)

    def test_stage_specific_spell_unlocks_follow_registered_stage(self):
        self.assertIs(self.world.validate_spell('esuna').failure, SpellFailure.STAGE_LOCKED)
        self.assertIs(self.world.validate_spell('meteor').failure, SpellFailure.STAGE_LOCKED)
        clear_stage(self.world); self.world.advance_stage()
        self.world.transition_to(GameState.PLAYER_AIM)
        self.assertTrue(self.world.validate_spell('esuna').valid)
        self.assertTrue(self.world.validate_spell('levitation').valid)
        self.assertIs(self.world.validate_spell('meteor').failure, SpellFailure.STAGE_LOCKED)
        clear_stage(self.world); self.world.advance_stage()
        self.world.transition_to(GameState.PLAYER_AIM)
        self.assertTrue(self.world.validate_spell('meteor').valid)

    def test_three_fixture_stages_distinguish_clear_victory_and_results(self):
        for stage in (1, 2, 3):
            clear_stage(self.world)
            if stage < 3:
                self.assertIs(self.world.state, GameState.STAGE_CLEAR)
                self.assertTrue(self.world.advance_stage())
                self.world.transition_to(GameState.PLAYER_AIM)
            else:
                self.assertIs(self.world.state, GameState.VICTORY)
                self.assertFalse(self.world.advance_stage())
                self.assertFalse(self.world.transition_to(GameState.STAGE_CLEAR))
                self.assertTrue(self.world.transition_to(GameState.RESULTS))
                self.assertFalse(self.world.transition_to(GameState.RESULTS))

    def test_full_run_restart_returns_to_first_stage_with_original_catalog(self):
        for terminal in (GameState.VICTORY, GameState.RESULTS):
            world = playing(self.catalog)
            for stage in (1, 2, 3):
                clear_stage(world)
                if stage < 3:
                    world.advance_stage(); world.transition_to(GameState.PLAYER_AIM)
            if terminal is GameState.RESULTS:world.transition_to(terminal)
            self.assertTrue(world.restart())
            self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp),
                             (1, 1, 100, 100, 1))
            self.assertIs(world.state, GameState.STAGE_INTRO)
            self.assertEqual(dict(world.stage_definitions), self.catalog)
            self.assertEqual(world.encounter.spawn_history, [])
            world.transition_to(GameState.PLAYER_AIM)
            self.assertEqual(world.encounter.spawn_history, [1, 2])

    def test_registry_requires_valid_matching_stage_one_and_is_detached(self):
        for invalid in ({}, {2: definition(2)}, {1: 'bad'}, {1: definition(2)},
                        {True: definition(1)}, [], None):
            if invalid is None:continue  # None intentionally selects the default prototype.
            with self.subTest(registry=invalid), self.assertRaises(ValueError):World(stages=invalid)
        with self.assertRaises(ValueError):World(demo=False, stages=self.catalog)
        with self.assertRaises(ValueError):World(encounter=definition(2))
        supplied = dict(self.catalog)
        world = World(stages=supplied)
        supplied.clear()
        self.assertEqual(set(world.stage_definitions), {1, 2, 3})
        with self.assertRaises(TypeError):world.stage_definitions[2] = definition(2)

    def test_explicit_prototype_fixture_remains_stage_one_only(self):
        world = World(encounter=PROTOTYPE)
        self.assertEqual(set(world.stage_definitions), {1})
        # Candidate B's stronger Bombs need a longer, valid shooting route.
        for row in (3,) * 7:
            if world.state is GameState.MENU:
                world.start_new_run(); world.transition_to(GameState.PLAYER_AIM)
            while world.player_row != row:world.move_player(1 if world.player_row < row else -1)
            world.set_aim_target((96, 96 + 48 * row)); world.fire()
            for _ in range(20):world.advance_time(.25)
            world.resolve_turn()
        self.assertIs(world.state, GameState.STAGE_CLEAR)
        self.assertEqual((world.hp, world.mp, world.bp), (100, 100, 5))
        self.assertFalse(world.advance_stage())
        self.assertTrue(world.restart())

    def test_posted_enter_advances_only_an_authorized_registered_clear(self):
        pygame.display.init()
        game = Game(); game.running = True; game.world = self.world
        clear_stage(game.world)
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        for event in pygame.event.get():game.handle_event(event)
        self.assertEqual(game.world.stage, 2)
        self.assertIs(game.world.state, GameState.STAGE_INTRO)

    def test_rendering_stage_clear_and_future_terminal_scenes_is_read_only(self):
        pygame.display.init(); pygame.font.init()
        screen = pygame.display.set_mode((960, 576)); renderer = Renderer()
        for stage in (1, 2, 3):
            clear_stage(self.world)
            before = deepcopy(vars(self.world))
            for _ in range(3):renderer.draw(screen, self.world.snapshot())
            self.assertEqual(vars(self.world), before)
            if stage < 3:
                self.world.advance_stage(); self.world.transition_to(GameState.PLAYER_AIM)
        self.world.transition_to(GameState.RESULTS)
        before = deepcopy(vars(self.world)); renderer.draw(screen, self.world.snapshot())
        self.assertEqual(vars(self.world), before)


if __name__ == '__main__':
    unittest.main()
