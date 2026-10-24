"""Immutable status records and deterministic enemy-phase timing.

Poison, Bind and Doom skip aging on their application turn. Ward/Levitation age
only after a full enemy phase they covered; newly granted mid-phase records are
not aged at that boundary. World owns damage and knockout resource changes.
"""

from dataclasses import dataclass, field, replace
from enum import Enum


class StatusKind(Enum):
    POISON = "poison"
    BIND = "bind"
    DOOM = "doom"
    LEVITATION = "levitation"
    WARD = "ward"
    RERAISE = "reraise"


BENEFICIAL_KINDS = frozenset({StatusKind.LEVITATION, StatusKind.WARD, StatusKind.RERAISE})
ESUNA_REMOVABLE = frozenset({StatusKind.POISON, StatusKind.BIND})
RERAISE_HP = 50
POISON_DAMAGE = 3


def validate_turn(turn: int) -> None:
    if type(turn) is not int or turn < 1:
        raise ValueError("Turn must be a positive integer")


def validate_source(source_id: int | str | None) -> None:
    if source_id is not None and not (
        (type(source_id) is int and source_id > 0)
        or (type(source_id) is str and source_id.strip())
    ):
        raise ValueError("Source must be a positive ID or nonempty string")


class StatusEventKind(Enum):
    APPLIED = "status_applied"
    REFRESHED = "status_refreshed"
    REMOVED = "status_removed"
    EXPIRED = "status_expired"
    DURATION_ADVANCED = "duration_advanced"
    DAMAGE = "damage_applied"
    POISON_DAMAGE = "periodic_damage_applied"
    HAZARD_DAMAGE = "hazard_damage_applied"
    WARD_BLOCKED = "damage_blocked_by_ward"
    LEVITATION_BLOCKED = "hazard_blocked_by_levitation"
    DOOM_ADVANCED = "doom_countdown_advanced"
    FORCED_KNOCKOUT = "forced_knockout"
    RERAISE_ACTIVATED = "reraise_activated"
    HAZARD_PLACED = "hazard_placed"
    HAZARD_REFRESHED = "hazard_refreshed"
    HAZARD_REMOVED = "hazard_removed"
    HAZARD_EXPIRED = "hazard_expired"


@dataclass(frozen=True)
class StatusEvent:
    kind: StatusEventKind
    turn: int
    status: StatusKind | None = None
    row: int | None = None
    source_id: int | str | None = None
    amount: int = 0
    attempted_damage: int = 0
    hp_before: int | None = None
    hp_after: int | None = None
    remaining_turns: int | None = None


@dataclass(frozen=True)
class StatusEffect:
    kind: StatusKind
    remaining_turns: int | None
    applied_turn: int
    source_id: int | str | None = None
    charges: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StatusKind):
            raise ValueError("Status kind must be a StatusKind")
        if (self.remaining_turns is not None
                and (type(self.remaining_turns) is not int or self.remaining_turns < 1)):
            raise ValueError("Remaining effective turns must be positive or unspecified")
        validate_turn(self.applied_turn)
        validate_source(self.source_id)
        if self.kind in (StatusKind.WARD, StatusKind.RERAISE):
            if type(self.charges) is not int or self.charges != 1:
                raise ValueError("Active Ward and Reraise records require exactly one charge")
        elif self.charges is not None:
            raise ValueError("Only Ward and Reraise use charges")
        if self.kind is StatusKind.RERAISE and self.remaining_turns is not None:
            raise ValueError("Reraise persists until consumed, without a turn duration")
        if self.kind in (StatusKind.WARD, StatusKind.LEVITATION) and self.remaining_turns is None:
            raise ValueError("Ward and Levitation require an effective duration")

    @property
    def beneficial(self) -> bool:
        return self.kind in BENEFICIAL_KINDS

    @property
    def negative(self) -> bool:
        return not self.beneficial

    @property
    def revival_hp(self) -> int | None:
        return RERAISE_HP if self.kind is StatusKind.RERAISE else None


@dataclass
class StatusState:
    """One immutable record per kind, with phase guards and an immutable event view."""

    _effects: dict[StatusKind, StatusEffect] = field(default_factory=dict, init=False)
    _events: list[StatusEvent] = field(default_factory=list, init=False)
    _phase_turn: int = field(default=0, init=False)
    _expired_turn: int = field(default=0, init=False)
    _poison_turn: int = field(default=0, init=False)
    _doom_turn: int = field(default=0, init=False)

    @property
    def events(self) -> tuple[StatusEvent, ...]:
        return tuple(self._events)

    def record(self, event: StatusEvent) -> None:
        self._events.append(event)

    def get(self, kind: StatusKind) -> StatusEffect | None:
        return self._effects.get(kind)

    def is_active(self, kind: StatusKind, turn: int) -> bool:
        effect = self.get(kind)
        return effect is not None and effect.applied_turn <= turn

    def put(self, effect: StatusEffect) -> StatusEffect | None:
        if not isinstance(effect, StatusEffect):
            raise ValueError("Status state accepts only StatusEffect records")
        previous = self._effects.get(effect.kind)
        self._effects[effect.kind] = effect
        self.record(StatusEvent(StatusEventKind.REFRESHED if previous else StatusEventKind.APPLIED,
                                effect.applied_turn, effect.kind, source_id=effect.source_id,
                                remaining_turns=effect.remaining_turns))
        return previous

    def remove(self, kind: StatusKind, *, turn: int | None = None,
               expired: bool = False) -> StatusEffect | None:
        effect = self.get(kind)
        if effect is None:
            return None
        event_turn = effect.applied_turn if turn is None else turn
        validate_turn(event_turn)
        self._effects.pop(kind)
        self.record(StatusEvent(StatusEventKind.EXPIRED if expired else StatusEventKind.REMOVED,
                                event_turn, kind, source_id=effect.source_id,
                                remaining_turns=0 if expired else effect.remaining_turns))
        return effect

    def snapshot(self) -> tuple[StatusEffect, ...]:
        return tuple(self._effects[kind] for kind in sorted(self._effects, key=lambda k: k.value))

    def begin_phase(self, turn: int) -> bool:
        validate_turn(turn)
        if turn <= self._phase_turn:
            return False
        self._phase_turn = turn
        return True

    def take_poison_tick(self, turn: int) -> StatusEffect | None:
        """Claim one tick; the application phase is grace, without damage or aging."""
        validate_turn(turn)
        if turn <= self._poison_turn:
            return None
        self._poison_turn = turn
        effect = self.get(StatusKind.POISON)
        return effect if effect is not None and turn > effect.applied_turn else None

    def advance_doom(self, turn: int) -> bool:
        """Advance once and remove consumed Doom before reporting its knockout."""
        validate_turn(turn)
        if turn <= self._doom_turn:
            return False
        self._doom_turn = turn
        effect = self.get(StatusKind.DOOM)
        if effect is None or effect.remaining_turns is None or turn <= effect.applied_turn:
            return False
        remaining = effect.remaining_turns - 1
        self.record(StatusEvent(StatusEventKind.DOOM_ADVANCED, turn, StatusKind.DOOM,
                                source_id=effect.source_id, remaining_turns=remaining))
        if remaining == 0:
            self.remove(StatusKind.DOOM, turn=turn, expired=True)
            return True
        self._effects[StatusKind.DOOM] = replace(effect, remaining_turns=remaining)
        return False

    def finish_phase(self, turn: int, initial: tuple[StatusEffect, ...]) -> tuple[StatusEvent, ...]:
        """Age covered intervals after damage; do not age refreshed mid-phase records."""
        validate_turn(turn)
        if turn != self._phase_turn or turn <= self._expired_turn:
            return ()
        self._expired_turn = turn
        index = len(self._events)
        for effect in sorted(initial, key=lambda item: item.kind.value):
            if (self.get(effect.kind) is not effect or effect.remaining_turns is None
                    or effect.kind is StatusKind.DOOM or turn < effect.applied_turn):
                continue
            if effect.kind not in (StatusKind.WARD, StatusKind.LEVITATION) and turn == effect.applied_turn:
                continue
            remaining = effect.remaining_turns - 1
            if remaining == 0:
                self.remove(effect.kind, turn=turn, expired=True)
            else:
                self._effects[effect.kind] = replace(effect, remaining_turns=remaining)
                self.record(StatusEvent(StatusEventKind.DURATION_ADVANCED, turn, effect.kind,
                                        source_id=effect.source_id, remaining_turns=remaining))
        return tuple(self._events[index:])

    def reset(self) -> None:
        self._effects.clear()
        self._events.clear()
        self._phase_turn = self._expired_turn = self._poison_turn = self._doom_turn = 0
