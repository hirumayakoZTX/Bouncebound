"""Model-only offensive effects; no input, animation, or turn-state transitions.

Distinct action IDs can still commit different spells in the same turn, as in
Step 2.1. Step 2.5 must claim one main action and attach the full turn lifecycle.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from src.combat import BatchDamageResult, Combat
from src.spells import (
    SpellCast, SpellContext, SpellDefinition, SpellEngine, SpellFailure, SpellId,
    SpellOwner, SpellResult, StatusCheck,
)


OFFENSIVE_DAMAGE: Mapping[SpellId, int] = MappingProxyType({
    SpellId.FIRE: 20,
    SpellId.STARSTORM: 10,
    SpellId.METEOR: 15,
})


@dataclass(frozen=True)
class OffensiveSpellResult:
    commit: SpellResult
    effects: BatchDamageResult | None = None

    @property
    def valid(self) -> bool:
        return self.commit.valid and self.effects is not None

    @property
    def failure(self) -> SpellFailure | None:
        return self.commit.failure

    @property
    def cast(self) -> SpellCast | None:
        return self.commit.cast


def execute_offensive(action_id: str, spell_id: SpellId | str, owner: SpellOwner,
                      engine: SpellEngine, combat: Combat, *,
                      status_check: StatusCheck | None = None) -> OffensiveSpellResult:
    """Freshly validate/pay once, then resolve direct damage and all Bomb chains.

    The payment-only and effect APIs share the engine's action-ID ledger. A prior
    payment-only commit cannot later be replayed here to obtain an extra effect.
    Only identifiers are accepted; caller-created cast descriptions confer no authority.
    """
    def eligible(definition: SpellDefinition, context: SpellContext) -> SpellFailure | None:
        if definition.spell_id not in OFFENSIVE_DAMAGE:
            return SpellFailure.UNSUPPORTED_EFFECT
        return status_check(definition, context) if status_check is not None else None

    commit = engine.commit(action_id, spell_id, owner, status_check=eligible)
    cast = commit.cast
    if not commit.valid or cast is None:
        return OffensiveSpellResult(commit)
    effects = combat.apply_damage_batch(cast.targets.enemy_ids, OFFENSIVE_DAMAGE[cast.spell_id],
                                       source=f"spell:{cast.spell_id.value}")
    return OffensiveSpellResult(commit, effects)
