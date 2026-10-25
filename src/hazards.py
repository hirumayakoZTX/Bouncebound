"""Row-keyed PoisonTiles: two phases after placement, with refresh instead of stacks."""

from dataclasses import dataclass, field, replace

from src.constants import GRID_ROWS
from src.statuses import StatusEvent, StatusEventKind, validate_source, validate_turn


POISON_TILE_DAMAGE = 5


def validate_row(row: int) -> None:
    if type(row) is not int or not 0 <= row < GRID_ROWS:
        raise ValueError("PoisonTile row must be an integer from 0 to 7")


@dataclass(frozen=True)
class PoisonTile:
    row: int
    remaining_turns: int
    applied_turn: int
    source_id: int | str | None = None

    def __post_init__(self) -> None:
        validate_row(self.row)
        validate_turn(self.applied_turn)
        validate_source(self.source_id)
        if type(self.remaining_turns) is not int or self.remaining_turns < 1:
            raise ValueError("PoisonTile duration must be a positive integer")


@dataclass
class HazardState:
    _tiles: dict[int, PoisonTile] = field(default_factory=dict, init=False)
    _phase_turn: int = field(default=0, init=False)
    _expired_turn: int = field(default=0, init=False)

    def put(self, tile: PoisonTile) -> StatusEvent:
        if not isinstance(tile, PoisonTile):
            raise ValueError("Hazard state accepts only PoisonTile records")
        previous = self._tiles.get(tile.row)
        self._tiles[tile.row] = tile
        return StatusEvent(StatusEventKind.HAZARD_REFRESHED if previous else StatusEventKind.HAZARD_PLACED,
                           tile.applied_turn, row=tile.row, source_id=tile.source_id,
                           remaining_turns=tile.remaining_turns)

    def remove(self, row: int) -> PoisonTile | None:
        validate_row(row)
        return self._tiles.pop(row, None)

    def snapshot(self) -> tuple[PoisonTile, ...]:
        return tuple(self._tiles[row] for row in sorted(self._tiles))

    def begin_phase(self, turn: int, initial: tuple[PoisonTile, ...] = ()) -> tuple[PoisonTile, ...]:
        validate_turn(turn)
        if turn <= self._phase_turn:
            return ()
        self._phase_turn = turn
        # A mid-phase refresh preserves an already-earned hit. Return the old
        # eligible record so finish_phase leaves the refreshed duration intact.
        due = {tile.row: tile for tile in initial if tile.applied_turn < turn
               and tile.row in self._tiles}
        due.update({tile.row: tile for tile in self.snapshot() if tile.applied_turn < turn})
        return tuple(due[row] for row in sorted(due))

    def finish_phase(self, turn: int, initial: tuple[PoisonTile, ...]) -> tuple[StatusEvent, ...]:
        validate_turn(turn)
        if turn != self._phase_turn or turn <= self._expired_turn:
            return ()
        self._expired_turn = turn
        events = []
        for tile in sorted(initial, key=lambda item: item.row):
            if self._tiles.get(tile.row) is not tile:
                continue
            remaining = tile.remaining_turns - 1
            if remaining == 0:
                self._tiles.pop(tile.row)
                kind = StatusEventKind.HAZARD_EXPIRED
            else:
                self._tiles[tile.row] = replace(tile, remaining_turns=remaining)
                kind = StatusEventKind.DURATION_ADVANCED
            events.append(StatusEvent(kind, turn, row=tile.row, source_id=tile.source_id,
                                      remaining_turns=remaining))
        return tuple(events)

    def reset(self) -> None:
        self._tiles.clear()
        self._phase_turn = self._expired_turn = 0
