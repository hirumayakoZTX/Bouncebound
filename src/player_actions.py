"""Immutable main-action authorization and spell presentation records."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from src.spells import SpellDefinition, SpellFailure


SPELL_ANIMATION_SECONDS = 0.45


class ActionKind(Enum):
    SHOT = "shot"
    SPELL = "spell"


@dataclass(frozen=True)
class MainAction:
    action_id: str
    kind: ActionKind
    turn: int
    completed: bool = False


@dataclass(frozen=True)
class SpellHUD:
    definition: SpellDefinition
    next_ready_turn: int
    failure: SpellFailure | None

    @property
    def ready(self) -> bool:
        return self.failure is None


SPELL_FEEDBACK = MappingProxyType({
    SpellFailure.NO_SELECTION: "Select a spell with 1-8",
    SpellFailure.INSUFFICIENT_MP: "Not enough MP",
    SpellFailure.COOLDOWN: "Spell on cooldown",
    SpellFailure.STAGE_LOCKED: "Spell locked",
    SpellFailure.NO_TARGET: "No valid target",
    SpellFailure.FULL_HP: "Cure requires missing HP",
    SpellFailure.RERAISE_USED: "Reraise already used",
    SpellFailure.INVALID_STATE: "Main action unavailable",
})


def spell_failure_message(failure: SpellFailure) -> str:
    return SPELL_FEEDBACK.get(failure, failure.value)
