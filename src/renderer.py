"""Snapshot-only battlefield, combat HUD, and screen coordination."""

from dataclasses import dataclass

import pygame

from src.assets import AssetManager

from src.constants import BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE
from src.states import ACTIVE_STATES, GameState
from src.world import WorldSnapshot
from src.entities import EnemyType
from src.player_actions import SPELL_ANIMATION_SECONDS
from src.hud import CombatHUD
from src.screens import ScreenRenderer


@dataclass(frozen=True)
class SpriteSpec:
    path: str
    native_size: tuple[int, int] = (16, 16)
    scale: int = 3


PLAYER_SPRITE = SpriteSpec("images/player/guardian.png")
ENEMY_SPRITES = {
    EnemyType.BASIC: SpriteSpec("images/enemies/slime.png"),
    EnemyType.BOMB: SpriteSpec("images/enemies/bomb.png"),
}
CRYSTAL_SPRITE = SpriteSpec("images/ui/bp_crystal.png", scale=2)
ORB_SPRITE = SpriteSpec("images/projectiles/orb.png", scale=1)


class Renderer:
    def __init__(self, assets: AssetManager | None = None) -> None:
        self.assets = assets if assets is not None else AssetManager()
        # Decode known resources once before the first frame. Unknown enemy art
        # continues to use procedural shapes without probing absent files.
        for spec in (PLAYER_SPRITE, *ENEMY_SPRITES.values(), CRYSTAL_SPRITE, ORB_SPRITE):
            self.assets.load_image(spec.path, native_size=spec.native_size, scale=spec.scale)
        self.body_font = pygame.font.Font(None, 28)
        self.hud_font = pygame.font.Font(None, 22)
        self.hud = CombatHUD()
        self.screens = ScreenRenderer()

    def draw(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        screen.fill((21, 28, 44))
        if snapshot.state in ACTIVE_STATES or snapshot.state is GameState.PAUSED:
            self._draw_battlefield(screen, snapshot)
            if snapshot.state is GameState.PAUSED:
                self.screens.draw(screen, snapshot, self.assets)
            self.hud.draw(screen, snapshot)
        else:
            self.screens.draw(screen, snapshot, self.assets)

    def _draw_battlefield(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        arena = pygame.Rect(BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE)
        pygame.draw.rect(screen, (30, 43, 63), arena)
        pygame.draw.rect(screen, (102, 139, 175), arena, width=2)
        for tile in snapshot.hazards:
            # PoisonTiles affect the player lane, never projectile collision geometry.
            row_rect = pygame.Rect(snapshot.player_position[0] - 24,
                                   BATTLEFIELD_ORIGIN[1] + 48 * tile.row, 48, 48)
            pygame.draw.rect(screen, (125, 68, 146), row_rect, width=3)
            label = self.hud_font.render(str(tile.remaining_turns), True, (221, 158, 242))
            screen.blit(label, row_rect.topleft)
        for enemy in snapshot.enemies:
            rect = pygame.Rect(enemy.bounds.left, enemy.bounds.top,
                               enemy.bounds.right - enemy.bounds.left,
                               enemy.bounds.bottom - enemy.bounds.top)
            color, prefix = {
                EnemyType.BASIC: ((81, 158, 105), "S"),
                EnemyType.BOMB: ((190, 75, 79), "B"),
                EnemyType.ULTROS: ((148, 100, 204), "U"),
                EnemyType.TYPHON: ((205, 151, 59), "T"),
                EnemyType.CACTUAR: ((30, 125, 90), "C"),
                EnemyType.ALLIGATOR: ((89, 113, 54), "A"),
                EnemyType.BULB: ((159, 85, 143), "Bu"),
                EnemyType.MORBOL: ((84, 85, 157), "M"),
                EnemyType.LANDTRAP: ((147, 91, 48), "L"),
                EnemyType.CHICHU: ((188, 86, 27), "Ch"),
                EnemyType.MANDRAGORA: ((111, 119, 45), "Mn"),
                EnemyType.DIREMITE: ((65, 98, 159), "D"),
                EnemyType.TONBERRY: ((27, 110, 97), "T!" if enemy.enraged else "To"),
                EnemyType.GORGON: ((132, 67, 152), "G"),
                EnemyType.ODIN: ((108, 116, 130), "O"),
            }[enemy.enemy_type]
            spec = ENEMY_SPRITES.get(enemy.enemy_type)
            if spec is not None and self._draw_sprite(screen, spec, rect.center) is not None:
                # Retain identity and HP in a small plate below the sprite's face.
                label = self.hud_font.render(f"{prefix}{enemy.hp}", True, (255, 255, 255))
                label_rect = label.get_rect(bottomright=(rect.right - 1, rect.bottom - 1))
                pygame.draw.rect(screen, (21, 28, 44), label_rect)
                screen.blit(label, label_rect)
            else:
                pygame.draw.rect(screen, color, rect, border_radius=6)
                label = self.body_font.render(f"{prefix}{enemy.hp}", True, (255, 255, 255))
                screen.blit(label, label.get_rect(center=rect.center))
        for crystal in snapshot.crystals:
            cx = (crystal.bounds.left + crystal.bounds.right) / 2
            cy = (crystal.bounds.top + crystal.bounds.bottom) / 2
            rx, ry = 14, 17
            occupied = any((enemy.grid_col, enemy.grid_row) == (crystal.grid_col, crystal.grid_row)
                           for enemy in snapshot.enemies)
            if occupied:
                cx, cy = crystal.bounds.right - 8, crystal.bounds.top + 8
                rx, ry = 5, 6
            if self._draw_sprite(screen, CRYSTAL_SPRITE, (cx, cy),
                                 scale=1 if occupied else 2) is None:
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
        if self._draw_sprite(screen, PLAYER_SPRITE, (x, y)) is None:
            pygame.draw.circle(screen, (129, 209, 236), (x, y), 18)
            pygame.draw.polygon(
                screen, (235, 239, 250), ((x - 24, y), (x - 8, y - 10), (x - 8, y + 10))
            )
        for projectile in snapshot.projectiles:
            if self._draw_sprite(screen, ORB_SPRITE, projectile.position) is None:
                pygame.draw.circle(screen, (255, 225, 133), projectile.position, projectile.radius)
        if (snapshot.state is GameState.SPELL_ANIMATION
                or (snapshot.state is GameState.PAUSED
                    and snapshot.paused_state is GameState.SPELL_ANIMATION)):
            if snapshot.spell_result is not None:
                progress = 1.0 - snapshot.spell_remaining / SPELL_ANIMATION_SECONDS
                pygame.draw.circle(screen, (201, 158, 255), snapshot.player_position,
                                   24 + int(12 * progress), width=2)

    def _draw_sprite(self, screen: pygame.Surface, spec: SpriteSpec,
                     center: tuple[float, float], *, scale: int | None = None) -> pygame.Rect | None:
        image = self.assets.load_image(spec.path, native_size=spec.native_size,
                                       scale=spec.scale if scale is None else scale)
        if image.is_fallback:
            return None
        rect = image.surface.get_rect(center=center)
        screen.blit(image.surface, rect)
        return rect
