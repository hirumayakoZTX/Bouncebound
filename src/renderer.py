"""Procedural placeholder rendering without external artwork or audio."""

import pygame

from src.constants import BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE, WINDOW_TITLE
from src.states import ACTIVE_STATES, GameState
from src.world import WorldSnapshot
from src.entities import EnemyType


class Renderer:
    def __init__(self) -> None:
        self.title_font = pygame.font.Font(None, 48)
        self.body_font = pygame.font.Font(None, 28)

    def draw(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        screen.fill((21, 28, 44))
        if snapshot.state is GameState.MENU:
            self._center_text(screen, WINDOW_TITLE, 230, heading=True)
            self._center_text(screen, "Enter: Start", 310)
            self._center_text(screen, "Escape: Quit", 350)
        elif snapshot.state is GameState.STAGE_INTRO:
            self._center_text(screen, f"Stage {snapshot.stage}", 240, heading=True)
            self._center_text(screen, "Enter: Continue", 320)
        elif snapshot.state is GameState.GAME_OVER:
            self._center_text(screen, "Game Over", 220, heading=True)
            self._center_text(screen, f"Stage {snapshot.stage} | Turn {snapshot.turn_index}", 280)
            self._center_text(
                screen, f"HP {snapshot.hp}/{snapshot.max_hp} | "
                f"MP {snapshot.mp}/{snapshot.max_mp} | BP {snapshot.bp}", 320,
            )
            self._center_text(screen, "Close the window to exit", 380)
        elif snapshot.state in ACTIVE_STATES or snapshot.state is GameState.PAUSED:
            self._draw_battlefield(screen, snapshot)
            if snapshot.state is GameState.PAUSED:
                overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))
                self._center_text(screen, "Paused", 250, heading=True)
                self._center_text(screen, "Escape: Resume", 315)
        else:
            self._center_text(
                screen, snapshot.state.name.replace("_", " ").title(),
                screen.get_height() // 2, heading=True,
            )

    def _draw_battlefield(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        self._center_text(
            screen, f"Stage {snapshot.stage}    Turn {snapshot.turn_index}", 32
        )
        arena = pygame.Rect(BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE)
        pygame.draw.rect(screen, (30, 43, 63), arena)
        pygame.draw.rect(screen, (102, 139, 175), arena, width=2)
        self._center_text(screen, "Green: Slime | Red: Bomb | Blue: BP Crystal", 56)
        for enemy in snapshot.enemies:
            rect = pygame.Rect(enemy.bounds.left, enemy.bounds.top,
                               enemy.bounds.right - enemy.bounds.left,
                               enemy.bounds.bottom - enemy.bounds.top)
            color = (81, 158, 105) if enemy.enemy_type is EnemyType.BASIC else (190, 75, 79)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            prefix = "S" if enemy.enemy_type is EnemyType.BASIC else "B"
            label = self.body_font.render(f"{prefix}{enemy.hp}", True, (255, 255, 255))
            screen.blit(label, label.get_rect(center=rect.center))
        for crystal in snapshot.crystals:
            cx = (crystal.bounds.left + crystal.bounds.right) / 2
            cy = (crystal.bounds.top + crystal.bounds.bottom) / 2
            rx, ry = 14, 17
            if any((enemy.grid_col, enemy.grid_row) == (crystal.grid_col, crystal.grid_row)
                   for enemy in snapshot.enemies):
                cx, cy = crystal.bounds.right - 8, crystal.bounds.top + 8
                rx, ry = 5, 6
            pygame.draw.polygon(screen, (74, 172, 255),
                                ((cx, cy - ry), (cx + rx, cy),
                                 (cx, cy + ry), (cx - rx, cy)))
        if (snapshot.aim_target is not None
                and (snapshot.state is GameState.PLAYER_AIM
                     or (snapshot.state is GameState.PAUSED
                         and snapshot.paused_state is GameState.PLAYER_AIM))):
            pygame.draw.line(
                screen, (249, 211, 113), snapshot.aim_origin, snapshot.aim_target, width=1
            )
            pygame.draw.circle(screen, (249, 211, 113), snapshot.aim_target, 4, width=1)
        x, y = snapshot.player_position
        pygame.draw.circle(screen, (129, 209, 236), (x, y), 18)
        pygame.draw.polygon(
            screen, (235, 239, 250), ((x - 24, y), (x - 8, y - 10), (x - 8, y + 10))
        )
        for projectile in snapshot.projectiles:
            pygame.draw.circle(screen, (255, 225, 133), projectile.position, projectile.radius)
        if snapshot.state is GameState.PLAYER_AIM:
            feedback = (f"Enemy phase {snapshot.last_resolved_turn} complete | "
                        if snapshot.last_resolved_turn is not None else "")
            self._center_text(screen, feedback + "Waiting for input", 472)
        elif snapshot.state is GameState.SHOT_ANIMATION:
            self._center_text(screen, "Orb in flight", 472)
        elif snapshot.state is GameState.TURN_RESOLVE:
            self._center_text(screen, "Resolving enemy phase", 472)
        self._center_text(
            screen,
            f"HP {snapshot.hp}/{snapshot.max_hp}    "
            f"MP {snapshot.mp}/{snapshot.max_mp}    BP {snapshot.bp}"
            + (f" (+{snapshot.pending_bp} pending)" if snapshot.pending_bp else ""),
            500,
        )
        if snapshot.state is not GameState.PAUSED:
            self._center_text(screen, f"{snapshot.state.name} | Escape: Pause", 540)

    def _center_text(
        self, screen: pygame.Surface, text: str, y: int, *, heading: bool = False
    ) -> None:
        font = self.title_font if heading else self.body_font
        image = font.render(text, True, (235, 239, 250))
        screen.blit(image, image.get_rect(center=(screen.get_width() // 2, y)))
