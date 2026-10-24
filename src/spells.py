"""Immutable spell rules, read-only targeting, and model-only resource commits."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Protocol

from src.constants import BATTLEFIELD_ORIGIN, BATTLEFIELD_SIZE, TILE_SIZE
from src.entities import EnemySnapshot
from src.states import GameState


class SpellId(Enum):
    FIRE = "fire"
    STARSTORM = "starstorm"
    METEOR = "meteor"
    CURE = "cure"
    ESUNA = "esuna"
    LEVITATION = "levitation"
    WARD = "ward"
    RERAISE = "reraise"


class TargetKind(Enum):
    NEAREST_IN_ROW = "nearest_in_row"
    FRONT_AREA = "front_area"
    ALL_ENEMIES = "all_enemies"
    SELF = "self"


@dataclass(frozen=True)
class SpellDefinition:
    spell_id: SpellId
    name: str
    mp_cost: int
    cooldown: int
    unlock_stage: int
    target_kind: TargetKind


SPELLS: Mapping[SpellId, SpellDefinition] = MappingProxyType({
    SpellId.FIRE: SpellDefinition(SpellId.FIRE, "Pom Fire", 30, 3, 1, TargetKind.NEAREST_IN_ROW),
    SpellId.STARSTORM: SpellDefinition(SpellId.STARSTORM, "Pom Starstorm", 40, 4, 1, TargetKind.FRONT_AREA),
    SpellId.METEOR: SpellDefinition(SpellId.METEOR, "Pom Meteor", 80, 10, 3, TargetKind.ALL_ENEMIES),
    SpellId.CURE: SpellDefinition(SpellId.CURE, "Pom Cure", 10, 1, 1, TargetKind.SELF),
    SpellId.ESUNA: SpellDefinition(SpellId.ESUNA, "Pom Esuna", 20, 3, 2, TargetKind.SELF),
    SpellId.LEVITATION: SpellDefinition(SpellId.LEVITATION, "Pom Levitation", 20, 3, 2, TargetKind.SELF),
    SpellId.WARD: SpellDefinition(SpellId.WARD, "Pom Ward", 30, 3, 1, TargetKind.SELF),
    SpellId.RERAISE: SpellDefinition(SpellId.RERAISE, "Pom Reraise", 50, 99, 1, TargetKind.SELF),
})


def get_spell(spell_id: SpellId | str) -> SpellDefinition | None:
    if isinstance(spell_id, SpellId):
        return SPELLS[spell_id]
    if type(spell_id) is str:
        try:
            return SPELLS[SpellId(spell_id)]
        except ValueError:
            pass
    return None


class SpellFailure(Enum):
    INVALID_SPELL = "Unknown spell identifier"
    INVALID_STATE = "Spells require an available player aiming action"
    STAGE_LOCKED = "Spell is locked at the current stage"
    INSUFFICIENT_MP = "Not enough MP"
    COOLDOWN = "Spell cooldown has not expired"
    NO_TARGET = "No active enemy matches the spell target"
    FULL_HP = "Cure requires HP below maximum"
    STATUS_RESTRICTED = "A status-dependent casting restriction applies"
    INVALID_ACTION_ID = "Spell action ID must be a nonempty string"
    ALREADY_COMMITTED = "This spell action was already committed"


@dataclass(frozen=True)
class SpellContext:
    """Detached input; World supplies snapshots of active, non-escaped enemies."""

    state: GameState
    stage: int
    turn_index: int
    hp: int
    max_hp: int
    mp: int
    player_row: int
    player_position: tuple[int, int]
    enemies: tuple[EnemySnapshot, ...]
    action_pending: bool = False


@dataclass(frozen=True)
class SpellTargets:
    kind: TargetKind
    enemy_ids: tuple[int, ...] = ()
    center: tuple[float, float] | None = None
    radius: float | None = None


@dataclass(frozen=True)
class SpellCast:
    spell_id: SpellId
    casting_turn: int
    mp_cost: int
    next_ready_turn: int
    targets: SpellTargets


@dataclass(frozen=True)
class SpellResult:
    """A valid description is not an applied effect or a player-facing action."""

    cast: SpellCast | None = None
    failure: SpellFailure | None = None

    @property
    def valid(self) -> bool:
        return self.cast is not None and self.failure is None


StatusCheck = Callable[[SpellDefinition, SpellContext], SpellFailure | None]


class SpellOwner(Protocol):
    mp: int

    def spell_context(self) -> SpellContext: ...


def select_targets(definition: SpellDefinition, context: SpellContext) -> SpellTargets:
    """Select stable IDs without holding mutable entities or applying effects."""
    active = tuple(enemy for enemy in context.enemies if enemy.hp > 0)
    kind = definition.target_kind
    if kind is TargetKind.SELF:
        return SpellTargets(kind)
    if kind is TargetKind.NEAREST_IN_ROW:
        candidates = [enemy for enemy in active if enemy.grid_row == context.player_row]
        nearest = min(candidates, key=lambda enemy: (-enemy.grid_col, enemy.enemy_id), default=None)
        return SpellTargets(kind, (nearest.enemy_id,) if nearest else ())
    if kind is TargetKind.FRONT_AREA:
        left, top = BATTLEFIELD_ORIGIN
        width, height = BATTLEFIELD_SIZE
        center = (max(left, min(left + width, context.player_position[0] - 8 * TILE_SIZE)),
                  max(top, min(top + height, context.player_position[1])))
        radius = 2 * TILE_SIZE
        # Compare enemy-center distances; the circle includes its boundary.
        active = tuple(enemy for enemy in active
                       if ((enemy.bounds.left + enemy.bounds.right) / 2 - center[0]) ** 2
                       + ((enemy.bounds.top + enemy.bounds.bottom) / 2 - center[1]) ** 2
                       <= radius ** 2)
        return SpellTargets(kind, tuple(sorted(enemy.enemy_id for enemy in active)), center, radius)
    return SpellTargets(kind, tuple(sorted(enemy.enemy_id for enemy in active)))


@dataclass
class SpellEngine:
    """Own cooldown/idempotency history; the MP balance belongs only to World."""

    _next_ready_turn: dict[SpellId, int] = field(default_factory=dict, init=False)
    _committed_actions: dict[str, SpellCast] = field(default_factory=dict, init=False)

    @property
    def cooldowns(self) -> Mapping[SpellId, int]:
        return MappingProxyType(self._next_ready_turn.copy())

    def next_ready_turn(self, spell_id: SpellId | str) -> int:
        definition = get_spell(spell_id)
        if definition is None:
            raise ValueError(SpellFailure.INVALID_SPELL.value)
        return self._next_ready_turn.get(definition.spell_id, 1)

    def reset(self) -> None:
        self._next_ready_turn.clear()
        self._committed_actions.clear()

    def validate(self, spell_id: SpellId | str, context: SpellContext, *,
                 status_check: StatusCheck | None = None) -> SpellResult:
        definition = get_spell(spell_id)
        if definition is None:
            return SpellResult(failure=SpellFailure.INVALID_SPELL)
        if context.state is not GameState.PLAYER_AIM or context.action_pending:
            return SpellResult(failure=SpellFailure.INVALID_STATE)
        if context.stage < definition.unlock_stage:
            return SpellResult(failure=SpellFailure.STAGE_LOCKED)
        if context.mp < definition.mp_cost:
            return SpellResult(failure=SpellFailure.INSUFFICIENT_MP)
        if context.turn_index < self.next_ready_turn(definition.spell_id):
            return SpellResult(failure=SpellFailure.COOLDOWN)
        targets = select_targets(definition, context)
        if targets.kind is not TargetKind.SELF and not targets.enemy_ids:
            return SpellResult(failure=SpellFailure.NO_TARGET)
        if definition.spell_id is SpellId.CURE and context.hp >= context.max_hp:
            return SpellResult(failure=SpellFailure.FULL_HP)
        # Status-dependent rules are deferred until supplied by a later system.
        if status_check is not None:
            failure = status_check(definition, context)
            if failure is not None:
                return SpellResult(failure=failure)
        return SpellResult(cast=SpellCast(definition.spell_id, context.turn_index,
                                         definition.mp_cost,
                                         context.turn_index + definition.cooldown + 1,
                                         targets))

    def commit(self, action_id: str, spell_id: SpellId | str, owner: SpellOwner, *,
               status_check: StatusCheck | None = None) -> SpellResult:
        """Revalidate and atomically publish payment/history in the single-threaded model.

        Callers reuse an action ID for retries. Validation descriptions are never
        accepted as payment authority; current MP, targets and readiness are checked.
        This method does not apply effects, claim a gameplay turn, or change scenes.
        """
        if type(action_id) is not str or not action_id.strip():
            return SpellResult(failure=SpellFailure.INVALID_ACTION_ID)
        if action_id in self._committed_actions:
            return SpellResult(failure=SpellFailure.ALREADY_COMMITTED)
        context = owner.spell_context()
        result = self.validate(spell_id, context, status_check=status_check)
        if not result.valid:
            return result
        cast = result.cast
        # Allocate all updated history before changing the authoritative balance.
        cooldowns = self._next_ready_turn | {cast.spell_id: cast.next_ready_turn}
        committed = self._committed_actions | {action_id: cast}
        remaining_mp = context.mp - cast.mp_cost
        owner.mp = remaining_mp
        self._next_ready_turn = cooldowns
        self._committed_actions = committed
        return result
