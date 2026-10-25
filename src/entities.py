"""Grid enemies and collectibles without rendering dependencies."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from src.statuses import StatusKind

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
    player_row: int | None = None
    apply_status: Callable[[StatusKind, int, int], object] | None = None
    place_poison_tile: Callable[[int, int, int], object] | None = None
    cell_is_free: Callable[[int, int], bool] | None = None
    ability_player: Callable[[int], int] | None = None
    force_knockout: Callable[[], int] | None = None


class EnemyType(Enum):
    BASIC = "basic"
    BOMB = "bomb"
    ULTROS = "ultros"
    TYPHON = "typhon"
    CACTUAR = "cactuar"
    ALLIGATOR = "alligator"
    BULB = "bulb"
    MORBOL = "morbol"
    LANDTRAP = "landtrap"
    CHICHU = "chichu"
    MANDRAGORA = "mandragora"
    DIREMITE = "diremite"
    TONBERRY = "tonberry"
    GORGON = "gorgon"
    ODIN = "odin"


STAGE_ONE_BOSSES = frozenset({EnemyType.ULTROS, EnemyType.TYPHON})
BOSS_HP = 15
BOSS_ATTACK_DAMAGE = 5
LIVE_BOSSES = STAGE_ONE_BOSSES | {EnemyType.CHICHU, EnemyType.ODIN}
STAGE_THREE_ENEMIES = frozenset({EnemyType.MANDRAGORA, EnemyType.DIREMITE,
                                EnemyType.TONBERRY, EnemyType.GORGON, EnemyType.ODIN})
# HP and active-attack damage. All types retain five-HP defense-line contact.
ENEMY_STATS = MappingProxyType({
    EnemyType.BASIC: (5, 0), EnemyType.BOMB: (5, 0),
    EnemyType.ULTROS: (15, 5), EnemyType.TYPHON: (15, 5),
    EnemyType.CACTUAR: (10, 5), EnemyType.ALLIGATOR: (12, 4),
    EnemyType.BULB: (8, 0), EnemyType.MORBOL: (18, 0),
    EnemyType.LANDTRAP: (8, 0), EnemyType.CHICHU: (30, 15),
    EnemyType.MANDRAGORA: (10, 0), EnemyType.DIREMITE: (12, 0),
    EnemyType.TONBERRY: (18, 3), EnemyType.GORGON: (15, 0), EnemyType.ODIN: (50, 40),
})
ENEMY_UNLOCK_STAGE = MappingProxyType({
    kind: 3 if kind in STAGE_THREE_ENEMIES else
    1 if kind in {EnemyType.BASIC, EnemyType.BOMB} | STAGE_ONE_BOSSES else 2
    for kind in EnemyType
})


@dataclass(frozen=True)
class EnemySnapshot:
    enemy_id: int
    enemy_type: EnemyType
    grid_col: int
    grid_row: int
    hp: int
    max_hp: int
    bounds: Bounds
    enraged: bool = False
    odin_phase: int | None = None


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
    enraged: bool = field(default=False, init=False)
    odin_phase: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        validate_id(self.enemy_id)
        if not isinstance(self.enemy_type, EnemyType):
            raise ValueError("Enemy type must be a supported EnemyType")
        cell_bounds(self.grid_col, self.grid_row)
        self.hp = self.max_hp = ENEMY_STATS[self.enemy_type][0]
        self.attack_damage = ENEMY_STATS[self.enemy_type][1]

    @property
    def is_boss(self) -> bool:
        return self.enemy_type in LIVE_BOSSES

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
        before = self.hp
        self.hp = max(0, self.hp - amount)
        if self.enemy_type is EnemyType.TONBERRY and self.hp < before:
            self.enraged = True
        return not self.alive

    def on_turn(self, context: EnemyTurnContext) -> bool:
        """Claim once and execute the ability before standard movement/contact."""
        if not self.active or self.last_action_turn == context.turn_index:
            return False
        self.last_action_turn = context.turn_index
        self.turns_alive += 1
        if self.enemy_type in STAGE_ONE_BOSSES:
            damage = context.attack_player or context.damage_player
            damage(self.attack_damage)
        else:
            from src.enemy_abilities import execute_ability
            execute_ability(self, context)
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
                             self.hp, self.max_hp, self.bounds, self.enraged,
                             self.odin_phase if self.enemy_type is EnemyType.ODIN else None)


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
