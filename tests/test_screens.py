"""Screen content, navigation boundaries, rendering purity, and campaign regression."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame

from src.assets import AssetManager
from src.constants import LOGICAL_SIZE, WINDOW_TITLE
from src.game import Game
from src.renderer import Renderer
from src.screens import ScreenRenderer, SCREEN_CACHE_LIMIT, INSTRUCTION_CARDS, INSTRUCTION_BOUNDS, FRAME
from src.states import ACTIVE_STATES, GameState, GameOverReason, INSTRUCTION_PAGE_COUNT
from src.statuses import StatusKind
from src.world import World
from stage_one_fixtures import OPENING_ROWS, perform_action
from stage_two_fixtures import STAGE_TWO_CLEAR
from stage_three_fixtures import METEOR_CLEAR
from test_scenes import world_in_state


TERMINALS = (GameState.STAGE_CLEAR, GameState.GAME_OVER, GameState.VICTORY, GameState.RESULTS)


class ScreenNavigationTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init(); pygame.font.init()
        self.screen = pygame.display.set_mode(LOGICAL_SIZE)
        self.game = Game(); self.game.running = True
        self.world = self.game.world

    def tearDown(self): pygame.quit()

    def key(self, key, **kwargs):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, **kwargs))
        for event in pygame.event.get(): self.game.handle_event(event)

    def test_start_game_enters_intro_then_first_wave(self):
        self.key(pygame.K_RETURN)
        self.assertIs(self.world.state, GameState.STAGE_INTRO)
        self.assertFalse(self.world.encounter.spawn_history)
        self.key(pygame.K_RETURN)
        self.assertIs(self.world.state, GameState.PLAYER_AIM)
        self.assertEqual(self.world.encounter.spawned_waves, {0})

    def test_instructions_key_opens_help_without_starting_run(self):
        self.key(pygame.K_i)
        self.assertIs(self.world.state, GameState.INSTRUCTIONS)
        self.assertFalse(self.world.encounter.spawn_history)
        self.assertEqual((self.world.hp, self.world.mp, self.world.bp, self.world.turn_index), (100, 100, 1, 1))

    def test_both_back_keys_restore_menu_without_resetting_resources(self):
        for back in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self.world.hp, self.world.mp, self.world.bp = 40, 35, 3
            before = deepcopy(vars(self.world))
            self.key(pygame.K_i); self.key(pygame.K_RIGHT); self.key(back)
            self.assertEqual(vars(self.world), before)
            self.assertTrue(self.game.running)

    def test_help_page_navigation_is_bounded_and_repeat_safe(self):
        self.key(pygame.K_i)
        self.key(pygame.K_LEFT); self.assertEqual(self.world.instructions_page, 0)
        self.key(pygame.K_RIGHT, repeat=True); self.assertEqual(self.world.instructions_page, 0)
        self.key(pygame.K_RIGHT); self.assertEqual(self.world.instructions_page, 1)
        self.key(pygame.K_RIGHT); self.assertEqual(self.world.instructions_page, 1)
        self.key(pygame.K_PAGEUP); self.assertEqual(self.world.instructions_page, 0)
        self.key(pygame.K_PAGEDOWN); self.assertEqual(self.world.instructions_page, 1)

    def test_help_reopens_at_first_page(self):
        self.key(pygame.K_i); self.key(pygame.K_RIGHT); self.key(pygame.K_ESCAPE)
        self.key(pygame.K_i)
        self.assertEqual(self.world.snapshot().instructions_page, 0)

    def test_help_ignores_start_restart_cast_and_movement_inputs(self):
        self.key(pygame.K_i); before = deepcopy(vars(self.world))
        for value in (pygame.K_RETURN, pygame.K_r, pygame.K_SPACE, pygame.K_1, pygame.K_w, pygame.K_s):
            self.key(value)
        for event in (pygame.event.Event(pygame.MOUSEMOTION, pos=(96, 240)),
                      pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 240))):
            self.game.handle_event(event)
        self.assertEqual(vars(self.world), before)

    def test_help_never_ticks_statuses_hazards_or_cooldowns(self):
        self.world.apply_status(StatusKind.POISON); self.world.place_poison_tile(3)
        self.key(pygame.K_i); before = deepcopy(vars(self.world))
        renderer = Renderer()
        for _ in range(8):
            self.world.advance_time(1000)
            self.assertFalse(self.world.resolve_turn())
            renderer.draw(self.screen, self.world.snapshot())
        self.assertEqual(vars(self.world), before)

    def test_help_cannot_bypass_authorized_stage_transitions(self):
        self.key(pygame.K_i); before = deepcopy(vars(self.world))
        for target in (GameState.STAGE_INTRO, GameState.PLAYER_AIM, *TERMINALS, GameState.PAUSED):
            self.assertFalse(self.world.transition_to(target))
            self.assertEqual(vars(self.world), before)

    def test_page_api_rejects_invalid_changes_outside_help(self):
        before = deepcopy(vars(self.world))
        self.assertFalse(self.world.change_instructions_page(1))
        self.assertEqual(vars(self.world), before)
        self.key(pygame.K_i); before = deepcopy(vars(self.world))
        for delta in (True, 0, 2, 'next', None, 1.0):
            self.assertFalse(self.world.change_instructions_page(delta))
            self.assertEqual(vars(self.world), before)

    def test_instruction_page_snapshot_is_immutable_and_detached(self):
        self.key(pygame.K_i); snapshot = self.world.snapshot()
        self.key(pygame.K_RIGHT)
        self.assertEqual(snapshot.instructions_page, 0)
        self.assertEqual(self.world.snapshot().instructions_page, 1)
        with self.assertRaises(FrozenInstanceError): snapshot.instructions_page = 1

    def test_instructions_key_is_ignored_outside_menu(self):
        for state in GameState:
            if state is GameState.MENU: continue
            self.game.world = world_in_state(state)
            before = deepcopy(vars(self.game.world)); self.key(pygame.K_i)
            self.assertEqual(vars(self.game.world), before)

    def test_repeated_navigation_keys_cannot_start_skip_restart_or_toggle_pause(self):
        for state in GameState:
            self.game.world = world_in_state(state)
            before = deepcopy(vars(self.game.world))
            for value in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_r, pygame.K_i, pygame.K_BACKSPACE):
                self.key(value, repeat=True)
            self.assertEqual(vars(self.game.world), before)
            self.assertTrue(self.game.running)

    def test_escape_from_menu_exits_cleanly(self):
        self.key(pygame.K_ESCAPE)
        self.assertFalse(self.game.running)

    def test_closing_window_works_from_every_scene_including_help(self):
        for state in GameState:
            self.game.running = True; self.game.world = world_in_state(state)
            before = deepcopy(vars(self.game.world))
            self.game.handle_event(pygame.event.Event(pygame.QUIT))
            self.assertFalse(self.game.running); self.assertEqual(vars(self.game.world), before)

    def test_pause_restores_every_exact_active_phase_and_metadata(self):
        for state in ACTIVE_STATES:
            self.game.world = world_in_state(state)
            self.game.world.apply_status(StatusKind.DOOM); self.game.world.place_poison_tile(3)
            before = self.game.world.snapshot()
            self.key(pygame.K_ESCAPE); paused = deepcopy(vars(self.game.world))
            for _ in range(4):
                self.game.world.advance_time(1000); self.game.world.resolve_turn()
                Renderer().draw(self.screen, self.game.world.snapshot())
            self.assertEqual(vars(self.game.world), paused)
            self.key(pygame.K_ESCAPE); self.assertEqual(self.game.world.snapshot(), before)

    def test_real_shot_and_spell_pause_preserves_animation_and_pending_action(self):
        self.key(pygame.K_RETURN); self.key(pygame.K_RETURN)
        self.world.set_aim_target((96, 240)); self.assertTrue(self.world.fire())
        for kind in ('shot', 'spell'):
            if kind == 'spell':
                while self.world.state is GameState.SHOT_ANIMATION: self.world.advance_time(.25)
                self.world.resolve_turn(); self.world.select_spell('ward'); self.world.cast_selected_spell()
            self.world.advance_time(.004); before = self.world.snapshot()
            self.key(pygame.K_ESCAPE); self.world.advance_time(1000)
            for value in (pygame.K_i, pygame.K_SPACE, pygame.K_r): self.key(value)
            self.key(pygame.K_ESCAPE)
            self.assertEqual(self.world.snapshot(), before)

    def test_paused_frame_elapsed_time_does_not_leak_on_resume_in_real_loop(self):
        for spell in (False, True):
            game = Game(); snapshots = []; step = 0; previous = None
            clock = Mock(); clock.tick.side_effect = lambda fps: 10000 if game.world.state is GameState.PAUSED else 100
            original = Renderer.draw
            def key(value): pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value))
            def drive(renderer, screen, snapshot):
                nonlocal step, previous
                original(renderer, screen, snapshot); snapshots.append(snapshot)
                if step == 0: key(pygame.K_RETURN); step = 1
                elif step == 1: key(pygame.K_RETURN); step = 2
                elif step == 2:
                    if spell: key(pygame.K_7); key(pygame.K_SPACE)
                    else: pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96,240)))
                    step = 3
                elif step == 3: previous = snapshot; key(pygame.K_ESCAPE); step = 4
                elif step == 4:
                    self.assertIs(snapshot.state, GameState.PAUSED)
                    key(pygame.K_ESCAPE); step = 5
                else:
                    self.assertEqual(snapshot, previous)
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
            with patch('src.game.pygame.time.Clock', return_value=clock), \
                 patch.object(Renderer, 'draw', autospec=True, side_effect=drive): game.run()
            self.assertEqual(len(snapshots), 6)
            self.assertFalse(game.running)
            pygame.display.init(); pygame.font.init(); self.screen = pygame.display.set_mode(LOGICAL_SIZE)

    def test_terminal_restart_uses_existing_full_run_reset(self):
        for state in TERMINALS:
            self.game.world = world_in_state(state)
            self.game.world.apply_status(StatusKind.DOOM); self.game.world.place_poison_tile(2)
            self.game.world.mp = 3; self.key(pygame.K_r)
            expected = World(encounter=self.game.world._encounter_definition)
            expected.start_new_run()
            self.assertEqual(vars(self.game.world), vars(expected))

    def test_unauthorized_scene_edges_cannot_clear_or_win(self):
        self.key(pygame.K_RETURN); self.key(pygame.K_RETURN)
        for target in (GameState.STAGE_CLEAR, GameState.VICTORY, GameState.RESULTS, GameState.INSTRUCTIONS):
            before = deepcopy(vars(self.world))
            self.assertFalse(self.world.transition_to(target))
            self.assertEqual(vars(self.world), before)


class ScreenDrawingTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init(); pygame.font.init()
        self.screen = pygame.display.set_mode(LOGICAL_SIZE)
        self.renderer = Renderer(); self.world = World()

    def tearDown(self): pygame.quit()

    def labels(self, snapshot):
        with patch.object(self.renderer.screens, '_text', wraps=self.renderer.screens._text) as text:
            self.renderer.draw(self.screen, snapshot)
        return [call.args[1] for call in text.call_args_list]

    def snapshot(self, state, **changes):
        return replace(self.world.snapshot(), state=state, **changes)

    def test_menu_identifies_game_and_only_real_keyboard_actions(self):
        labels = self.labels(self.world.snapshot())
        for text in (WINDOW_TITLE, 'Enter: Start Game', 'I: Instructions', 'Escape: Quit'):
            self.assertIn(text, labels)
        self.assertFalse(any('Settings' in text or 'Continue Game' in text for text in labels))

    def test_every_instruction_section_and_control_is_present(self):
        self.assertEqual(len(INSTRUCTION_CARDS), INSTRUCTION_PAGE_COUNT)
        content = []
        for page in range(INSTRUCTION_PAGE_COUNT):
            content.extend(self.labels(self.snapshot(GameState.INSTRUCTIONS, instructions_page=page)))
        joined = ' '.join(content)
        for text in ('W / Up Arrow', 'S / Down Arrow', 'Mouse:', 'Left-click:',
                     'One successful shot OR spell', 'selection are free', 'Failed casts spend no MP or turn',
                     'maximum 5', 'future volleys', 'does not consume BP', 'Space:', 'cooldowns',
                     'S1:', 'S2 adds', 'S3 adds', 'Poison:', 'Bind:', 'Doom:', 'Ward:', 'Levitation:',
                     'Reraise:', 'Stage 3 ends in Victory', 'Escape', 'Backspace', 'Game Over', 'Results'):
            self.assertIn(text, joined)
        self.assertIn('Esuna removes Poison/Bind, not Doom.', content)

    def test_instruction_navigation_prompt_and_page_number(self):
        for page in range(2):
            labels = self.labels(self.snapshot(GameState.INSTRUCTIONS, instructions_page=page))
            self.assertIn(f'Page {page + 1} / 2', labels)
            self.assertIn('Left / Right: Pages     Escape / Backspace: Back to Menu', labels)

    def test_stage_intros_identify_stage_bosses_and_wave_counts(self):
        for stage, bosses, waves in ((1, 'Ultros and Typhon', 5), (2, 'Chichu', 6), (3, 'Odin', 7)):
            labels = self.labels(self.snapshot(GameState.STAGE_INTRO, stage=stage,
                                               total_waves=waves, has_boss_wave=True))
            self.assertIn(f'Stage {stage}', labels); self.assertIn(bosses, labels)
            self.assertIn(f'{waves} scripted waves', labels); self.assertIn('Enter: Continue', labels)

    def test_stage_intro_does_not_advertise_bosses_for_prototype_fixture(self):
        labels = self.labels(self.snapshot(GameState.STAGE_INTRO, has_boss_wave=False))
        self.assertIn('Encounter goal', labels)
        self.assertNotIn('Ultros and Typhon', labels)

    def test_intro_unlocks_come_from_existing_catalog(self):
        for stage in (1, 2, 3):
            joined = ' '.join(self.labels(self.snapshot(GameState.STAGE_INTRO, stage=stage)))
            self.assertEqual('Meteor' in joined, stage == 3)
            self.assertEqual('Levitation' in joined, stage >= 2)
            self.assertEqual('Esuna' in joined, stage >= 2)

    def test_stage_clear_prompt_obeys_snapshot_advance_availability(self):
        for stage in (1, 2):
            labels = self.labels(self.snapshot(GameState.STAGE_CLEAR, stage=stage,
                                               has_boss_wave=True, next_stage_available=True))
            for text in ('Stage Clear', f'Stage {stage} encounter complete', 'Enter: Next Stage', 'R: Restart Run'):
                self.assertIn(text, labels)
        labels = self.labels(self.snapshot(GameState.STAGE_CLEAR, next_stage_available=False))
        self.assertIn('No next stage is available.', labels)
        self.assertNotIn('Enter: Next Stage', labels)

    def test_hp_defeat_uses_authoritative_reason_and_zero_health(self):
        labels = self.labels(self.snapshot(GameState.GAME_OVER, hp=0, game_over_reason=GameOverReason.HP_DEPLETED))
        self.assertIn('Player HP depleted', labels); self.assertIn('HP 0/100', labels)
        self.assertNotIn('Enter: Next Stage', labels)

    def test_defense_failure_is_not_misrepresented_as_hp_depletion(self):
        labels = self.labels(self.snapshot(GameState.GAME_OVER, hp=95, game_over_reason=GameOverReason.DEFENSE_FAILED))
        self.assertIn(GameOverReason.DEFENSE_FAILED.value, labels); self.assertIn('HP 95/100', labels)
        self.assertNotIn('Player HP depleted', labels)

    def test_no_reason_does_not_invent_a_gameplay_conclusion(self):
        labels = self.labels(self.snapshot(GameState.GAME_OVER, hp=0))
        self.assertIn('Run ended', labels); self.assertNotIn('Player HP depleted', labels)

    def test_victory_and_results_use_actual_final_resources(self):
        for state in (GameState.VICTORY, GameState.RESULTS):
            labels = self.labels(self.snapshot(state, stage=3, turn_index=22, hp=5, mp=20, bp=5))
            for text in ('Campaign complete', 'Stage 3 | Turn 22', 'HP 5/100', 'MP 20/100', 'BP 5/5', 'R: Restart Run'):
                self.assertIn(text, labels)
            self.assertEqual('Enter: Results' in labels, state is GameState.VICTORY)

    def test_results_score_is_unavailable_without_fabricated_statistics(self):
        labels = self.labels(self.snapshot(GameState.RESULTS, stage=3))
        self.assertIn('Score: —', labels)
        self.assertFalse(hasattr(self.world.snapshot(), 'score'))
        self.assertFalse(any('High score' in t or 'Bonus' in t or 'Kills' in t for t in labels))

    def test_pause_covers_center_but_preserves_hud_and_visible_field_edges(self):
        self.world.start_new_run(); self.world.transition_to(GameState.PLAYER_AIM)
        self.renderer.draw(self.screen, self.world.snapshot())
        before = self.screen.copy(); self.world.pause()
        labels = self.labels(self.world.snapshot())
        self.assertIn('Paused', labels); self.assertIn('Escape: Resume', labels)
        self.assertEqual(self.screen.get_at((26, 44)), before.get_at((26, 44)))
        self.assertNotEqual(self.screen.get_at((100, 90)), before.get_at((100, 90)))
        self.assertNotEqual(self.screen.get_at((100, 90))[:3], (0, 0, 0))

    def test_pause_identifies_each_frozen_phase(self):
        for phase, text in ((GameState.PLAYER_AIM, 'Aiming is paused.'),
                            (GameState.SHOT_ANIMATION, 'Your volley is frozen.'),
                            (GameState.SPELL_ANIMATION, 'Your spell is frozen.'),
                            (GameState.TURN_RESOLVE, 'Turn resolution is paused.')):
            self.assertIn(text, self.labels(self.snapshot(GameState.PAUSED, paused_state=phase)))

    def test_all_screens_and_pages_draw_without_mutating_world(self):
        self.world.apply_status(StatusKind.DOOM); self.world.place_poison_tile(3)
        before = deepcopy(vars(self.world))
        for state in GameState:
            for page in (0, 1) if state is GameState.INSTRUCTIONS else (0,):
                snapshot = self.snapshot(state, instructions_page=page)
                for _ in range(3): self.renderer.draw(self.screen, snapshot)
                self.assertEqual(vars(self.world), before)

    def test_supported_text_fits_declared_width_and_canvas_without_overlap(self):
        scenes = [self.snapshot(state, hp=100, mp=100, bp=5, next_stage_available=True,
                                game_over_reason=GameOverReason.DEFENSE_FAILED) for state in GameState
                  if state not in ACTIVE_STATES]
        scenes += [self.snapshot(GameState.STAGE_INTRO, stage=stage, total_waves=stage+4,
                                 has_boss_wave=True) for stage in (1, 2, 3)]
        scenes += [self.snapshot(GameState.INSTRUCTIONS, instructions_page=1)]
        original = self.renderer.screens._text
        for snapshot in scenes:
            records = []
            def record(screen, text, position, **kwargs):
                font = self.renderer.screens.fonts[kwargs.get('font', 'body')]
                width, height = font.size(text)
                self.assertLessEqual(width, kwargs['width'], text)
                x, y = position
                if kwargs.get('centered'): x += (kwargs['width'] - width) // 2
                rect = pygame.Rect(x, y, width, height)
                self.assertTrue(pygame.Rect(0, 0, *LOGICAL_SIZE).contains(rect), (text, rect))
                records.append((text, rect))
                return original(screen, text, position, **kwargs)
            with patch.object(self.renderer.screens, '_text', side_effect=record):
                self.renderer.draw(self.screen, snapshot)
            for index, (label, rect) in enumerate(records):
                for other_label, other_rect in records[index+1:]:
                    self.assertFalse(rect.colliderect(other_rect), (snapshot.state, label, other_label))
                if snapshot.state is GameState.INSTRUCTIONS and rect.top >= 150 and rect.top < 512:
                    self.assertTrue(any(pygame.Rect(bounds).contains(rect) for bounds in INSTRUCTION_BOUNDS), label)

    def test_long_paragraph_wraps_without_changing_font_size(self):
        view = self.renderer.screens
        text = 'This longer screen message must wrap at word boundaries while staying readable.'
        lines = view._wrap(text, 240)
        self.assertGreater(len(lines), 1); self.assertEqual(' '.join(lines), text)
        self.assertTrue(all(view.fonts['body'].size(line)[0] <= 240 for line in lines))

    def test_fonts_backdrop_and_shade_are_reused_without_reconstruction(self):
        view = self.renderer.screens; background = view._backdrop; shade = view._shade
        with patch('src.screens.pygame.font.Font', side_effect=AssertionError('Per-frame font creation')):
            for _ in range(4): self.renderer.draw(self.screen, self.world.snapshot())
        self.assertIs(view._backdrop, background); self.assertIs(view._shade, shade)
        first = dict(view._text_cache); self.renderer.draw(self.screen, self.world.snapshot())
        self.assertEqual(dict(view._text_cache), first)

    def test_surface_cache_is_bounded_with_changing_terminal_values(self):
        view = self.renderer.screens
        for turn in range(1, SCREEN_CACHE_LIMIT + 20):
            self.renderer.draw(self.screen, self.snapshot(GameState.RESULTS, turn_index=turn))
            self.assertLessEqual(len(view._text_cache), SCREEN_CACHE_LIMIT)

    def test_assets_decode_once_and_no_screen_requires_audio(self):
        with patch('src.assets.pygame.image.load', side_effect=AssertionError('Repeated disk read')), \
             patch('src.assets.pygame.mixer.init', side_effect=AssertionError('Audio device')):
            for _ in range(4): self.renderer.draw(self.screen, self.world.snapshot())
        self.assertFalse(pygame.mixer.get_init())

    def test_missing_and_corrupt_guardian_use_procedural_screen_fallback(self):
        for corrupt in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if corrupt:
                    path = root/'images/player/guardian.png'; path.parent.mkdir(parents=True)
                    path.write_bytes(b'not an image')
                with self.assertLogs('src.assets', level='WARNING'):
                    renderer = Renderer(AssetManager(root))
                before = deepcopy(vars(self.world))
                with patch('src.assets.pygame.image.load', side_effect=AssertionError('Repeated disk read')):
                    for state in (GameState.MENU, GameState.INSTRUCTIONS, GameState.STAGE_INTRO, *TERMINALS):
                        renderer.draw(self.screen, self.snapshot(state))
                self.assertEqual(vars(self.world), before)
                self.assertFalse(pygame.mixer.get_init())

    def test_terminal_screens_write_no_score_or_save_files(self):
        with tempfile.TemporaryDirectory() as directory:
            before = Path.cwd()
            try:
                os.chdir(directory)
                for state in TERMINALS: self.renderer.draw(self.screen, self.snapshot(state))
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally: os.chdir(before)


class ScreenCampaignTests(unittest.TestCase):
    def test_help_intros_pause_terminals_and_real_campaign_are_frame_schedule_invariant(self):
        pygame.display.init(); pygame.font.init(); self.addCleanup(pygame.quit)
        screen = pygame.display.set_mode(LOGICAL_SIZE); renderer = Renderer(); reference = None
        routes = (tuple(('shot', r) for r in OPENING_ROWS + (2, 5)), STAGE_TWO_CLEAR, METEOR_CLEAR)
        for schedule in ((1/30,), (1/60,), (1/144,), (.007, .041, .013, .09)):
            game = Game(); game.running = True; world = game.world; history = []
            def key(value):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value))
                for event in pygame.event.get(): game.handle_event(event)
            before = deepcopy(vars(world)); renderer.draw(screen, world.snapshot())
            key(pygame.K_i)
            for value in (pygame.K_RIGHT, pygame.K_LEFT, pygame.K_RIGHT):
                key(value); renderer.draw(screen, world.snapshot()); world.advance_time(1000)
            key(pygame.K_BACKSPACE); self.assertEqual(vars(world), before)
            key(pygame.K_RETURN)
            for stage, route in enumerate(routes, 1):
                intro = deepcopy(vars(world)); renderer.draw(screen, world.snapshot())
                self.assertEqual(vars(world), intro); self.assertFalse(world.enemies)
                self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp), (stage, 1, 100, 100, 1))
                key(pygame.K_RETURN)
                aimed = world.snapshot(); key(pygame.K_ESCAPE)
                paused = deepcopy(vars(world)); renderer.draw(screen, world.snapshot()); world.advance_time(1000)
                self.assertEqual(vars(world), paused); key(pygame.K_ESCAPE); self.assertEqual(world.snapshot(), aimed)
                for kind, row in route:
                    perform_action(world, kind, row, schedule, game=game)
                    snapshot = world.snapshot(); data = deepcopy(vars(world))
                    renderer.draw(screen, snapshot); self.assertEqual(vars(world), data)
                    history.append((snapshot, tuple(world.combat.death_events), tuple(world.encounter.spawn_history)))
                self.assertIs(world.state, GameState.VICTORY if stage == 3 else GameState.STAGE_CLEAR)
                if stage < 3: key(pygame.K_RETURN)
            key(pygame.K_RETURN); self.assertIs(world.state, GameState.RESULTS)
            before = deepcopy(vars(world))
            for _ in range(4): renderer.draw(screen, world.snapshot()); self.assertFalse(world.resolve_turn())
            self.assertEqual(vars(world), before)
            self.assertEqual((world.stage, world.turn_index, world.hp, world.mp, world.bp), (3, 22, 5, 20, 5))
            if reference is None: reference = history
            self.assertEqual(history, reference, schedule)
            key(pygame.K_r); self.assertIs(world.state, GameState.STAGE_INTRO)
            self.assertEqual((world.stage, world.instructions_page), (1, 0))
