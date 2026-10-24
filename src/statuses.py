"""Immutable status data and refresh storage, without ticking or interception.

Future turn processing must use applied_turn to avoid decrementing an effect in
its application turn. Ward charges concern ordinary damage, not forced death.
"""

from dataclasses import dataclass, field
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
        if type(self.applied_turn) is not int or self.applied_turn < 1:
            raise ValueError("Status application turn must be a positive integer")
        if self.source_id is not None and not (
            (type(self.source_id) is int and self.source_id > 0)
            or (type(self.source_id) is str and self.source_id.strip())
        ):
            raise ValueError("Status source must be a positive ID or nonempty string")
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
    """One immutable record per kind; replacement refreshes instead of stacking."""

    _effects: dict[StatusKind, StatusEffect] = field(default_factory=dict, init=False)

    def get(self, kind: StatusKind) -> StatusEffect | None:
        return self._effects.get(kind)

    def put(self, effect: StatusEffect) -> StatusEffect | None:
        if not isinstance(effect, StatusEffect):
            raise ValueError("Status state accepts only StatusEffect records")
        previous = self._effects.get(effect.kind)
        self._effects[effect.kind] = effect
        return previous

    def remove(self, kind: StatusKind) -> StatusEffect | None:
        return self._effects.pop(kind, None)

    def snapshot(self) -> tuple[StatusEffect, ...]:
        return tuple(self._effects[kind] for kind in sorted(self._effects, key=lambda k: k.value))

    def reset(self) -> None:
        self._effects.clear()
