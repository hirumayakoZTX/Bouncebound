"""Ordered post-enemy hazard/status processing, independent of frames and Pygame.

Hazards precede Poison, then Doom, then duration expiry. Ward blocks positive
ordinary damage, including hazards and Poison; Levitation blocks hazards first.
Knockouts/revival are resolved atomically by World at each actual damage event.
"""

from typing import Protocol

from src.hazards import HazardState, POISON_TILE_DAMAGE
from src.states import GameState
from src.statuses import (
    POISON_DAMAGE, StatusEffect, StatusEvent, StatusEventKind, StatusKind, StatusState,
)


class StatusOwner(Protocol):
    hp: int
    state: GameState
    turn_index: int
    player_row: int
    statuses: StatusState
    hazards: HazardState

    def apply_player_damage(self, amount: int, *, source: str = "direct",
                            row: int | None = None) -> int: ...

    def force_player_knockout(self, *, source: str = "doom") -> int: ...


def process_status_phase(owner: StatusOwner, initial: tuple[StatusEffect, ...]) -> tuple[StatusEvent, ...]:
    turn = owner.turn_index
    if (owner.state is not GameState.TURN_RESOLVE or owner.hp <= 0
            or not owner.statuses.begin_phase(turn)):
        return ()
    index = len(owner.statuses.events)
    tiles = owner.hazards.begin_phase(turn)
    for tile in tiles:
        if owner.hp <= 0:
            break
        if tile.row != owner.player_row:
            continue
        if owner.statuses.is_active(StatusKind.LEVITATION, turn):
            owner.statuses.record(StatusEvent(StatusEventKind.LEVITATION_BLOCKED, turn,
                                              StatusKind.LEVITATION, row=tile.row,
                                              source_id=tile.source_id, attempted_damage=POISON_TILE_DAMAGE,
                                              hp_before=owner.hp, hp_after=owner.hp))
        else:
            owner.apply_player_damage(POISON_TILE_DAMAGE, source="poison_tile", row=tile.row)
    if owner.hp > 0 and owner.statuses.take_poison_tick(turn) is not None:
        owner.apply_player_damage(POISON_DAMAGE, source="poison")
    if owner.hp > 0 and owner.statuses.advance_doom(turn):
        owner.force_player_knockout(source="doom")
    owner.statuses.finish_phase(turn, initial)
    for event in owner.hazards.finish_phase(turn, tiles):
        owner.statuses.record(event)
    return owner.statuses.events[index:]
