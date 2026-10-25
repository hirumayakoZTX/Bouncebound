"""Immutable encounter definitions and deterministic, model-only scheduling."""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from src.combat import Combat
from src.entities import Crystal, Enemy, EnemyType, ENEMY_UNLOCK_STAGE, LIVE_BOSSES, cell_bounds, validate_id
from src.constants import GRID_COLUMNS, GRID_ROWS


BOSS_STAGES = MappingProxyType({"ultros": 1, "typhon": 1, "chichu": 2, "odin": 3})


@dataclass(frozen=True)
class Spawn:
    entity_id: int
    kind: str
    col: int
    row: int

    def __post_init__(self) -> None:
        validate_id(self.entity_id)
        kinds = {kind.value for kind in EnemyType if kind not in LIVE_BOSSES} | {"crystal"}
        if type(self.kind) is not str or self.kind not in kinds:
            raise ValueError("Spawn kind must be a supported ordinary enemy or crystal")
        cell_bounds(self.col, self.row)


@dataclass(frozen=True)
class Wave:
    turn: int
    spawns: tuple[Spawn, ...]

    def __post_init__(self) -> None:
        if type(self.turn) is not int or self.turn < 1:
            raise ValueError("Wave turn must be a positive integer")
        if (not isinstance(self.spawns, tuple) or not self.spawns
                or any(not isinstance(spawn, Spawn) for spawn in self.spawns)):
            raise ValueError("Wave spawns must be a nonempty tuple of Spawn entries")
        enemy_cells = [(spawn.col, spawn.row) for spawn in self.spawns
                       if spawn.kind != "crystal"]
        if len(set(enemy_cells)) != len(enemy_cells):
            raise ValueError("Enemies in one wave must use distinct grid cells")


@dataclass(frozen=True)
class BossSpawn:
    """Validated boss placement; unsupported future kinds remain reservations."""

    entity_id: int
    kind: str
    col: int
    row: int

    def __post_init__(self) -> None:
        validate_id(self.entity_id)
        if type(self.kind) is not str or self.kind not in BOSS_STAGES:
            raise ValueError("Boss kind must be ultros, typhon, chichu, or odin")
        cell_bounds(self.col, self.row)


@dataclass(frozen=True)
class BossWave:
    when: str
    spawns: tuple[BossSpawn, ...]
    escape_policy: str = "contact_and_fail"

    def __post_init__(self) -> None:
        if self.escape_policy != "contact_and_fail":
            raise ValueError("Boss escape policy must be contact_and_fail")
        if self.when != "after_scripted_waves_cleared":
            raise ValueError("Boss trigger must be after_scripted_waves_cleared")
        if (not isinstance(self.spawns, tuple) or not self.spawns
                or any(not isinstance(spawn, BossSpawn) for spawn in self.spawns)):
            raise ValueError("Boss wave requires a nonempty tuple of BossSpawn entries")
        cells = [(spawn.col, spawn.row) for spawn in self.spawns]
        if len(set(cells)) != len(cells):
            raise ValueError("Boss wave cannot contain duplicate enemy cells")


@dataclass(frozen=True)
class EncounterDefinition:
    stage: int
    waves: tuple[Wave, ...]
    mandatory_enemy_ids: tuple[int, ...] | None = None
    capacity: int | None = None
    boss_wave: BossWave | None = None
    final: bool = False

    def __post_init__(self) -> None:
        if type(self.stage) is not int or not 1 <= self.stage <= 3:
            raise ValueError("Stage must be an integer from 1 to 3")
        if type(self.final) is not bool or self.final != (self.stage == 3):
            raise ValueError("Only Stage 3 is final, and Stage 3 must be marked final")
        if (self.capacity is not None and (type(self.capacity) is not int
                or not 1 <= self.capacity <= GRID_COLUMNS * GRID_ROWS)):
            raise ValueError("Enemy capacity must be an integer from 1 to 112")
        if self.boss_wave is not None and not isinstance(self.boss_wave, BossWave):
            raise ValueError("Boss wave must be a BossWave record")
        if (not isinstance(self.waves, tuple) or not self.waves
                or any(not isinstance(wave, Wave) for wave in self.waves)):
            raise ValueError("Encounter waves must be a nonempty tuple of Wave entries")
        turns = [wave.turn for wave in self.waves]
        if turns[0] != 1 or any(a >= b for a, b in zip(turns, turns[1:])):
            raise ValueError("Waves must start on Turn 1 and use increasing spawn turns")
        if any(ENEMY_UNLOCK_STAGE[EnemyType(spawn.kind)] > self.stage
               for wave in self.waves for spawn in wave.spawns if spawn.kind != "crystal"):
            raise ValueError("Enemy kind is unavailable in the configured stage")
        boss_spawns = self.boss_wave.spawns if self.boss_wave else ()
        if any(BOSS_STAGES[spawn.kind] != self.stage for spawn in boss_spawns):
            raise ValueError("Boss kinds must belong to the configured stage")
        if self.capacity is not None and len(boss_spawns) > self.capacity:
            raise ValueError("Boss wave exceeds enemy capacity")
        ids = [spawn.entity_id for wave in self.waves for spawn in wave.spawns]
        ids.extend(spawn.entity_id for spawn in boss_spawns)
        if len(set(ids)) != len(ids):
            raise ValueError("All encounter entities must have unique stable IDs")
        if self.mandatory_enemy_ids is not None:
            if not isinstance(self.mandatory_enemy_ids, tuple):
                raise ValueError("Mandatory enemy IDs must be a tuple")
            for enemy_id in self.mandatory_enemy_ids:
                validate_id(enemy_id)
            if len(set(self.mandatory_enemy_ids)) != len(self.mandatory_enemy_ids):
                raise ValueError("Mandatory enemy IDs must be unique")
        if not self.mandatory_ids:
            raise ValueError("An encounter requires at least one mandatory enemy")
        enemy_ids = {spawn.entity_id for wave in self.waves for spawn in wave.spawns
                     if spawn.kind != "crystal"} | {spawn.entity_id for spawn in boss_spawns}
        if not set(self.mandatory_ids) <= enemy_ids:
            raise ValueError("Mandatory IDs must reference configured enemies, never crystals")
        if not {spawn.entity_id for spawn in boss_spawns} <= set(self.mandatory_ids):
            raise ValueError("All reserved bosses must be mandatory")

    @property
    def mandatory_ids(self) -> tuple[int, ...]:
        if self.mandatory_enemy_ids is not None:
            return self.mandatory_enemy_ids
        scripted = tuple(spawn.entity_id for wave in self.waves for spawn in wave.spawns
                         if spawn.kind != "crystal")
        return scripted + (tuple(spawn.entity_id for spawn in self.boss_wave.spawns)
                           if self.boss_wave else ())

    @property
    def playable(self) -> bool:
        return (self.boss_wave is None or all(
            spawn.kind in {kind.value for kind in LIVE_BOSSES}
            for spawn in self.boss_wave.spawns))


class EncounterOutcome(Enum):
    CLEARED = "cleared"
    FAILED = "failed"


@dataclass
class Encounter:
    definition: EncounterDefinition
    spawned_ids: set[int] = field(default_factory=set, init=False)
    spawned_waves: set[int] = field(default_factory=set, init=False)
    spawn_history: list[int] = field(default_factory=list, init=False)
    boss_wave_spawned: bool = field(default=False, init=False)

    def spawn_due(self, turn: int, combat: Combat) -> tuple[int, ...]:
        """Retry due entries in wave/config order; occupied enemy cells wait.

        The World calls this only at safe turn boundaries. Crystals are
        nonblocking collectibles and may share cells with enemies.
        """
        spawned = []
        for index, wave in enumerate(self.definition.waves):
            if wave.turn > turn:
                break
            for spawn in wave.spawns:
                if spawn.entity_id in self.spawned_ids:
                    continue
                if spawn.kind == "crystal":
                    combat.add_crystal(Crystal(spawn.entity_id, spawn.col, spawn.row))
                else:
                    if (self.definition.capacity is not None
                            and sum(enemy.active for enemy in combat.enemies.values())
                            >= self.definition.capacity):
                        continue
                    if any(enemy.active and (enemy.grid_col, enemy.grid_row)
                           == (spawn.col, spawn.row) for enemy in combat.enemies.values()):
                        continue
                    combat.add_enemy(Enemy(spawn.entity_id, EnemyType(spawn.kind),
                                           spawn.col, spawn.row))
                self.spawned_ids.add(spawn.entity_id)
                self.spawn_history.append(spawn.entity_id)
                spawned.append(spawn.entity_id)
            if all(spawn.entity_id in self.spawned_ids for spawn in wave.spawns):
                self.spawned_waves.add(index)
        spawned.extend(self.spawn_boss_wave(combat))
        return tuple(spawned)

    def spawn_boss_wave(self, combat: Combat) -> tuple[int, ...]:
        """Preflight and publish the complete implemented boss group atomically.

        World calls the scheduler only at safe boundaries. A group cannot spawn
        partially, overwrite occupants, exceed capacity, or reuse archived IDs.
        """
        if (not self.definition.playable or combat.pending_deaths or combat.pending_bp
                or not self.boss_wave_ready(combat)):
            return ()
        spawns = self.definition.boss_wave.spawns
        capacity = self.definition.capacity
        active = tuple(enemy for enemy in combat.enemies.values() if enemy.active)
        if capacity is not None and len(active) + len(spawns) > capacity:
            return ()
        if any((enemy.grid_col, enemy.grid_row) == (spawn.col, spawn.row)
               for spawn in spawns for enemy in active):
            return ()
        if any(spawn.entity_id in combat.enemies or spawn.entity_id in combat.crystals
               for spawn in spawns):
            return ()
        enemies = tuple(Enemy(spawn.entity_id, EnemyType(spawn.kind), spawn.col, spawn.row)
                        for spawn in spawns)
        for enemy in enemies:
            combat.add_enemy(enemy)
            self.spawned_ids.add(enemy.enemy_id)
            self.spawn_history.append(enemy.enemy_id)
        self.boss_wave_spawned = True
        return tuple(enemy.enemy_id for enemy in enemies)

    @property
    def all_spawned(self) -> bool:
        return len(self.spawned_waves) == len(self.definition.waves)

    def boss_wave_ready(self, combat: Combat) -> bool:
        """Ready once mandatory scripted foes are defeated and no ordinary foes are active."""
        return (not self.boss_wave_spawned and self.definition.boss_wave is not None
                and self.all_spawned
                and not any(enemy.active for enemy in combat.enemies.values())
                and all((enemy := combat.enemies.get(spawn.entity_id)) is not None
                        and not enemy.active
                        and (spawn.entity_id not in self.definition.mandatory_ids or not enemy.alive)
                        for wave in self.definition.waves for spawn in wave.spawns
                        if spawn.kind != "crystal"))

    def outcome(self, combat: Combat) -> EncounterOutcome | None:
        """Mandatory escapes fail; all ordinary enemies must leave active play."""
        if not self.all_spawned or any(enemy.active for enemy in combat.enemies.values()):
            return None
        enemies = [combat.enemies.get(enemy_id) for enemy_id in self.definition.mandatory_ids]
        if any(enemy is not None and enemy.escaped for enemy in enemies):
            return EncounterOutcome.FAILED
        if self.definition.boss_wave is not None and not self.boss_wave_spawned:
            return None  # Empty scripted waves do not skip the required boss group.
        if any(enemy is None for enemy in enemies):
            return None
        if all(not enemy.alive for enemy in enemies):
            return EncounterOutcome.CLEARED
        return None
