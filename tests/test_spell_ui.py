"""Posted Pygame input, immutable HUD data, and full spell application flow."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import os
import unittest
from unittest.mock import Mock, patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame

from src.constants import LOGICAL_SIZE
from src.game import Game
from prototype_fixtures import prototype_game
from src.player_actions import SPELL_ANIMATION_SECONDS
from src.renderer import Renderer
from src.spells import SpellId
from src.states import GameState
from src.statuses import StatusKind
from src.world import World
from config.prototype import PROTOTYPE
from test_spell_actions import finish_action


class SpellUITests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode(LOGICAL_SIZE)
        pygame.event.clear()
        self.game = prototype_game()
        self.game.running = True
        self.game.world.start_new_run()
        self.game.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self):
        pygame.quit()

    def key(self, value, *, repeat=False):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value, repeat=repeat))
        for event in pygame.event.get():
            self.game.handle_event(event)

    def click(self, target=(96, 240)):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=target))
        for event in pygame.event.get():
            self.game.handle_event(event)

    def test_all_eight_numeric_mappings_in_an_isolated_stage_three_context(self):
        self.game.world.stage = 3
        expected = ('fire', 'starstorm', 'meteor', 'cure', 'esuna', 'levitation', 'ward', 'reraise')
        for number, spell_id in enumerate(expected, start=1):
            self.key(getattr(pygame, f'K_{number}'))
            self.assertEqual(self.game.world.selected_spell.value, spell_id)
        self.assertEqual((self.game.world.mp, self.game.world.turn_index), (100, 1))
        self.assertEqual(dict(self.game.world.spells.cooldowns), {})

    def test_stage_one_locks_preserve_selection_and_feedback_is_readable(self):
        self.key(pygame.K_1)
        for key in (pygame.K_3, pygame.K_5, pygame.K_6):
            self.key(key)
            self.assertIs(self.game.world.selected_spell, SpellId.FIRE)
            self.assertEqual(self.game.world.spell_feedback, 'Spell locked')
        self.assertEqual(self.game.world.stage, 1)

    def test_repeated_selection_or_cast_keys_have_no_effect(self):
        before = deepcopy(vars(self.game.world))
        self.key(pygame.K_7, repeat=True)
        self.key(pygame.K_SPACE, repeat=True)
        self.assertEqual(vars(self.game.world), before)
        self.key(pygame.K_7)
        self.key(pygame.K_SPACE, repeat=True)
        self.assertEqual(self.game.world.mp, 100)
        self.key(pygame.K_SPACE)
        before = deepcopy(vars(self.game.world))
        for _ in range(5):
            self.key(pygame.K_SPACE)
        self.click()
        self.assertEqual(vars(self.game.world), before)
        self.assertEqual(self.game.world.mp, 70)

    def test_selection_and_casting_are_ignored_in_other_scenes(self):
        owner = self.game.world
        owner.select_spell('ward')
        owner.cast_selected_spell()
        for paused in (False, True):
            if paused:
                owner.pause()
            before = deepcopy(vars(owner))
            for value in (pygame.K_1, pygame.K_8, pygame.K_SPACE):
                self.key(value)
            self.assertEqual(vars(owner), before)
        owner.resume()
        finish_action(owner, resolve=False)
        for state in (GameState.TURN_RESOLVE, GameState.GAME_OVER):
            if state is GameState.GAME_OVER:
                owner.force_player_knockout()
            before = deepcopy(vars(owner))
            self.key(pygame.K_2)
            self.key(pygame.K_SPACE)
            self.assertEqual(vars(owner), before)
        owner.start_new_run()
        for menu in (True, False):
            if menu:
                owner.reset()
            else:
                owner.start_new_run()
            before = deepcopy(vars(owner))
            self.key(pygame.K_1)
            self.key(pygame.K_SPACE)
            self.assertEqual(vars(owner), before)

    def test_no_selection_and_full_hp_cure_do_not_prevent_ward(self):
        self.key(pygame.K_SPACE)
        self.assertEqual(self.game.world.spell_feedback, 'Select a spell with 1-8')
        self.key(pygame.K_4)
        self.key(pygame.K_SPACE)
        self.assertEqual(self.game.world.spell_feedback, 'Cure requires missing HP')
        self.key(pygame.K_7)
        self.key(pygame.K_SPACE)
        self.assertEqual(self.game.world.spell_feedback, 'Cast: Pom Ward')
        self.assertIs(self.game.world.state, GameState.SPELL_ANIMATION)

    def test_invalid_fire_allows_movement_aiming_and_clicking(self):
        self.key(pygame.K_UP)
        self.key(pygame.K_1)
        self.key(pygame.K_SPACE)
        self.assertEqual(self.game.world.spell_feedback, 'No valid target')
        self.click((96, 192))
        self.assertIs(self.game.world.state, GameState.SHOT_ANIMATION)
        self.assertEqual(self.game.world.mp, 100)

    def test_insufficient_mp_feedback_has_no_action_or_history(self):
        self.game.world.mp = 29
        self.key(pygame.K_7)
        self.key(pygame.K_SPACE)
        self.assertEqual(self.game.world.spell_feedback, 'Not enough MP')
        self.assertIs(self.game.world.state, GameState.PLAYER_AIM)
        self.assertIsNone(self.game.world.snapshot().pending_action)
        self.assertEqual(dict(self.game.world.spells.cooldowns), {})

    def test_select_fire_then_click_uses_shot_without_casting(self):
        self.key(pygame.K_1)
        self.click()
        self.key(pygame.K_SPACE)
        self.assertEqual(self.game.world.mp, 100)
        self.assertEqual(dict(self.game.world.spells.cooldowns), {})
        self.assertIs(self.game.world.state, GameState.SHOT_ANIMATION)
        finish_action(self.game.world)
        self.assertEqual((self.game.world.bp, self.game.world.turn_index), (2, 2))

    def test_hud_exposes_selected_cost_ready_turn_failure_and_status_countdown(self):
        self.key(pygame.K_7)
        owner = self.game.world
        owner.apply_status(StatusKind.DOOM)
        owner.apply_status(StatusKind.BIND)
        owner.apply_status(StatusKind.RERAISE)
        snapshot = owner.snapshot()
        self.assertTrue(snapshot.spell_hud.ready)
        self.assertEqual(snapshot.spell_hud.definition.mp_cost, 30)
        self.assertEqual(snapshot.spell_hud.next_ready_turn, 1)
        renderer = Renderer()
        before = deepcopy(vars(owner))
        with patch.object(renderer.hud, '_text', wraps=renderer.hud._text) as text:
            renderer.draw(self.screen, snapshot)
        labels = [call.args[1] for call in text.call_args_list]
        for label in ('[7] Pom Ward', 'MP 30', 'Ready - Space to cast', 'Cooldown clear',
                      '! DOOM 5t', '! Bind 1t', '+ Reraise 1-use'):
            self.assertIn(label, labels)
        self.assertEqual(vars(owner), before)
        with self.assertRaises(FrozenInstanceError):
            snapshot.spell_hud.next_ready_turn = 0

    def test_animation_rendering_does_not_advance_or_repeat_effects(self):
        self.key(pygame.K_1)
        self.key(pygame.K_SPACE)
        owner = self.game.world
        renderer = Renderer()
        for paused in (False, True):
            if paused:
                self.key(pygame.K_ESCAPE)
            before = deepcopy(vars(owner))
            with patch.object(renderer.hud, '_text', wraps=renderer.hud._text) as text:
                for _ in range(5):
                    renderer.draw(self.screen, owner.snapshot())
                self.assertTrue(any('Pom Fire' in call.args[1] for call in text.call_args_list))
            self.assertEqual(vars(owner), before)
        self.assertEqual((owner.mp, len(owner.combat.death_events)), (70, 6))

    def test_restart_from_stage_clear_resets_ui_and_action_sequence(self):
        # Ordinary controls, including Fire as the final action.
        for turn, row in enumerate((3, 3, 2, 2, 4, 4, 3), start=1):
            while self.game.world.player_row != row:
                self.key(pygame.K_DOWN if self.game.world.player_row < row else pygame.K_UP)
            if turn == 7:
                self.key(pygame.K_1)
                self.key(pygame.K_SPACE)
            else:
                self.click((96, 96 + 48 * row))
            finish_action(self.game.world)
        self.assertIs(self.game.world.state, GameState.STAGE_CLEAR)
        before = deepcopy(vars(self.game.world))
        self.key(pygame.K_8)
        self.key(pygame.K_SPACE)
        self.assertEqual(vars(self.game.world), before)
        self.key(pygame.K_r)
        snapshot = self.game.world.snapshot()
        self.assertIs(snapshot.state, GameState.STAGE_INTRO)
        self.assertIsNone(snapshot.selected_spell)
        self.assertEqual(snapshot.spell_feedback, '')
        self.assertIsNone(snapshot.spell_result)
        self.assertEqual(self.game.world._next_action_id, 1)

    def test_full_prototype_mixed_spells_and_shots_use_one_action_each_turn(self):
        owner = self.game.world
        for turn, row in enumerate((3, 3, 2, 2, 4, 4, 3), start=1):
            self.assertEqual(owner.turn_index, turn)
            while owner.player_row != row:
                self.key(pygame.K_DOWN if owner.player_row < row else pygame.K_UP)
            if turn == 2:
                self.key(pygame.K_SPACE)
                self.assertEqual(owner.spell_feedback, 'Spell on cooldown')
                self.assertEqual(owner.mp, 70)
            if turn == 3:
                self.key(pygame.K_8)
                self.key(pygame.K_SPACE)
                self.assertEqual(owner.spell_feedback, 'Not enough MP')
                self.assertEqual(owner.mp, 40)
            if turn in (1, 7):
                self.key(pygame.K_1)
                self.key(pygame.K_SPACE)
            elif turn == 2:
                self.key(pygame.K_7)
                self.key(pygame.K_SPACE)
            else:
                self.click((96, 96 + 48 * row))
            finish_action(owner)
        self.assertIs(owner.state, GameState.STAGE_CLEAR)
        self.assertEqual((owner.turn_index, owner.hp, owner.mp, owner.bp), (7, 100, 10, 4))
        self.assertEqual(len(owner.combat.death_events), 24)
        self.assertEqual(owner.encounter.spawned_waves, {0, 1, 2, 3})
        self.assertIsNone(owner.snapshot().pending_action)

    def test_game_loop_pause_and_resume_does_not_apply_paused_elapsed_time(self):
        self.game = prototype_game()
        self.game.world = World(demo=False)
        original_draw = Renderer.draw
        clock = Mock()
        progress = {'frames': 0, 'paused': False, 'held': None, 'resumed': False}
        def draw(renderer, screen, snapshot):
            original_draw(renderer, screen, snapshot)
            progress['frames'] += 1
            self.assertLess(progress['frames'], 20)
            clock.tick.return_value = 10000 if snapshot.state is GameState.PAUSED else 100
            if snapshot.state in (GameState.MENU, GameState.STAGE_INTRO):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
            elif snapshot.state is GameState.PLAYER_AIM:
                if snapshot.turn_index == 2:
                    self.assertEqual(snapshot.mp, 70)
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                else:
                    for value in (pygame.K_7, pygame.K_SPACE):
                        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value))
            elif snapshot.state is GameState.SPELL_ANIMATION:
                if not progress['paused']:
                    self.assertEqual(snapshot.spell_remaining, SPELL_ANIMATION_SECONDS)
                    progress['paused'] = True
                    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
                elif not progress['resumed']:
                    self.assertEqual(snapshot.spell_remaining, SPELL_ANIMATION_SECONDS)
                    progress['resumed'] = True
            elif snapshot.state is GameState.PAUSED:
                if progress['held'] is None:
                    progress['held'] = snapshot
                self.assertEqual(snapshot, progress['held'])
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        with patch('src.game.pygame.time.Clock', return_value=clock), \
                patch.object(Renderer, 'draw', autospec=True, side_effect=draw):
            self.game.run()
        self.assertTrue(progress['resumed'])
        self.assertEqual(self.game.world.turn_index, 2)
        self.assertFalse(pygame.display.get_init())

    def test_same_frame_queued_spell_and_shot_commit_only_first_valid_action(self):
        for order in ('spell-first', 'shot-first'):
            owner = World(encounter=PROTOTYPE)
            owner.start_new_run()
            owner.transition_to(GameState.PLAYER_AIM)
            self.game.world = owner
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_7))
            spell = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
            shot = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 240))
            for event in ((spell, shot, spell) if order == 'spell-first' else (shot, spell, shot)):
                pygame.event.post(event)
            for event in pygame.event.get():
                self.game.handle_event(event)
            self.assertEqual(owner._next_action_id, 2)
            self.assertEqual(owner.mp, 70 if order == 'spell-first' else 100)
            self.assertEqual(len(owner.projectiles), 0 if order == 'spell-first' else 1)
            finish_action(owner)
            self.assertEqual(owner.turn_index, 2)


if __name__ == '__main__':
    unittest.main()
