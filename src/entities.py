"""Grid enemies and collectibles without rendering dependencies."""

from collections.abc import Callable
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


def validate_damage(amount: int) -> None:
    if type(amount) is not int or amount < 0:
        raise ValueError("Damage must be a nonnegative integer")


@dataclass(frozen=True)
class EnemyTurnContext:
    turn_index: int
    damage_player: Callable[[int], int]
    player_defeated: Callable[[], bool]
    attack_player: Callable[[int], int] | None = None


class EnemyType(Enum):
    BASIC = "basic"
    BOMB = "bomb"
    ULTROS = "ultros"
    TYPHON = "typhon"


STAGE_ONE_BOSSES = frozenset({EnemyType.ULTROS, EnemyType.TYPHON})
BOSS_HP = 15
BOSS_ATTACK_DAMAGE = 5


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
    attack_damage: int = field(default=0, init=False)
    turns_alive: int = field(default=0, init=False)
    last_action_turn: int | None = field(default=None, init=False)
    escaped: bool = field(default=False, init=False)
    escape_turn: int | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        validate_id(self.enemy_id)
        if not isinstance(self.enemy_type, EnemyType):
            raise ValueError("Enemy type must be a supported EnemyType")
        cell_bounds(self.grid_col, self.grid_row)
        if self.is_boss:
            self.hp = self.max_hp = BOSS_HP
            self.attack_damage = BOSS_ATTACK_DAMAGE

    @property
    def is_boss(self) -> bool:
        return self.enemy_type in STAGE_ONE_BOSSES

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def active(self) -> bool:
        return self.alive and not self.escaped

    @property
    def score_value(self) -> int:
        return 1000 if self.is_boss else 100 if self.enemy_type is EnemyType.BASIC else 200

    @property
    def bounds(self) -> Bounds:
        return cell_bounds(self.grid_col, self.grid_row)

    @property
    def position(self) -> tuple[float, float]:
        bounds = self.bounds
        return ((bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2)

    def take_damage(self, amount: int) -> bool:
        """Clamp HP and return whether this call caused the living-to-dead edge."""
        validate_damage(amount)
        if not self.active:
            return False
        self.hp = max(0, self.hp - amount)
        return not self.alive

    def on_turn(self, context: EnemyTurnContext) -> bool:
        """Claim once; Stage 1 bosses attack before standard movement/contact."""
        if not self.active or self.last_action_turn == context.turn_index:
            return False
        self.last_action_turn = context.turn_index
        self.turns_alive += 1
        if self.is_boss:
            damage = context.attack_player or context.damage_player
            damage(self.attack_damage)
        return True

    def advance_one_cell(self) -> bool:
        if not self.active or self.grid_col >= GRID_COLUMNS - 1:
            return False
        self.grid_col += 1
        return True

    def escape(self, turn_index: int) -> bool:
        """Archive defense-line removal separately from combat death."""
        if not self.active or self.grid_col != GRID_COLUMNS - 1:
            return False
        self.escaped = True
        self.escape_turn = turn_index
        return True

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
