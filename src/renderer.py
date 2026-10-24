"""Procedural placeholder rendering without external artwork or audio."""

import pygame

from src.constants import WINDOW_TITLE


class Renderer:
    def __init__(self) -> None:
        title_font = pygame.font.Font(None, 48)
        hint_font = pygame.font.Font(None, 26)
        self.title = title_font.render(WINDOW_TITLE, True, (235, 239, 250))
        self.hint = hint_font.render(
            "Project bootstrap | Press Escape to exit", True, (164, 177, 203)
        )

    def draw(self, screen: pygame.Surface) -> None:
        screen.fill((21, 28, 44))
        center_x, center_y = screen.get_rect().center
        screen.blit(self.title, self.title.get_rect(center=(center_x, center_y - 24)))
        screen.blit(self.hint, self.hint.get_rect(center=(center_x, center_y + 32)))
