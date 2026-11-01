"""Poison processing after enemy actions, independent of frames and Pygame."""

from typing import Protocol

from src.states import GameState
from src.statuses import POISON_DAMAGE, StatusEffect, StatusEvent, StatusKind, StatusState


class StatusOwner(Protocol):
    hp: int
    state: GameState
    turn_index: int
    player_row: int
    statuses: StatusState
    def apply_player_damage(self, amount: int, *, source: str = "direct",
                            row: int | None = None) -> int: ...


def process_status_phase(owner: StatusOwner,
                         initial: tuple[StatusEffect, ...]) -> tuple[StatusEvent, ...]:
    turn = owner.turn_index
    if (owner.state is not GameState.TURN_RESOLVE or owner.hp <= 0
            or not owner.statuses.begin_phase(turn)):
        return ()
    index = len(owner.statuses.events)
    initial_poison = next((effect for effect in initial if effect.kind is StatusKind.POISON), None)
    effect = owner.statuses.take_poison_tick(turn, initial_poison)
    if owner.hp > 0 and effect is not None:
        source = f"poison:{effect.source_id}" if effect.source_id is not None else "poison"
        owner.apply_player_damage(POISON_DAMAGE, source=source)
    owner.statuses.finish_phase(turn, initial)
    return owner.statuses.events[index:]
