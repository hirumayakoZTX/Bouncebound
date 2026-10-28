"""Bounded presentation effects for already-resolved immutable gameplay facts.

Update consumes events; draw only reads cached effects. Nothing here owns a
World, Combat, projectile, spell payment, or turn-resolution callback.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from math import cos, sin, pi, isfinite
from typing import TYPE_CHECKING

import pygame

from src.assets import AssetManager
from src.constants import MAX_BP
from src.entities import EnemyType, EnemySnapshot, LIVE_BOSSES
from src.player_actions import ActionKind
from src.spells import SpellId
from src.states import ACTIVE_STATES, GameState
from src.statuses import StatusEventKind as StatusEventType, StatusKind

if TYPE_CHECKING:
    from src.world import WorldSnapshot


MAX_EFFECTS = 128
MAX_TRAIL_POINTS = 6
MAX_LABELS = 64
COMBAT_CLIP = (96, 72, 752, 384)  # Arena plus the unchanged player/launch lane.
TERMINALS = frozenset({GameState.STAGE_CLEAR, GameState.GAME_OVER, GameState.VICTORY, GameState.RESULTS})
CUE_FILES = {name: f'sounds/{name}.wav' for name in
             ('shoot', 'bounce', 'hit', 'death', 'spellcast', 'damage', 'victory', 'defeat')}
ORB_COLORS = ((255, 223, 130), (124, 221, 255), (198, 175, 255), (146, 239, 180), (255, 178, 155))
SPELL_COLORS = {SpellId.FIRE: (255, 164, 91), SpellId.STARSTORM: (167, 190, 255),
                SpellId.METEOR: (239, 159, 133), SpellId.CURE: (139, 236, 163),
                SpellId.ESUNA: (182, 230, 252), SpellId.LEVITATION: (149, 220, 238),
                SpellId.WARD: (132, 194, 255), SpellId.RERAISE: (255, 219, 147)}


@dataclass(frozen=True)
class VisualEffect:
    event_id: int
    kind: str
    position: tuple[float, float]
    duration: float = .32
    age: float = 0.0
    entity_id: int | None = None
    label: str = ''
    targets: tuple[tuple[float, float], ...] = ()
    radius: float = 0.0
    boss: bool = False
    status_kind: StatusKind | None = None

    @property
    def progress(self) -> float:
        return min(1.0, self.age / self.duration)


@dataclass(frozen=True)
class PreviousFrame:
    stage: int
    turn_index: int
    state: GameState
    enemies: tuple[EnemySnapshot, ...]


def previous_frame(snapshot):
    # Retain active geometry, never an accumulating World event history.
    return PreviousFrame(snapshot.stage, snapshot.turn_index, snapshot.state, snapshot.enemies)


class AudioCues:
    """Fixed, lazy cue vocabulary; disabled audio performs no resource loading."""

    def __init__(self) -> None:
        self._sounds = {}
        self._assets = None

    def play(self, cue: str, assets: AssetManager) -> None:
        if not assets.audio_enabled or cue not in CUE_FILES:
            return
        if assets is not self._assets:
            self.clear()
            self._assets = assets
        if cue not in self._sounds:
            self._sounds[cue] = assets.load_sound(CUE_FILES[cue])
        self._sounds[cue].play()

    def silence(self) -> None:
        for sound in self._sounds.values():
            sound.stop()

    def clear(self) -> None:
        self.silence()
        self._sounds.clear()
        self._assets = None


class FeedbackLayer:
    """One bounded pool, sequence cursors, and at most five short projectile trails."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.audio = AudioCues()
        self._font = None
        self._labels: OrderedDict[tuple[str, tuple[int, int, int]], pygame.Surface] = OrderedDict()
        self._previous = None
        self._epoch = None
        self._combat_cursor = self._status_cursor = self._sequence = 0
        self._action_id = None
        self._active_statuses = frozenset()
        self.effects: deque[VisualEffect] = deque(maxlen=MAX_EFFECTS)
        self.trails: dict[int, deque[tuple[float, float]]] = {}
        self.last_events: tuple[VisualEffect, ...] = ()

    def clear(self) -> None:
        self.audio.clear()
        self.effects.clear(); self.trails.clear()
        self._previous = None; self._epoch = None; self._action_id = None
        self._combat_cursor = self._status_cursor = self._sequence = 0
        self.last_events = ()
        self._active_statuses = frozenset()
        self._new = deque(maxlen=MAX_EFFECTS)
        self._labels.clear()

    def _emit(self, kind: str, position, *, cue=None, assets, duration=.32, **values) -> None:
        self._sequence += 1
        effect = VisualEffect(self._sequence, kind, tuple(position), duration=duration, **values)
        self._new.append(effect)
        if self.enabled and (effect.status_kind is None or effect.status_kind in self._active_statuses):
            self.effects.append(effect)
        if cue is not None and self._cue_count < 32:
            self.audio.play(cue, assets)
            self._cue_count += 1

    def update(self, snapshot: WorldSnapshot, elapsed: float, assets: AssetManager, *, epoch: int = 0) -> None:
        """Explicit presentation step, after gameplay. Epoch is owned by Game input routing."""
        if not isfinite(elapsed) or elapsed < 0:
            raise ValueError('Presentation elapsed time must be finite and nonnegative')
        old = self._previous
        reset = (self._epoch is not None and epoch != self._epoch
                 or old is not None and (snapshot.stage != old.stage or snapshot.turn_index < old.turn_index
                     or old.state in TERMINALS and snapshot.state not in TERMINALS))
        if reset:
            self.clear(); old = None
        first = self._epoch is None
        self._epoch = epoch
        self._active_statuses = frozenset(effect.kind for effect in snapshot.statuses)
        if snapshot.state is GameState.PAUSED:
            if old is None or old.state is not GameState.PAUSED:
                self.audio.silence()
            self._previous = previous_frame(snapshot)
            self.last_events = ()
            return
        dt = 0.0 if old is None or old.state is GameState.PAUSED else min(elapsed, .25)
        self.effects = deque((replace(effect, age=effect.age + dt) for effect in self.effects
                              if effect.age + dt < effect.duration
                              and (effect.status_kind is None or effect.status_kind in self._active_statuses)
                              and (not effect.kind.startswith('spell:') or snapshot.state is GameState.SPELL_ANIMATION)),
                             maxlen=MAX_EFFECTS)
        self._new = deque(maxlen=MAX_EFFECTS); self._cue_count = 0
        observations = snapshot.combat_observations
        if first and not reset:
            # Attaching to an existing encounter must not replay archived effects.
            self._combat_cursor = observations[-1].sequence if observations else 0
            self._status_cursor = len(snapshot.status_events)
        if observations and observations[-1].sequence < self._combat_cursor:
            self._combat_cursor = 0
        fresh = tuple(event for event in observations if event.sequence > self._combat_cursor)
        positions = {e.enemy_id: ((e.bounds.left + e.bounds.right)/2, (e.bounds.top + e.bounds.bottom)/2)
                     for e in (old.enemies if old else ())}
        positions.update({e.enemy_id: ((e.bounds.left + e.bounds.right)/2, (e.bounds.top + e.bounds.bottom)/2)
                          for e in snapshot.enemies})
        positions.update({event.entity_id: event.position for event in fresh if event.enemy_type is not None})
        action = snapshot.pending_action
        if action is not None and action.action_id != self._action_id:
            self._action_id = action.action_id
            if action.kind is ActionKind.SHOT and not action.completed and snapshot.projectiles:
                self._emit('launch', snapshot.aim_origin, assets=assets, cue='shoot', label=f'Volley x{len(snapshot.projectiles)}')
            elif snapshot.spell_result is not None and snapshot.spell_result.valid:
                result = snapshot.spell_result; cast = result.cast
                targets = tuple(positions[i] for i in cast.targets.enemy_ids if i in positions)
                position = cast.targets.center or snapshot.player_position
                label = ''
                if cast.spell_id is SpellId.CURE:
                    label = f'+{result.effects.healed} HP'
                elif cast.spell_id is SpellId.ESUNA:
                    label = f'Cleansed {len(result.effects.removed)}'
                self._emit('spell:' + cast.spell_id.value, position, assets=assets, cue='spellcast',
                           duration=.45, targets=targets, radius=cast.targets.radius or 0,
                           label=label, status_kind=(StatusKind(cast.spell_id.value)
                           if cast.spell_id in (SpellId.WARD, SpellId.LEVITATION, SpellId.RERAISE) else None))
        for event in fresh:
            if event.kind == 'death':
                kind = 'explosion' if event.enemy_type is EnemyType.BOMB else 'death'
                self._emit(kind, event.position, entity_id=event.entity_id, assets=assets, cue='death',
                           boss=event.enemy_type in LIVE_BOSSES, duration=.42)
            elif event.kind == 'hit':
                self._emit('hit', event.position, entity_id=event.entity_id, label=f'-{event.amount}',
                           assets=assets, cue='hit', duration=.24)
            else:
                self._emit(event.kind, event.position, entity_id=event.entity_id, assets=assets,
                           cue='bounce' if event.kind == 'bounce' else None, duration=.2)
        if observations:
            self._combat_cursor = observations[-1].sequence
        if len(snapshot.status_events) < self._status_cursor:
            self._status_cursor = 0
        for event in snapshot.status_events[self._status_cursor:]:
            values = dict(assets=assets)
            if event.kind in (StatusEventType.DAMAGE, StatusEventType.POISON_DAMAGE, StatusEventType.HAZARD_DAMAGE):
                if event.amount > 0:
                    prefix = 'Poison ' if event.kind is StatusEventType.POISON_DAMAGE else 'Tile ' if event.kind is StatusEventType.HAZARD_DAMAGE else ''
                    self._emit('damage', snapshot.player_position, label=f'{prefix}-{event.amount}', cue='damage', **values)
            elif event.kind is StatusEventType.WARD_BLOCKED:
                self._emit('ward_block', snapshot.player_position, label='BLOCK', **values)
            elif event.kind is StatusEventType.LEVITATION_BLOCKED:
                self._emit('floor_block', snapshot.player_position, label='FLOOR SAFE', **values)
            elif event.kind is StatusEventType.RERAISE_ACTIVATED:
                self._emit('revive', snapshot.player_position, label=f'REVIVE +{event.amount}', duration=.65, **values)
            elif event.kind is StatusEventType.FORCED_KNOCKOUT:
                # Revival is already resolved; never show a terminal defeat here.
                self._emit('warning', snapshot.player_position, label='EXECUTE' if event.source_id == 'odin_execute' else 'DOOM', **values)
            elif event.kind in (StatusEventType.APPLIED, StatusEventType.REFRESHED) and event.status in (StatusKind.POISON, StatusKind.BIND, StatusKind.DOOM):
                self._emit('warning', snapshot.player_position, label=event.status.name, status_kind=event.status, **values)
        self._status_cursor = len(snapshot.status_events)
        if old is not None:
            previous_enemies = {e.enemy_id: e for e in old.enemies}
            for enemy in snapshot.enemies:
                previous = previous_enemies.get(enemy.enemy_id)
                if previous is not None and enemy.enraged and not previous.enraged:
                    self._emit('warning', positions[enemy.enemy_id], label='ENRAGED', assets=assets)
        if old is None or old.state is not snapshot.state:
            if snapshot.state in (GameState.STAGE_CLEAR, GameState.VICTORY, GameState.GAME_OVER):
                kind = 'victory' if snapshot.state is GameState.VICTORY else 'defeat' if snapshot.state is GameState.GAME_OVER else 'clear'
                self._emit(kind, (480, 206), assets=assets, duration=.6,
                           cue=kind if kind in ('victory', 'defeat') else None)
        active = {orb.projectile_id for orb in snapshot.projectiles[:MAX_BP]}
        self.trails = {i: trail for i, trail in self.trails.items() if i in active}
        if self.enabled:
            for orb in snapshot.projectiles[:MAX_BP]:
                trail = self.trails.setdefault(orb.projectile_id, deque(maxlen=MAX_TRAIL_POINTS))
                if not trail or trail[-1] != orb.position:
                    trail.append(orb.position)
        self.last_events = tuple(self._new)
        self._previous = previous_frame(snapshot)

    def _label(self, screen, text, position, color) -> None:
        if not text:
            return
        if self._font is None:
            self._font = pygame.font.Font(None, 22)
        key = (text, color)
        image = self._labels.get(key)
        if image is None:
            image = self._font.render(text, True, color)
            self._labels[key] = image
            if len(self._labels) > MAX_LABELS:
                self._labels.popitem(last=False)
        else:
            self._labels.move_to_end(key)
        x, y = position
        x = max(98, min(846-image.get_width(), x-image.get_width()/2))
        y = max(74, min(454-image.get_height(), y))
        rect = image.get_rect(topleft=(round(x), round(y)))
        pygame.draw.rect(screen, (21, 28, 44), rect)
        screen.blit(image, rect)

    def draw(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        """No timers, event consumption, random state, or sound playback during draw."""
        if not self.enabled:
            return
        clip = screen.get_clip()
        combat = snapshot.state in ACTIVE_STATES or snapshot.state is GameState.PAUSED
        screen.set_clip(COMBAT_CLIP if combat else screen.get_rect())
        if combat:
            for identifier, trail in self.trails.items():
                color = ORB_COLORS[(identifier-1) % len(ORB_COLORS)]
                for index, (x, y) in enumerate(trail):
                    size = 2 + index // 3
                    shade = tuple(int(c * (.3 + .07 * index)) for c in color)
                    pygame.draw.rect(screen, shade, (round(x)-size//2, round(y)-size//2, size, size))
        label_slots = {}
        for effect in self.effects:
            terminal = effect.kind in ('clear', 'victory', 'defeat')
            if terminal == combat:
                continue
            x, y = effect.position; progress = effect.progress
            radius = 7 + round(14 * progress)
            color = (255, 208, 127)
            kind = effect.kind
            anchor = (round(x/24), round(y/24))
            slot = label_slots.get(anchor, 0)
            label_y = y - 42 - slot*18 - 8*progress
            if label_y < 74:
                label_y = y + 28 + slot*18
            def label(text):
                if text and slot < 3:
                    self._label(screen, text, (x, label_y), color)
                    label_slots[anchor] = slot + 1
            if kind.startswith('spell:'):
                spell = SpellId(kind.split(':')[1]); color = SPELL_COLORS[spell]
                if spell is SpellId.FIRE:
                    for target in effect.targets:
                        pygame.draw.line(screen, color, (824, y), target, width=2)
                        pygame.draw.circle(screen, color, target, radius, width=2)
                elif spell is SpellId.STARSTORM:
                    pygame.draw.circle(screen, color, (round(x), round(y)), round(effect.radius), width=1)
                    for angle in range(5):
                        a = angle * 2*pi/5 + progress*.3
                        point = (round(x+cos(a)*effect.radius*.6), round(y+sin(a)*effect.radius*.6))
                        pygame.draw.rect(screen, color, (*point, 4, 4))
                elif spell is SpellId.METEOR:
                    for tx, ty in effect.targets:
                        offset = round((1-progress)*25)
                        pygame.draw.line(screen, color, (tx+offset, ty-offset), (tx, ty), width=3)
                        pygame.draw.circle(screen, color, (round(tx), round(ty)), radius, width=1)
                elif spell is SpellId.CURE:
                    pygame.draw.rect(screen, color, (x-3, y-16, 6, 32))
                    pygame.draw.rect(screen, color, (x-16, y-3, 32, 6))
                elif spell is SpellId.LEVITATION:
                    for offset in (18, 26):
                        pygame.draw.line(screen, color, (x-18, y+offset), (x+18, y+offset), width=2)
                    pygame.draw.polygon(screen, color, ((x-6,y-22),(x,y-30),(x+6,y-22)), width=2)
                elif spell is SpellId.WARD:
                    pygame.draw.polygon(screen, color, ((x,y-28),(x+24,y-14),(x+20,y+18),
                                                        (x,y+30),(x-20,y+18),(x-24,y-14)), width=2)
                elif spell is SpellId.RERAISE:
                    pygame.draw.ellipse(screen, color, (x-21,y-28,42,12), width=2)
                    pygame.draw.rect(screen, color, (x-2,y-10,4,20))
                    pygame.draw.rect(screen, color, (x-10,y-2,20,4))
                else:
                    pygame.draw.polygon(screen, color, ((x,y-24),(x+24,y),(x,y+24),(x-24,y)), width=2)
                label(effect.label or ('Reraise ready' if spell is SpellId.RERAISE else ''))
            elif kind == 'explosion':
                color = (255, 161, 102)
                for col in (-1,0,1):
                    for row in (-1,0,1):
                        cx, cy = x + col*48, y + row*48
                        if (col or row) and 120 <= cx <= 744 and 96 <= cy <= 432:
                            pygame.draw.rect(screen, color, (cx-22,cy-22,44,44), width=1)
                pygame.draw.circle(screen, color, (round(x),round(y)), radius+12, width=2)
            elif kind in ('ward_block', 'floor_block', 'revive', 'damage', 'warning'):
                color = (149, 222, 255) if kind in ('ward_block','floor_block') else (154, 238, 183) if kind=='revive' else (255, 172, 155)
                if kind == 'floor_block':
                    pygame.draw.line(screen, color, (x-22,y+23),(x+22,y+23),width=3)
                else:
                    pygame.draw.rect(screen, color, (x-24,y-24,48,48),width=2)
                label(effect.label)
            else:
                color = (255, 173, 151) if kind in ('hit','death','defeat') else (144, 230, 205) if kind in ('crystal','clear') else color
                if kind == 'hit':
                    pygame.draw.rect(screen, color, (x-22,y-22,44,44),width=2)
                else:
                    count = 8 if effect.boss else 4
                    for index in range(count):
                        angle = index * 2*pi/count
                        px = round(x+cos(angle)*radius); py = round(y+sin(angle)*radius)
                        pygame.draw.rect(screen, color, (px-2,py-2,4,4))
                label(effect.label if kind in ('hit', 'launch') else '')
        screen.set_clip(clip)
