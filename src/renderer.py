"""Procedural placeholder rendering without external artwork or audio."""

import pygame

from src.constants import BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE, WINDOW_TITLE
from src.states import ACTIVE_STATES, GameState
from src.world import WorldSnapshot
from src.entities import EnemyType
from src.player_actions import SPELL_ANIMATION_SECONDS, spell_failure_message
from src.spells import get_spell


class Renderer:
    def __init__(self) -> None:
        self.title_font = pygame.font.Font(None, 48)
        self.body_font = pygame.font.Font(None, 28)
        self.hud_font = pygame.font.Font(None, 22)

    def draw(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        screen.fill((21, 28, 44))
        if snapshot.state is GameState.MENU:
            self._center_text(screen, WINDOW_TITLE, 230, heading=True)
            self._center_text(screen, "Enter: Start", 310)
            self._center_text(screen, "Escape: Quit", 350)
        elif snapshot.state is GameState.STAGE_INTRO:
            self._center_text(screen, f"Stage {snapshot.stage}", 240, heading=True)
            if snapshot.total_waves:
                self._center_text(screen, (f"Stage {snapshot.stage}: {snapshot.total_waves} waves + "
                                           + {1: "Ultros and Typhon", 2: "Chichu", 3: "Odin"}[snapshot.stage]
                                           if snapshot.has_boss_wave else
                                           f"Prototype: {snapshot.total_waves} scripted waves"), 285)
            self._center_text(screen, "Enter: Continue", 320)
        elif snapshot.state in (GameState.GAME_OVER, GameState.STAGE_CLEAR):
            cleared = snapshot.state is GameState.STAGE_CLEAR
            self._center_text(screen, "Stage Clear" if cleared else "Game Over", 190, heading=True)
            reason = ((f"Stage {snapshot.stage} encounter complete" if snapshot.has_boss_wave
                       else "Prototype encounter complete") if cleared
                      else snapshot.game_over_reason.value if snapshot.game_over_reason
                      else "Player HP depleted" if snapshot.hp <= 0 else "Run ended")
            self._center_text(screen, reason, 240)
            self._center_text(screen, f"Stage {snapshot.stage} | Turn {snapshot.turn_index}", 280)
            self._center_text(
                screen, f"HP {snapshot.hp}/{snapshot.max_hp} | "
                f"MP {snapshot.mp}/{snapshot.max_mp} | BP {snapshot.bp}", 320,
            )
            self._center_text(screen, "Press R to Restart", 380)
            if snapshot.next_stage_available:
                self._center_text(screen, "Enter: Next stage", 420)
        elif snapshot.state in (GameState.VICTORY, GameState.RESULTS):
            self._center_text(screen, "Victory" if snapshot.state is GameState.VICTORY
                              else "Results", 190, heading=True)
            self._center_text(screen, "Campaign complete", 240)
            self._center_text(screen, f"Stage {snapshot.stage} | Turn {snapshot.turn_index}", 280)
            self._center_text(screen, f"HP {snapshot.hp}/{snapshot.max_hp} | "
                              f"MP {snapshot.mp}/{snapshot.max_mp} | BP {snapshot.bp}", 320)
            if snapshot.state is GameState.VICTORY:
                self._center_text(screen, "Enter: Results", 380)
            self._center_text(screen, "Press R to Restart", 420)
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
            screen, f"Stage {snapshot.stage}    Turn {snapshot.turn_index}"
            + (f"    Waves {snapshot.spawned_waves}/{snapshot.total_waves}"
               if snapshot.total_waves else "")
            + ((f"    Bosses {snapshot.bosses_remaining}/{snapshot.boss_total}" if snapshot.boss_wave_spawned
                else "    Bosses pending") if snapshot.has_boss_wave else ""), 32
        )
        arena = pygame.Rect(BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE)
        pygame.draw.rect(screen, (30, 43, 63), arena)
        pygame.draw.rect(screen, (102, 139, 175), arena, width=2)
        statuses = " | ".join(
            effect.kind.name + (f" {effect.remaining_turns}" if effect.remaining_turns is not None
                                else " (1 revival)")
            for effect in snapshot.statuses
        )
        self._hud_text(screen, "Status: " + statuses if statuses else
                       ("C: Cactuar | A: Alligator | Bu: Bulb | M: Morbol | L: Landtrap | Ch: Chichu"
                        if snapshot.stage == 2 else
                        "Mn: Mandragora | D: Diremite | To: Tonberry (! Enraged) | G: Gorgon | O: Odin"
                        if snapshot.stage == 3 else
                        "Green: Slime | Red: Bomb | Purple: Ultros | Gold: Typhon | Blue: BP"), 56)
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
            pygame.draw.rect(screen, color, rect, border_radius=6)
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
        elif (snapshot.state is GameState.SPELL_ANIMATION
              or (snapshot.state is GameState.PAUSED
                  and snapshot.paused_state is GameState.SPELL_ANIMATION)):
            result = snapshot.spell_result
            if result is not None:
                name = get_spell(result.cast.spell_id).name
                progress = 1.0 - snapshot.spell_remaining / SPELL_ANIMATION_SECONDS
                pygame.draw.circle(screen, (201, 158, 255), snapshot.player_position,
                                   24 + int(12 * progress), width=2)
                self._center_text(screen, f"{name} | Spell effect", 472)
        elif snapshot.state is GameState.TURN_RESOLVE:
            self._center_text(screen, "Resolving enemy phase", 472)
        self._center_text(
            screen,
            f"HP {snapshot.hp}/{snapshot.max_hp}    "
            f"MP {snapshot.mp}/{snapshot.max_mp}    BP {snapshot.bp}"
            + (f" (+{snapshot.pending_bp} pending)" if snapshot.pending_bp else ""),
            495,
        )
        hud = snapshot.spell_hud
        if hud is None:
            selection = "Spell: None | Select with 1-8"
        else:
            readiness = "Ready" if hud.ready else spell_failure_message(hud.failure)
            selection = (f"{hud.definition.name} | MP {hud.definition.mp_cost} | "
                         f"Ready turn {hud.next_ready_turn} | {readiness}")
        self._hud_text(screen, selection, 518)
        self._hud_text(screen, snapshot.spell_feedback or snapshot.state.name, 540)
        self._hud_text(screen, "1 Fire  2 Starstorm  3 Meteor  4 Cure  5 Esuna  6 Levitation  7 Ward  8 Reraise"
                       "  | Space: Cast | Click: Shoot | Esc: Pause", 563)

    def _hud_text(self, screen: pygame.Surface, text: str, y: int) -> None:
        image = self.hud_font.render(text, True, (235, 239, 250))
        if image.get_width() > screen.get_width() - 24:
            # Fit long status/control lists into their HUD row without covering the arena.
            image = pygame.transform.smoothscale(
                image, (screen.get_width() - 24, image.get_height()))
        screen.blit(image, image.get_rect(center=(screen.get_width() // 2, y)))

    def _center_text(
        self, screen: pygame.Surface, text: str, y: int, *, heading: bool = False
    ) -> None:
        font = self.title_font if heading else self.body_font
        image = font.render(text, True, (235, 239, 250))
        screen.blit(image, image.get_rect(center=(screen.get_width() // 2, y)))
