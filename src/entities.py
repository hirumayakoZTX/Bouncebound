"""Static grid enemies and collectibles without rendering dependencies."""

from dataclasses import dataclass, field
from enum import Enum

from src.collision import Bounds
from src.constants import BATTLEFIELD_ORIGIN, GRID_COLUMNS, GRID_ROWS, TILE_SIZE


def cell_bounds(col: int, row: int) -> Bounds:
    if (type(col) is not int or type(row) is not int
            or not 0 <= col < GRID_COLUMNS or not 0 <= row < GRID_ROWS):
        raise ValueError("Grid position must use columns 0..13 and rows 0..7")
    left = BATTLEFIELD_ORIGIN[0] + TILE_SIZE * col
    top = BATTLEFIELD_ORIGIN[1] + TILE_SIZE * row
    return Bounds(left, top, left + TILE_SIZE, top + TILE_SIZE)


def validate_id(entity_id: int) -> None:
    if type(entity_id) is not int or entity_id < 1:
        raise ValueError("Entity IDs must be positive integers")


class EnemyType(Enum):
    BASIC = "basic"
    BOMB = "bomb"


@dataclass(frozen=True)
class EnemySnapshot:
    enemy_id: int
    enemy_type: EnemyType
    grid_col: int
    grid_row: int
    hp: int
    max_hp: int
    bounds: Bounds


@dataclass
class Enemy:
    enemy_id: int
    enemy_type: EnemyType
    grid_col: int
    grid_row: int
    hp: int = field(default=5, init=False)
    max_hp: int = field(default=5, init=False)
    contact_damage: int = field(default=5, init=False)

    def __post_init__(self) -> None:
        validate_id(self.enemy_id)
        if not isinstance(self.enemy_type, EnemyType):
            raise ValueError("Only basic and bomb enemy types are supported")
        cell_bounds(self.grid_col, self.grid_row)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def score_value(self) -> int:
        return 100 if self.enemy_type is EnemyType.BASIC else 200

    @property
    def bounds(self) -> Bounds:
        return cell_bounds(self.grid_col, self.grid_row)

    @property
    def position(self) -> tuple[float, float]:
        bounds = self.bounds
        return ((bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2)

    def take_damage(self, amount: int) -> bool:
        """Clamp HP and return whether this call caused the living-to-dead edge."""
        if type(amount) is not int or amount < 0:
            raise ValueError("Damage must be a nonnegative integer")
        if not self.alive:
            return False
        self.hp = max(0, self.hp - amount)
        return not self.alive

    def snapshot(self) -> EnemySnapshot:
        return EnemySnapshot(self.enemy_id, self.enemy_type, self.grid_col, self.grid_row,
                             self.hp, self.max_hp, self.bounds)


@dataclass(frozen=True)
class CrystalSnapshot:
    crystal_id: int
    grid_col: int
    grid_row: int
    bounds: Bounds


@dataclass
class Crystal:
    crystal_id: int
    grid_col: int
    grid_row: int
    collected: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        validate_id(self.crystal_id)
        cell_bounds(self.grid_col, self.grid_row)

    @property
    def bounds(self) -> Bounds:
        return cell_bounds(self.grid_col, self.grid_row)

    def collect(self) -> bool:
        if self.collected:
            return False
        self.collected = True
        return True

    def snapshot(self) -> CrystalSnapshot:
        return CrystalSnapshot(self.crystal_id, self.grid_col, self.grid_row, self.bounds)
