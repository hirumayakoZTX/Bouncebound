"""Read-only combat presentation. No input, validation, timing, or gameplay effects."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

import pygame

from src.constants import MAX_BP
from src.player_actions import spell_failure_message
from src.spells import SPELLS, SpellId
from src.states import GameState
from src.statuses import StatusKind

if TYPE_CHECKING:
    from src.world import WorldSnapshot


# All panels are outside the fixed battlefield (96, 72, 672, 384).
HP_PANEL = (16, 8, 212, 56)
MP_PANEL = (236, 8, 212, 56)
BP_PANEL = (456, 8, 200, 56)
PROGRESS_PANEL = (664, 8, 280, 56)
STATUS_PANEL = (16, 464, 928, 24)
SPELL_PANEL = (16, 492, 352, 76)
FEEDBACK_PANEL = (376, 492, 292, 76)
SHORTCUT_PANEL = (676, 492, 268, 76)
PANELS = (HP_PANEL, MP_PANEL, BP_PANEL, PROGRESS_PANEL, STATUS_PANEL,
          SPELL_PANEL, FEEDBACK_PANEL, SHORTCUT_PANEL)

BACKGROUND = (22, 33, 51)
BORDER = (79, 108, 137)
TEXT = (237, 243, 251)
MUTED = (175, 193, 211)
HP_COLOR = (105, 215, 143)
MP_COLOR = (113, 174, 255)
BP_COLOR = (107, 211, 243)
ACCENT = (252, 214, 129)
HARMFUL = (255, 172, 155)
BENEFICIAL = (151, 232, 199)
TEXT_CACHE_LIMIT = 128

STATUS_NAMES = {
    StatusKind.POISON: 'Poison', StatusKind.BIND: 'Bind', StatusKind.DOOM: 'DOOM',
    StatusKind.WARD: 'Ward', StatusKind.LEVITATION: 'Levitation', StatusKind.RERAISE: 'Reraise',
}
STATUS_WIDTHS = {
    StatusKind.POISON: 96, StatusKind.BIND: 80, StatusKind.DOOM: 96,
    StatusKind.WARD: 88, StatusKind.LEVITATION: 112, StatusKind.RERAISE: 132,
}


def spell_availability(snapshot: WorldSnapshot) -> str:
    """Describe the model's selected-spell result, with explicit scene restrictions."""
    if snapshot.state is GameState.PAUSED:
        return 'Paused - actions unavailable'
    if snapshot.state is not GameState.PLAYER_AIM:
        return 'Main action unavailable'
    if snapshot.spell_hud is None:
        return 'Select an unlocked spell'
    if snapshot.spell_hud.failure is not None:
        return spell_failure_message(snapshot.spell_hud.failure)
    return 'Ready - Space to cast'


def cooldown_label(snapshot: WorldSnapshot) -> str:
    if snapshot.spell_hud is None:
        return 'Selection is free; one shot OR spell per turn'
    ready = snapshot.spell_hud.next_ready_turn
    remaining = max(0, ready - snapshot.turn_index)
    if remaining:
        unit = 'turn' if remaining == 1 else 'turns'
        return f'Ready T{ready} - {remaining} {unit} remaining'
    return 'Cooldown clear'


def status_labels(snapshot: WorldSnapshot) -> tuple[tuple[StatusKind, str, bool], ...]:
    result = []
    for effect in snapshot.statuses:
        if effect.applied_turn > snapshot.turn_index:
            continue
        duration = ('1-use' if effect.kind is StatusKind.RERAISE else
                    f'{effect.remaining_turns}t' if effect.remaining_turns is not None else 'active')
        prefix = '+' if effect.beneficial else '!'
        result.append((effect.kind, f'{prefix} {STATUS_NAMES[effect.kind]} {duration}', effect.beneficial))
    return tuple(result)


def hazard_label(snapshot: WorldSnapshot) -> str:
    if not snapshot.hazards:
        return 'Tiles: none'
    here = next((tile for tile in snapshot.hazards if tile.row == snapshot.player_row), None)
    label = f'Tiles {len(snapshot.hazards)}'
    if here is not None:
        label += f' | Here {here.remaining_turns}t'
        floating = any(effect.kind is StatusKind.LEVITATION and effect.applied_turn <= snapshot.turn_index
                       for effect in snapshot.statuses)
        if floating:
            label += ' / protected'
        elif here.applied_turn == snapshot.turn_index:
            label += ' / new'
    return label


class CombatHUD:
    """Fixed combat panels, three persistent fonts, and a bounded text-surface cache."""

    def __init__(self) -> None:
        self.fonts = {name: pygame.font.Font(None, size)
                      for name, size in (('heading', 24), ('body', 21), ('small', 19))}
        self._text_cache: OrderedDict[tuple, pygame.Surface] = OrderedDict()

    def _fit(self, text: str, font: str, width: int) -> str:
        if self.fonts[font].size(text)[0] <= width:
            return text
        while text and self.fonts[font].size(text + '...')[0] > width:
            text = text[:-1]
        return text + '...' if text else ''

    def _text(self, screen: pygame.Surface, text: str, pos: tuple[int, int], *,
              width: int, font: str = 'body', color: tuple[int, int, int] = TEXT) -> pygame.Rect:
        text = self._fit(text, font, width)
        key = (font, text, color)
        surface = self._text_cache.get(key)
        if surface is None:
            surface = self.fonts[font].render(text, True, color)
            self._text_cache[key] = surface
            if len(self._text_cache) > TEXT_CACHE_LIMIT:
                self._text_cache.popitem(last=False)
        else:
            self._text_cache.move_to_end(key)
        return screen.blit(surface, pos)

    @staticmethod
    def _panel(screen: pygame.Surface, bounds: tuple[int, int, int, int]) -> pygame.Rect:
        rect = pygame.Rect(bounds)
        pygame.draw.rect(screen, BACKGROUND, rect)
        pygame.draw.rect(screen, BORDER, rect, width=1)
        return rect

    def _resource(self, screen: pygame.Surface, bounds: tuple[int, int, int, int],
                  name: str, value: int, maximum: int, color: tuple[int, int, int]) -> None:
        rect = self._panel(screen, bounds)
        self._text(screen, f'{name} {value}/{maximum}', (rect.x + 10, rect.y + 8),
                   width=rect.w - 20, font='heading')
        track = pygame.Rect(rect.x + 10, rect.y + 36, rect.w - 20, 10)
        pygame.draw.rect(screen, (8, 17, 29), track)
        fraction = min(1.0, max(0.0, value / maximum)) if maximum > 0 else 0.0
        fill = track.copy(); fill.width = int(track.width * fraction)
        if fill.width:
            pygame.draw.rect(screen, color, fill)

    def _bp(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        rect = self._panel(screen, BP_PANEL)
        self._text(screen, f'BP {snapshot.bp}/{MAX_BP}', (rect.x + 10, rect.y + 8),
                   width=82, font='heading')
        caption = f'+{snapshot.pending_bp} pending' if snapshot.pending_bp else 'Next volley'
        self._text(screen, caption, (rect.x + 94, rect.y + 11), width=96, font='small',
                   color=ACCENT if snapshot.pending_bp else MUTED)
        for index in range(MAX_BP):
            pip = pygame.Rect(rect.x + 10 + index * 37, rect.y + 36, 32, 10)
            pygame.draw.rect(screen, (8, 17, 29), pip)
            if index < snapshot.bp:
                pygame.draw.rect(screen, BP_COLOR, pip)
            elif index < min(MAX_BP, snapshot.bp + snapshot.pending_bp):
                pygame.draw.rect(screen, ACCENT, pip, width=2)
            else:
                pygame.draw.rect(screen, BORDER, pip, width=1)

    def _progress(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        rect = self._panel(screen, PROGRESS_PANEL)
        self._text(screen, f'Stage {snapshot.stage}  Turn {snapshot.turn_index}',
                   (rect.x + 10, rect.y + 8), width=174, font='heading')
        self._text(screen, 'Score: —', (rect.x + 198, rect.y + 10), width=72,
                   font='body', color=MUTED)
        wave = f'Waves {snapshot.spawned_waves}/{snapshot.total_waves}' if snapshot.total_waves else 'Waves: —'
        if snapshot.has_boss_wave:
            wave += (f' | Bosses alive {snapshot.bosses_remaining}/{snapshot.boss_total}'
                     if snapshot.boss_wave_spawned else ' | Boss pending')
        self._text(screen, wave, (rect.x + 10, rect.y + 34), width=260, font='body', color=MUTED)

    def _statuses(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        rect = self._panel(screen, STATUS_PANEL)
        self._text(screen, 'Effects', (rect.x + 10, rect.y + 5), width=52, font='small', color=MUTED)
        labels = status_labels(snapshot)
        if not labels:
            self._text(screen, 'None', (90, rect.y + 5), width=180, font='small', color=MUTED)
        x = 90
        for kind, label, beneficial in labels:
            chip = pygame.Rect(x, rect.y + 2, STATUS_WIDTHS[kind], 20)
            color = BENEFICIAL if beneficial else HARMFUL
            pygame.draw.rect(screen, color, chip, width=1)
            self._text(screen, label, (x + 5, rect.y + 5), width=chip.w - 10, font='small', color=color)
            x += chip.w + 4
        self._text(screen, hazard_label(snapshot), (rect.right - 218, rect.y + 5),
                   width=208, font='small', color=MUTED)

    def _spell(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        rect = self._panel(screen, SPELL_PANEL)
        hud = snapshot.spell_hud
        if hud is None:
            title = 'No spell selected'
        else:
            number = tuple(SpellId).index(hud.definition.spell_id) + 1
            title = f'[{number}] {hud.definition.name}'
            self._text(screen, f'MP {hud.definition.mp_cost}', (rect.right - 70, rect.y + 9),
                       width=60, font='body', color=MP_COLOR)
        self._text(screen, title, (rect.x + 10, rect.y + 7), width=262, font='heading', color=ACCENT)
        available = snapshot.state is GameState.PLAYER_AIM and hud is not None and hud.ready
        self._text(screen, spell_availability(snapshot), (rect.x + 10, rect.y + 31), width=332,
                   color=BENEFICIAL if available else MUTED)
        self._text(screen, cooldown_label(snapshot), (rect.x + 10, rect.y + 55),
                   width=332, font='small', color=MUTED)

    def _feedback(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        rect = self._panel(screen, FEEDBACK_PANEL)
        phase = {GameState.PLAYER_AIM: 'YOUR ACTION', GameState.SHOT_ANIMATION: 'VOLLEY IN FLIGHT',
                 GameState.SPELL_ANIMATION: 'SPELL IN PROGRESS', GameState.TURN_RESOLVE: 'RESOLVING TURN',
                 GameState.PAUSED: 'PAUSED'}
        self._text(screen, phase.get(snapshot.state, 'COMBAT'), (rect.x + 10, rect.y + 7),
                   width=272, font='small', color=MUTED)
        default = (f'Enemy phase {snapshot.last_resolved_turn} complete.'
                   if snapshot.last_resolved_turn is not None else 'Move, aim, then choose one action.')
        message = snapshot.spell_feedback or default
        # Wrap into two full-size lines; excess future text is visibly ellipsized.
        words = message.split(); lines = ['']
        for word in words:
            candidate = (lines[-1] + ' ' + word).strip()
            if self.fonts['body'].size(candidate)[0] > 272 and len(lines) == 1 and lines[-1]:
                lines.append(word)
            else:
                lines[-1] = candidate
        for index, line in enumerate(lines):
            self._text(screen, line, (rect.x + 10, rect.y + 25 + index * 17), width=272)
        self._text(screen, 'Click: Shoot   W/S: Move   Esc: Pause', (rect.x + 10, rect.y + 59),
                   width=272, font='small', color=MUTED)

    def _shortcuts(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        rect = self._panel(screen, SHORTCUT_PANEL)
        for index, definition in enumerate(SPELLS.values()):
            cell = pygame.Rect(rect.x + 8 + (index % 2) * 128, rect.y + 4 + (index // 2) * 18, 124, 17)
            selected = snapshot.selected_spell is definition.spell_id
            locked = snapshot.stage < definition.unlock_stage
            color = MUTED if locked else TEXT
            if selected:
                pygame.draw.rect(screen, ACCENT, cell, width=1)
            self._text(screen, str(index + 1), (cell.x + 3, cell.y + 2), width=12,
                       font='small', color=ACCENT if selected else color)
            self._text(screen, definition.name.removeprefix('Pom '), (cell.x + 21, cell.y + 2),
                       width=79 if locked else 100, font='small', color=color)
            if locked:
                self._text(screen, f'S{definition.unlock_stage}', (cell.right - 19, cell.y + 2),
                           width=18, font='small', color=ACCENT)

    def draw(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        self._resource(screen, HP_PANEL, 'HP', snapshot.hp, snapshot.max_hp,
                       HARMFUL if snapshot.hp <= snapshot.max_hp * .25 else HP_COLOR)
        self._resource(screen, MP_PANEL, 'MP', snapshot.mp, snapshot.max_mp, MP_COLOR)
        self._bp(screen, snapshot)
        self._progress(screen, snapshot)
        self._statuses(screen, snapshot)
        self._spell(screen, snapshot)
        self._feedback(screen, snapshot)
        self._shortcuts(screen, snapshot)
