"""Window lifecycle and event dispatch for the bootstrap application."""

import pygame

from src.constants import LOGICAL_SIZE, TARGET_FPS, WINDOW_TITLE
from src.renderer import Renderer


class Game:
    def __init__(self) -> None:
        self.running = False

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.running = False

    def run(self) -> None:
        try:
            # Only initialize required subsystems; bootstrap needs no audio device.
            pygame.display.init()
            pygame.font.init()
            screen = pygame.display.set_mode(LOGICAL_SIZE)
            pygame.display.set_caption(WINDOW_TITLE)
            renderer = Renderer()
            clock = pygame.time.Clock()
            self.running = True

            while self.running:
                for event in pygame.event.get():
                    self.handle_event(event)
                if not self.running:
                    break
                renderer.draw(screen)
                pygame.display.flip()
                clock.tick(TARGET_FPS)
        finally:
            self.running = False
            pygame.quit()
