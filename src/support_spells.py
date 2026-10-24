"""Model-only support changes; duration and knockout processing remain deferred.

Distinct action IDs may still commit different spells in one turn. Player-facing
casting and enforcement of one main action per turn belong to later integration.
"""

from dataclasses import dataclass
from typing import Protocol

from src.spells import (
    SpellCast, SpellContext, SpellDefinition, SpellEngine, SpellFailure, SpellId,
    SpellOwner, SpellResult, StatusCheck,
)
from src.statuses import ESUNA_REMOVABLE, StatusEffect, StatusKind, StatusState


CURE_HEALING = 50
SUPPORT_SPELLS = frozenset({SpellId.CURE, SpellId.ESUNA, SpellId.LEVITATION,
                          SpellId.WARD, SpellId.RERAISE})


class SupportOwner(SpellOwner, Protocol):
    hp: int
    max_hp: int
    statuses: StatusState
    reraise_used: bool


@dataclass(frozen=True)
class SupportChanges:
    hp_before: int
    hp_after: int
    removed: tuple[StatusEffect, ...]
    granted: StatusEffect | None
    refreshed: bool
    reraise_used: bool
    reraise_active: bool

    @property
    def healed(self) -> int:
        return self.hp_after - self.hp_before

    @property
    def reraise_available(self) -> bool:
        return not self.reraise_used


@dataclass(frozen=True)
class SupportSpellResult:
    commit: SpellResult
    effects: SupportChanges | None = None

    @property
    def valid(self) -> bool:
        return self.commit.valid and self.effects is not None

    @property
    def failure(self) -> SpellFailure | None:
        return self.commit.failure

    @property
    def cast(self) -> SpellCast | None:
        return self.commit.cast


def execute_support(action_id: str, spell_id: SpellId | str, owner: SupportOwner,
                    engine: SpellEngine, *, status_check: StatusCheck | None = None) -> SupportSpellResult:
    """Revalidate/pay through the shared ledger, then apply one support change.

    Successful support execution consumes Reraise's encounter allowance. A prior
    payment-only action cannot be replayed to grant effects. Removing an active
    Reraise record does not restore the separate encounter allowance.
    """
    def eligible(definition: SpellDefinition, context: SpellContext) -> SpellFailure | None:
        if definition.spell_id not in SUPPORT_SPELLS:
            return SpellFailure.UNSUPPORTED_SUPPORT_EFFECT
        return status_check(definition, context) if status_check is not None else None

    commit = engine.commit(action_id, spell_id, owner, status_check=eligible)
    cast = commit.cast
    if not commit.valid or cast is None:
        return SupportSpellResult(commit)
    hp_before = owner.hp
    removed = ()
    granted = None
    refreshed = False
    if cast.spell_id is SpellId.CURE:
        owner.hp = min(owner.max_hp, owner.hp + CURE_HEALING)
    elif cast.spell_id is SpellId.ESUNA:
        removed = tuple(effect for effect in owner.statuses.snapshot() if effect.kind in ESUNA_REMOVABLE)
        for effect in removed:
            owner.statuses.remove(effect.kind)
    else:
        # Grant state only: no immunity, damage interception, or revival runs here.
        kind = StatusKind(cast.spell_id.value)
        granted = StatusEffect(kind, None if kind is StatusKind.RERAISE else 1,
                               cast.casting_turn, source_id=action_id,
                               charges=1 if kind in (StatusKind.WARD, StatusKind.RERAISE) else None)
        refreshed = owner.statuses.put(granted) is not None
        if kind is StatusKind.RERAISE:
            owner.reraise_used = True
    changes = SupportChanges(hp_before, owner.hp, removed, granted, refreshed,
                             owner.reraise_used, owner.statuses.get(StatusKind.RERAISE) is not None)
    return SupportSpellResult(commit, changes)
