"""Model-only support changes; status runtime is resolved through World turns.

Low-level calls do not claim actions. Player input uses World's casting entry
point to claim one main action and resolve the shared turn lifecycle.
"""

from dataclasses import dataclass
from typing import Protocol

from src.spells import (
    SpellCast, SpellContext, SpellDefinition, SpellEngine, SpellFailure, SpellId,
    SpellOwner, SpellResult, StatusCheck,
)
from src.statuses import CLEANSE_REMOVABLE, StatusEffect, StatusKind, StatusState


MEND_HEALING = 50
SUPPORT_SPELLS = frozenset({SpellId.MEND, SpellId.CLEANSE, SpellId.BARRIER})


class SupportOwner(SpellOwner, Protocol):
    hp: int
    max_hp: int
    statuses: StatusState


@dataclass(frozen=True)
class SupportChanges:
    hp_before: int
    hp_after: int
    removed: tuple[StatusEffect, ...]
    granted: StatusEffect | None
    refreshed: bool
    @property
    def healed(self) -> int:
        return self.hp_after - self.hp_before


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

    A prior payment-only action cannot be replayed to grant effects.
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
    if cast.spell_id is SpellId.MEND:
        owner.hp = min(owner.max_hp, owner.hp + MEND_HEALING)
    elif cast.spell_id is SpellId.CLEANSE:
        removed = tuple(effect for effect in owner.statuses.snapshot()
                        if effect.kind in CLEANSE_REMOVABLE)
        for effect in removed:
            owner.statuses.remove(effect.kind, turn=cast.casting_turn)
    else:
        granted = StatusEffect(StatusKind.WARD, 1, cast.casting_turn,
                               source_id=action_id, charges=1)
        refreshed = owner.statuses.put(granted) is not None
    changes = SupportChanges(hp_before, owner.hp, removed, granted, refreshed)
    return SupportSpellResult(commit, changes)
