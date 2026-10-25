"""Window lifecycle and scene-aware input dispatch."""

import pygame

from src.constants import LOGICAL_SIZE, TARGET_FPS, WINDOW_TITLE
from src.renderer import Renderer
from src.states import ACTIVE_STATES, GameState
from src.world import World
from src.spells import SpellId


SPELL_KEYS = dict(zip((pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                       pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8), SpellId))


class Game:
    def __init__(self) -> None:
        self.running = False
        self.world = World()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        if not self.running:
            return
        if event.type == pygame.MOUSEMOTION:
            self.world.set_aim_target(event.pos)
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if hasattr(event, "pos"):
                    self.world.set_aim_target(event.pos)
                self.world.fire()
            return
        if event.type != pygame.KEYDOWN:
            return

        # Navigation repeats must not skip help pages or toggle pause twice.
        if getattr(event, "repeat", False):
            return
        if self.world.state is GameState.INSTRUCTIONS:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.world.transition_to(GameState.MENU)
            elif event.key in (pygame.K_LEFT, pygame.K_PAGEUP):
                self.world.change_instructions_page(-1)
            elif event.key in (pygame.K_RIGHT, pygame.K_PAGEDOWN):
                self.world.change_instructions_page(1)
            return
        if event.key == pygame.K_i and self.world.state is GameState.MENU:
            self.world.transition_to(GameState.INSTRUCTIONS)
            return

        if event.key == pygame.K_RETURN and not getattr(event, "repeat", False):
            if self.world.state is GameState.MENU:
                self.world.start_new_run()
            elif self.world.state is GameState.STAGE_INTRO:
                self.world.transition_to(GameState.PLAYER_AIM)
            elif self.world.state is GameState.STAGE_CLEAR:
                self.world.advance_stage()
            elif self.world.state is GameState.VICTORY:
                self.world.transition_to(GameState.RESULTS)
        elif event.key == pygame.K_r and not getattr(event, "repeat", False):
            self.world.restart()
        elif event.key == pygame.K_ESCAPE:
            if self.world.state is GameState.MENU:
                self.running = False
            elif self.world.state is GameState.PAUSED:
                self.world.resume()
            elif self.world.state in ACTIVE_STATES:
                self.world.pause()
        elif not getattr(event, "repeat", False):
            if event.key in (pygame.K_w, pygame.K_UP):
                self.world.move_player(-1)
            elif event.key in (pygame.K_s, pygame.K_DOWN):
                self.world.move_player(1)
            elif event.key in SPELL_KEYS:
                self.world.select_spell(SPELL_KEYS[event.key])
            elif event.key == pygame.K_SPACE:
                self.world.cast_selected_spell()

    def run(self) -> None:
        try:
            # Only initialize required subsystems; bootstrap needs no audio device.
            pygame.display.init()
            pygame.font.init()
            screen = pygame.display.set_mode(LOGICAL_SIZE)
            pygame.display.set_caption(WINDOW_TITLE)
            renderer = Renderer()
            clock = pygame.time.Clock()
            self.world.reset()
            self.running = True
            elapsed = 0.0

            while self.running:
                previous_state = self.world.state
                for event in pygame.event.get():
                    self.handle_event(event)
                    if not self.running:
                        break
                if not self.running:
                    break
                # New or resumed animations must not consume the prior frame's elapsed time.
                if (previous_state is self.world.state
                        and self.world.state in (GameState.SHOT_ANIMATION, GameState.SPELL_ANIMATION)):
                    self.world.advance_time(elapsed)
                elif self.world.state is GameState.TURN_RESOLVE:
                    self.world.resolve_turn()
                renderer.draw(screen, self.world.snapshot())
                pygame.display.flip()
                elapsed = clock.tick(TARGET_FPS) / 1000.0
        finally:
            self.running = False
            pygame.quit()
