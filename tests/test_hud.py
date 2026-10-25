"""Snapshot-only HUD semantics, layout, rendering safety, and campaign regressions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from itertools import cycle
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame

from src.assets import AssetManager
from src.game import Game
from src.hud import (
    CombatHUD, PANELS, HP_PANEL, MP_PANEL, BP_PANEL, STATUS_PANEL, SPELL_PANEL,
    FEEDBACK_PANEL, SHORTCUT_PANEL, HP_COLOR, HARMFUL, MP_COLOR, BP_COLOR, ACCENT,
    TEXT_CACHE_LIMIT, spell_availability, cooldown_label, status_labels, hazard_label,
)
from src.player_actions import SpellHUD, spell_failure_message
from src.renderer import Renderer
from src.spells import SpellFailure, SpellId, get_spell
from src.states import GameState
from src.statuses import StatusKind
from src.world import World
from stage_one_fixtures import perform_action, OPENING_ROWS
from stage_two_fixtures import STAGE_TWO_CLEAR
from stage_three_fixtures import METEOR_CLEAR


class HUDTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init(); pygame.font.init()
        self.screen = pygame.display.set_mode((960, 576))
        self.hud = CombatHUD()
        self.world = World()
        self.world.start_new_run(); self.world.transition_to(GameState.PLAYER_AIM)

    def tearDown(self):
        pygame.quit()

    def labels(self, snapshot=None):
        with patch.object(self.hud, '_text', wraps=self.hud._text) as text:
            self.hud.draw(self.screen, snapshot or self.world.snapshot())
        return [call.args[1] for call in text.call_args_list]

    def selected(self, spell, *, failure=None, ready=1, **changes):
        # Detached presentation fixtures exercise every model-supplied failure;
        # actual validation remains covered through World and Game below.
        return replace(self.world.snapshot(), selected_spell=SpellId(spell),
                       spell_hud=SpellHUD(get_spell(spell), ready, failure), **changes)

    def test_all_panels_fit_canvas_and_reserved_regions_without_overlap(self):
        screen = pygame.Rect(0, 0, 960, 576)
        field = pygame.Rect(96, 72, 672, 384)
        for index, bounds in enumerate(PANELS):
            rect = pygame.Rect(bounds)
            self.assertTrue(screen.contains(rect))
            self.assertFalse(rect.colliderect(field))
            self.assertTrue(rect.bottom <= 64 or rect.top >= 464)
            for other in PANELS[index + 1:]:
                self.assertFalse(rect.colliderect(other))

    def test_drawing_hud_does_not_touch_battlefield_or_player_lane(self):
        color = (123, 34, 56)
        self.screen.fill(color)
        self.hud.draw(self.screen, self.world.snapshot())
        for rect in (pygame.Rect(96, 72, 672, 384), pygame.Rect(800, 72, 48, 384)):
            pixels = pygame.image.tobytes(self.screen.subsurface(rect), 'RGB')
            self.assertEqual(pixels, bytes(color) * (rect.w * rect.h))

    def test_hp_full_partial_low_and_zero_have_exact_bar_lengths_and_labels(self):
        for value in (100, 50, 5, 0):
            with self.subTest(hp=value):
                snapshot = replace(self.world.snapshot(), hp=value)
                self.assertIn(f'HP {value}/100', self.labels(snapshot))
                x, y = HP_PANEL[0] + 10, HP_PANEL[1] + 36
                color = HARMFUL if value <= 25 else HP_COLOR
                pixels = [self.screen.get_at((x + i, y))[:3] for i in range(192)]
                self.assertEqual(pixels.count(color), int(192 * value / 100))

    def test_mp_uses_authoritative_maximum_and_no_passive_animation(self):
        for value in (100, 70, 20, 0):
            self.assertIn(f'MP {value}/100', self.labels(replace(self.world.snapshot(), mp=value)))
            x, y = MP_PANEL[0] + 10, MP_PANEL[1] + 36
            count = sum(self.screen.get_at((x + i, y))[:3] == MP_COLOR for i in range(192))
            self.assertEqual(count, int(192 * value / 100))

    def test_resource_maxima_are_read_from_snapshot(self):
        labels = self.labels(replace(self.world.snapshot(), hp=30, max_hp=150, mp=40, max_mp=200))
        self.assertIn('HP 30/150', labels); self.assertIn('MP 40/200', labels)

    def test_bp_one_through_five_matches_next_volley_pips(self):
        for bp in range(1, 6):
            self.assertIn(f'BP {bp}/5', self.labels(replace(self.world.snapshot(), bp=bp)))
            for index in range(5):
                center = (BP_PANEL[0] + 26 + index * 37, BP_PANEL[1] + 41)
                self.assertEqual(self.screen.get_at(center)[:3] == BP_COLOR, index < bp)

    def test_pending_bp_is_outline_and_does_not_raise_available_volley(self):
        labels = self.labels(replace(self.world.snapshot(), bp=2, pending_bp=2))
        self.assertIn('BP 2/5', labels); self.assertIn('+2 pending', labels)
        for index in (2, 3):
            x, y = BP_PANEL[0] + 10 + index * 37, BP_PANEL[1] + 36
            self.assertEqual(self.screen.get_at((x, y))[:3], ACCENT)
            self.assertNotEqual(self.screen.get_at((x + 16, y + 5))[:3], BP_COLOR)

    def test_stage_turn_and_wave_counts_are_snapshot_values(self):
        for stage, waves in ((1, 5), (2, 6), (3, 7)):
            labels = self.labels(replace(self.world.snapshot(), stage=stage, turn_index=19,
                                         spawned_waves=waves, total_waves=waves))
            self.assertIn(f'Stage {stage}  Turn 19', labels)
            self.assertTrue(any(f'Waves {waves}/{waves}' in label for label in labels))

    def test_boss_progress_is_separate_from_scripted_wave_counts(self):
        labels = self.labels(replace(self.world.snapshot(), spawned_waves=5, total_waves=5,
                                     boss_wave_spawned=True, bosses_remaining=1, boss_total=2))
        self.assertIn('Waves 5/5 | Bosses alive 1/2', labels)
        self.assertTrue(any('Boss pending' in label for label in self.labels()))
        self.assertIn('Waves: —', self.labels(replace(self.world.snapshot(), total_waves=0,
                                                   has_boss_wave=False)))

    def test_score_is_an_unavailable_placeholder_without_model_field(self):
        self.assertIn('Score: —', self.labels())
        self.assertFalse(hasattr(self.world, 'score'))
        self.assertFalse(hasattr(self.world.snapshot(), 'score'))

    def test_no_selection_explains_free_selection_and_one_main_action(self):
        labels = self.labels()
        self.assertIn('No spell selected', labels)
        self.assertIn('Select an unlocked spell', labels)
        self.assertIn('Selection is free; one shot OR spell per turn', labels)

    def test_all_eight_spell_names_keys_and_costs_use_existing_definitions(self):
        for number, spell in enumerate(SpellId, 1):
            definition = get_spell(spell)
            labels = self.labels(self.selected(spell.value, stage=3))
            self.assertIn(f'[{number}] {definition.name}', labels)
            self.assertIn(f'MP {definition.mp_cost}', labels)

    def test_ready_selection_uses_world_validation(self):
        self.assertTrue(self.world.select_spell('fire'))
        self.assertTrue(self.world.snapshot().spell_hud.ready)
        self.assertIn('Ready - Space to cast', self.labels())

    def test_absolute_cooldown_turn_and_remaining_turns(self):
        snapshot = self.selected('fire', failure=SpellFailure.COOLDOWN, ready=5, turn_index=2)
        labels = self.labels(snapshot)
        self.assertIn('Spell on cooldown', labels)
        self.assertIn('Ready T5 - 3 turns remaining', labels)
        self.assertEqual(cooldown_label(replace(snapshot, turn_index=4)), 'Ready T5 - 1 turn remaining')
        self.assertEqual(cooldown_label(replace(snapshot, turn_index=5)), 'Cooldown clear')

    def test_insufficient_mp_is_not_misrepresented_as_cooldown(self):
        self.world.mp = 29
        self.world.select_spell('fire')
        self.assertEqual(self.world.snapshot().spell_hud.failure, SpellFailure.INSUFFICIENT_MP)
        labels = self.labels()
        self.assertIn('Not enough MP', labels); self.assertIn('Cooldown clear', labels)
        self.assertNotIn('Spell on cooldown', labels)

    def test_no_target_and_full_hp_cure_have_model_failure_messages(self):
        self.world.move_player(-1); self.world.move_player(-1); self.world.move_player(-1)
        self.world.select_spell('fire')
        self.assertIn('No valid target', self.labels())
        self.world.select_spell('cure')
        self.assertIn('Cure requires missing HP', self.labels())

    def test_reraise_used_message_and_failed_cast_feedback(self):
        self.world.reraise_used = True
        self.world.select_spell('reraise'); result = self.world.cast_selected_spell()
        self.assertFalse(result.valid)
        self.assertIn('Reraise already used', self.labels())
        self.assertEqual((self.world.mp, self.world.turn_index), (100, 1))

    def test_locked_selection_keeps_previous_spell_and_actual_feedback(self):
        self.world.select_spell('fire')
        self.assertFalse(self.world.select_spell('meteor'))
        labels = self.labels()
        self.assertIn('[1] Pom Fire', labels); self.assertNotIn('[3] Pom Meteor', labels)
        self.assertIn('Spell locked', labels)
        self.assertIs(self.world.selected_spell, SpellId.FIRE)

    def test_stage_unlock_tags_follow_catalog_without_extra_validation(self):
        for stage, count in ((1, 3), (2, 1), (3, 0)):
            labels = self.labels(replace(self.world.snapshot(), stage=stage))
            tags = [label for label in labels if label in ('S2', 'S3')]
            self.assertEqual(len(tags), count)
            for definition in (get_spell(spell) for spell in SpellId):
                if definition.unlock_stage > stage:
                    self.assertIn(f'S{definition.unlock_stage}', tags)

    def test_uncommon_model_restriction_is_preserved_verbatim(self):
        snapshot = self.selected('fire', failure=SpellFailure.STATUS_RESTRICTED)
        self.assertEqual(spell_availability(snapshot), spell_failure_message(SpellFailure.STATUS_RESTRICTED))

    def test_projectile_animation_does_not_advertise_ready_casting(self):
        self.world.select_spell('ward'); self.world.set_aim_target((96, 240)); self.world.fire()
        labels = self.labels()
        self.assertIn('VOLLEY IN FLIGHT', labels); self.assertIn('Main action unavailable', labels)
        self.assertNotIn('Ready - Space to cast', labels)

    def test_spell_animation_has_committed_values_and_cast_identity(self):
        self.world.select_spell('ward'); self.assertTrue(self.world.cast_selected_spell().valid)
        labels = self.labels()
        for text in ('MP 70/100', '[7] Pom Ward', 'SPELL IN PROGRESS', 'Cast: Pom Ward'):
            self.assertIn(text, labels)
        self.assertNotIn('Ready - Space to cast', labels)

    def test_turn_resolution_does_not_advertise_ready_casting(self):
        self.world.select_spell('ward'); self.world.cast_selected_spell(); self.world.advance_time(.5)
        self.assertIs(self.world.state, GameState.TURN_RESOLVE)
        labels = self.labels()
        self.assertIn('RESOLVING TURN', labels); self.assertIn('Main action unavailable', labels)

    def test_pause_is_explicit_even_if_snapshot_ready_flag_was_true(self):
        snapshot = self.selected('ward', state=GameState.PAUSED, paused_state=GameState.PLAYER_AIM)
        labels = self.labels(snapshot)
        self.assertIn('Paused - actions unavailable', labels); self.assertIn('PAUSED', labels)
        self.assertNotIn('Ready - Space to cast', labels)

    def test_no_effects_has_explicit_none_label(self):
        labels = self.labels()
        self.assertIn('Effects', labels); self.assertIn('None', labels)
        self.assertIn('Tiles: none', labels)

    def test_all_six_effects_are_distinct_and_readable_with_correct_durations(self):
        for kind in StatusKind:
            self.world.apply_status(kind)
        labels = self.labels()
        for label in ('! Poison 3t', '! Bind 1t', '! DOOM 5t', '+ Ward 1t',
                      '+ Levitation 1t', '+ Reraise 1-use'):
            self.assertIn(label, labels)
        self.assertFalse(any('Reraise' in label and ('99' in label or 'None' in label) for label in labels))
        for _, label, _ in status_labels(self.world.snapshot()):
            self.assertFalse(label.endswith('seconds'))

    def test_refreshed_status_displays_new_remaining_duration(self):
        self.world.apply_status(StatusKind.POISON, 1)
        self.assertIn('! Poison 1t', self.labels())
        self.world.apply_status(StatusKind.POISON, 3)
        self.assertIn('! Poison 3t', self.labels()); self.assertNotIn('! Poison 1t', self.labels())

    def test_ward_and_levitation_disappear_only_after_model_expiration(self):
        self.world.apply_status(StatusKind.WARD); self.world.apply_status(StatusKind.LEVITATION)
        perform_action(self.world, 'shot', 3)
        self.assertFalse(status_labels(self.world.snapshot()))
        labels = self.labels()
        self.assertNotIn('+ Ward 1t', labels); self.assertNotIn('+ Levitation 1t', labels)

    def test_ward_consumption_reflects_unchanged_hp(self):
        self.world.apply_status(StatusKind.WARD)
        self.assertEqual(self.world.apply_player_damage(40), 0)
        labels = self.labels()
        self.assertIn('HP 100/100', labels); self.assertNotIn('+ Ward 1t', labels)

    def test_cure_and_reraise_use_real_updated_hp_not_cached_values(self):
        self.labels()
        self.world.apply_player_damage(70)
        self.assertIn('HP 30/100', self.labels())
        self.assertTrue(self.world.execute_support_spell('heal-fixture', 'cure').valid)
        self.assertIn('HP 80/100', self.labels()); self.assertIn('MP 90/100', self.labels())
        self.world.apply_status(StatusKind.RERAISE); self.world.apply_player_damage(100)
        labels = self.labels()
        self.assertIn('HP 50/100', labels); self.assertNotIn('+ Reraise 1-use', labels)

    def test_hazards_show_only_snapshot_rows_and_levitation_protection(self):
        self.world.place_poison_tile(0)
        self.assertEqual(hazard_label(self.world.snapshot()), 'Tiles 1')
        self.world.place_poison_tile(3)
        self.assertEqual(hazard_label(self.world.snapshot()), 'Tiles 2 | Here 2t / new')
        self.world.apply_status(StatusKind.LEVITATION)
        self.assertEqual(hazard_label(self.world.snapshot()), 'Tiles 2 | Here 2t / protected')
        self.world.remove_poison_tile(3)
        self.assertEqual(hazard_label(self.world.snapshot()), 'Tiles 1')

    def test_invalid_input_feedback_does_not_lock_shooting(self):
        game = Game(); game.running = True; game.world = self.world
        for key in (pygame.K_4, pygame.K_SPACE):
            game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
        self.assertIn('Cure requires missing HP', self.labels())
        before = deepcopy(vars(self.world)); self.labels()
        self.assertEqual(vars(self.world), before)
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 240)))
        self.assertIs(self.world.state, GameState.SHOT_ANIMATION)

    def test_every_text_rectangle_fits_its_panel_with_all_effects_and_long_feedback(self):
        for kind in StatusKind: self.world.apply_status(kind)
        for row in range(8): self.world.place_poison_tile(row)
        snapshot = self.selected('levitation', stage=3, spell_feedback=('A long future feedback message ' * 20))
        actual = []
        original = self.hud._text
        def record(*args, **kwargs):
            rect = original(*args, **kwargs)
            actual.append((args[1], rect))
            return rect
        with patch.object(self.hud, '_text', side_effect=record):
            self.hud.draw(self.screen, snapshot)
        for text, rect in actual:
            self.assertTrue(any(pygame.Rect(panel).contains(rect) for panel in PANELS), (text, rect))
            self.assertFalse(rect.colliderect(pygame.Rect(96, 72, 672, 384)))
        # Ellipsis bounds excess text without shrinking any fonts.
        self.assertTrue(any(key[1].endswith('...') for key in self.hud._text_cache))
        self.assertGreaterEqual(self.hud.fonts['small'].get_height(), 13)

    def test_common_labels_are_not_ellipsized_or_squeezed(self):
        for kind in StatusKind: self.world.apply_status(kind)
        self.world.select_spell('starstorm')
        self.world.spell_feedback = 'Cure requires missing HP'
        self.labels()
        self.assertFalse(any(key[1].endswith('...') for key in self.hud._text_cache))

    def test_fonts_are_created_once_and_cache_is_bounded(self):
        with patch('src.hud.pygame.font.Font', side_effect=AssertionError('Per-frame font allocation')):
            for value in range(TEXT_CACHE_LIMIT + 20):
                self.labels(replace(self.world.snapshot(), turn_index=value + 1,
                                    spell_feedback=f'Message {value}'))
                self.assertLessEqual(len(self.hud._text_cache), TEXT_CACHE_LIMIT)

    def test_identical_draw_reuses_text_surfaces(self):
        self.labels(); cached = dict(self.hud._text_cache)
        self.labels()
        self.assertEqual(dict(self.hud._text_cache), cached)
        for key, surface in cached.items(): self.assertIs(self.hud._text_cache[key], surface)

    def test_repeated_draws_preserve_world_events_snapshots_and_scene(self):
        self.world.apply_status(StatusKind.DOOM); self.world.place_poison_tile(3)
        self.world.select_spell('fire')
        snapshot = self.world.snapshot(); before = deepcopy(vars(self.world))
        for _ in range(30): self.hud.draw(self.screen, snapshot)
        self.assertEqual(vars(self.world), before); self.assertEqual(self.world.snapshot(), snapshot)
        with self.assertRaises(FrozenInstanceError): snapshot.mp = 0

    def test_present_and_missing_assets_keep_hud_without_audio_or_disk_reads(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'images').mkdir()
            for asset_root in (None, root):
                with patch('src.assets.pygame.mixer.init', side_effect=AssertionError('Audio initialization')):
                    if asset_root is None: renderer = Renderer()
                    else:
                        with self.assertLogs('src.assets', level='WARNING'):
                            renderer = Renderer(AssetManager(asset_root))
                    with patch('src.assets.pygame.image.load', side_effect=AssertionError('Per-frame disk read')):
                        for _ in range(3): renderer.draw(self.screen, self.world.snapshot())
                    self.assertFalse(pygame.mixer.get_init())
                    self.assertEqual(self.screen.get_at((26, 44))[:3], HP_COLOR)

    def test_pause_overlay_preserves_legible_panels_and_readonly_world(self):
        renderer = Renderer(); self.world.select_spell('ward'); self.world.cast_selected_spell()
        self.world.pause(); before = deepcopy(vars(self.world))
        renderer.draw(self.screen, self.world.snapshot())
        self.assertEqual(self.screen.get_at((26, 44))[:3], HP_COLOR)
        self.assertEqual(vars(self.world), before)
        self.assertIn('Paused - actions unavailable', self.labels())

    def test_restart_clears_presentation_values_without_stale_cache(self):
        self.world.select_spell('ward'); self.world.cast_selected_spell(); self.labels()
        self.world.advance_time(.5); self.world.resolve_turn()
        self.world.apply_player_damage(1000)
        self.assertIs(self.world.state, GameState.GAME_OVER)
        self.assertTrue(self.world.restart()); self.world.transition_to(GameState.PLAYER_AIM)
        labels = self.labels()
        for label in ('HP 100/100', 'MP 100/100', 'BP 1/5', 'No spell selected', 'None', 'Tiles: none'):
            self.assertIn(label, labels)
        self.assertNotIn('Cast: Pom Ward', labels)
        self.assertEqual(dict(self.world.spells.cooldowns), {})

    def test_stage_transition_uses_fresh_resources_effects_and_hud_unlocks(self):
        for row in OPENING_ROWS + (2, 5): perform_action(self.world, 'shot', row)
        self.assertTrue(self.world.advance_stage()); self.world.transition_to(GameState.PLAYER_AIM)
        labels = self.labels()
        for label in ('Stage 2  Turn 1', 'HP 100/100', 'MP 100/100', 'BP 1/5', 'No spell selected'):
            self.assertIn(label, labels)
        self.assertNotIn('S2', labels); self.assertIn('S3', labels)


class HUDCampaignTests(unittest.TestCase):
    def test_campaign_with_rendering_is_identical_at_four_frame_schedules(self):
        pygame.display.init(); pygame.font.init()
        self.addCleanup(pygame.quit)
        screen = pygame.display.set_mode((960, 576)); renderer = Renderer()
        reference = None
        for schedule in ((1/30,), (1/60,), (1/144,), (.007, .041, .013, .09)):
            game = Game(); game.running = True; world = game.world; times = cycle(schedule); history = []
            def key(value):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value))
                for event in pygame.event.get(): game.handle_event(event)
            key(pygame.K_RETURN); key(pygame.K_RETURN)
            routes = (tuple(('shot', r) for r in OPENING_ROWS + (2, 5)), STAGE_TWO_CLEAR, METEOR_CLEAR)
            for stage, route in enumerate(routes, 1):
                for kind, row in route:
                    while world.player_row != row:
                        key(pygame.K_DOWN if world.player_row < row else pygame.K_UP)
                    if kind == 'shot':
                        pos = (96, 96 + 48 * row)
                        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=pos))
                        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
                        for event in pygame.event.get(): game.handle_event(event)
                    else:
                        key(getattr(pygame, f'K_{list(SpellId).index(SpellId(kind)) + 1}')); key(pygame.K_SPACE)
                    while world.state in (GameState.SHOT_ANIMATION, GameState.SPELL_ANIMATION):
                        world.advance_time(next(times))
                        renderer.draw(screen, world.snapshot())
                    self.assertTrue(world.resolve_turn())
                    snapshot = world.snapshot(); before = deepcopy(vars(world))
                    renderer.draw(screen, snapshot)
                    self.assertEqual(vars(world), before)
                    history.append((snapshot, tuple(world.combat.death_events), world.status_events,
                                    tuple(world.encounter.spawn_history)))
                if stage < 3:
                    self.assertIs(world.state, GameState.STAGE_CLEAR)
                    key(pygame.K_RETURN); key(pygame.K_RETURN)
            self.assertIs(world.state, GameState.VICTORY); key(pygame.K_RETURN)
            self.assertIs(world.state, GameState.RESULTS)
            self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp), (3, 22, 5, 20, 5))
            if reference is None: reference = history
            self.assertEqual(history, reference, schedule)
