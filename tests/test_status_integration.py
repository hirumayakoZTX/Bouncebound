"""Real application/World resolution with fixture statuses and no spell hotkeys."""
from copy import deepcopy
from itertools import cycle
import os
import unittest
from unittest.mock import Mock, patch
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame
from src.constants import LOGICAL_SIZE
from src.game import Game
from src.hazards import HazardState
from src.renderer import Renderer
from src.states import GameState
from src.statuses import StatusKind as Kind, StatusState
from src.world import World
from test_status_runtime import finish_turn, world

class StatusIntegrationTests(unittest.TestCase):

    def tearDown(self):
        pygame.quit()

    def test_application_pause_in_flight_and_pending_phase_preserves_exact_timers(self):
        game = Game()
        game.world = World(demo=False)
        clock = Mock()
        clock.tick.return_value = 250
        original_draw = Renderer.draw
        configured = False
        fired = set()
        pauses = set()
        held = None
        held_frames = 0
        frames = 0
        moved = False

        def key(value):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=value))

        def drive(renderer, screen, snapshot):
            nonlocal configured, held, held_frames, frames, moved
            frames += 1
            self.assertLess(frames, 150)
            original_draw(renderer, screen, snapshot)
            if snapshot.state is GameState.MENU:
                key(pygame.K_RETURN)
            elif snapshot.state is GameState.STAGE_INTRO:
                key(pygame.K_RETURN)
            elif snapshot.state is GameState.PLAYER_AIM:
                if not configured:
                    game.world.apply_status(Kind.POISON, 2)
                    game.world.apply_status(Kind.BIND, 1)
                    game.world.apply_status(Kind.DOOM, 3)
                    game.world.place_poison_tile(3)
                    configured = True
                if snapshot.turn_index == 3:
                    self.assertEqual(snapshot.hp, 92)
                    self.assertEqual(game.world.statuses.get(Kind.DOOM).remaining_turns, 2)
                    self.assertEqual(game.world.statuses.get(Kind.POISON).remaining_turns, 1)
                    self.assertIsNone(game.world.statuses.get(Kind.BIND))
                    self.assertEqual(snapshot.hazards[0].remaining_turns, 1)
                    if not moved:
                        moved = True
                        key(pygame.K_UP)
                    else:
                        self.assertEqual(snapshot.player_row, 2)
                        pygame.event.post(pygame.event.Event(pygame.QUIT))
                    return
                if snapshot.turn_index not in fired:
                    # Both first input intervals are bound.
                    key(pygame.K_UP)
                    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=(96, 240)))
                    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(96, 240)))
                    fired.add(snapshot.turn_index)
            elif snapshot.state is GameState.SHOT_ANIMATION and snapshot.turn_index == 1 and ('flight' not in pauses):
                pauses.add('flight')
                key(pygame.K_ESCAPE)
            elif snapshot.state is GameState.TURN_RESOLVE and snapshot.turn_index == 2 and ('pending' not in pauses):
                pauses.add('pending')
                key(pygame.K_ESCAPE)
            elif snapshot.state is GameState.PAUSED:
                if held is None:
                    held = snapshot
                    held_frames = 0
                self.assertEqual(snapshot, held)
                held_frames += 1
                if held_frames == 3:
                    held = None
                    key(pygame.K_ESCAPE)
        with patch('src.game.pygame.time.Clock', return_value=clock), patch.object(Renderer, 'draw', autospec=True, side_effect=drive):
            game.run()
        self.assertEqual(pauses, {'flight', 'pending'})
        self.assertEqual(game.world.turn_index, 3)
        self.assertFalse(game.running)
        self.assertFalse(pygame.display.get_init())

    def test_rendering_and_hotkeys_never_tick_statuses_or_hazards(self):
        game = Game()
        game.world = world()
        game.running = True
        owner = game.world
        for kind in (Kind.POISON, Kind.BIND, Kind.DOOM, Kind.WARD, Kind.LEVITATION):
            owner.apply_status(kind)
        owner.place_poison_tile(3)
        pygame.display.init()
        pygame.font.init()
        screen = pygame.display.set_mode(LOGICAL_SIZE)
        renderer = Renderer()
        before = deepcopy(vars(owner))
        for _ in range(20):
            renderer.draw(screen, owner.snapshot())
        for value in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_SPACE):
            game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=value))
        self.assertEqual(vars(owner), before)
        for value in (pygame.K_w, pygame.K_s, pygame.K_UP, pygame.K_DOWN):
            game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=value))
        self.assertEqual(vars(owner), before)
        self.assertFalse(owner.fire())
        self.assertFalse(owner.resolve_turn())
        self.assertEqual(vars(owner), before)

    def test_full_physics_frame_schedules_produce_identical_status_and_hazard_results(self):
        results = []
        for schedule in ([1 / 30], [1 / 60], [1 / 144], [0.005, 0.047, 0.003, 0.011, 0.02, 0.014]):
            owner = world()
            owner.apply_status(Kind.POISON, 3)
            owner.place_poison_tile(3)
            for _ in range(4):
                owner.set_aim_target((96, 240))
                owner.fire()
                for index, dt in enumerate(cycle(schedule)):
                    owner.advance_time(dt)
                    if owner.state is GameState.TURN_RESOLVE:
                        break
                    self.assertLess(index, 2000)
                self.assertTrue(owner.resolve_turn())
            self.assertEqual((owner.hp, owner.turn_index), (81, 5))
            results.append(owner.snapshot())
        self.assertTrue(all((snapshot == results[0] for snapshot in results)))

    def test_repeated_restart_clears_status_events_phase_guards_hazards_and_cast_history(self):
        owner = world()
        for _ in range(3):
            owner.execute_support_spell('revive', 'reraise')
            owner.apply_status(Kind.POISON, 3)
            owner.apply_status(Kind.DOOM, 5)
            owner.place_poison_tile(3)
            finish_turn(owner)
            owner.force_player_knockout()
            owner.force_player_knockout()
            self.assertIs(owner.state, GameState.GAME_OVER)
            self.assertTrue(owner.restart())
            self.assertEqual(owner.statuses, StatusState())
            self.assertEqual(owner.hazards, HazardState())
            self.assertEqual(owner.status_events, ())
            self.assertFalse(owner.reraise_used)
            self.assertEqual(dict(owner.spells.cooldowns), {})
            self.assertEqual((owner.hp, owner.mp, owner.bp, owner.turn_index), (100, 100, 1, 1))
            owner.transition_to(GameState.PLAYER_AIM)

    def test_pause_resume_and_invalid_inputs_never_shorten_bound_or_countdowns(self):
        owner = world()
        owner.apply_status(Kind.BIND, 1)
        owner.apply_status(Kind.DOOM, 2)
        owner.place_poison_tile(3)
        before = owner.snapshot()
        owner.pause()
        held = deepcopy(vars(owner))
        for _ in range(20):
            owner.advance_time(10000)
            self.assertFalse(owner.resolve_turn())
            self.assertFalse(owner.move_player(-1))
        self.assertEqual(vars(owner), held)
        owner.resume()
        self.assertEqual(owner.snapshot(), before)
        self.assertEqual((owner.turn_index, owner.mp, owner.bp), (1, 100, 1))
if __name__ == '__main__':
    unittest.main()
