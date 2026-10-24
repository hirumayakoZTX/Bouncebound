"""Validated prototype waves and deterministic, model-only spawn scheduling."""

from dataclasses import dataclass, field
from enum import Enum

from src.combat import Combat
from src.entities import Crystal, Enemy, EnemyType, cell_bounds, validate_id


@dataclass(frozen=True)
class Spawn:
    entity_id: int
    kind: str
    col: int
    row: int

    def __post_init__(self) -> None:
        validate_id(self.entity_id)
        if self.kind not in ("basic", "bomb", "crystal"):
            raise ValueError("Prototype spawns support basic, bomb, or crystal")
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
class EncounterDefinition:
    stage: int
    waves: tuple[Wave, ...]

    def __post_init__(self) -> None:
        if type(self.stage) is not int or self.stage != 1:
            raise ValueError("The prototype supports only Stage 1")
        if (not isinstance(self.waves, tuple) or not self.waves
                or any(not isinstance(wave, Wave) for wave in self.waves)):
            raise ValueError("Encounter waves must be a nonempty tuple of Wave entries")
        turns = [wave.turn for wave in self.waves]
        if turns[0] != 1 or any(a >= b for a, b in zip(turns, turns[1:])):
            raise ValueError("Waves must start on Turn 1 and use increasing spawn turns")
        ids = [spawn.entity_id for wave in self.waves for spawn in wave.spawns]
        if len(set(ids)) != len(ids):
            raise ValueError("All encounter entities must have unique stable IDs")
        if not self.mandatory_ids:
            raise ValueError("An encounter requires at least one mandatory enemy")

    @property
    def mandatory_ids(self) -> tuple[int, ...]:
        return tuple(spawn.entity_id for wave in self.waves for spawn in wave.spawns
                     if spawn.kind != "crystal")


class EncounterOutcome(Enum):
    CLEARED = "cleared"
    FAILED = "failed"


@dataclass
class Encounter:
    definition: EncounterDefinition
    spawned_ids: set[int] = field(default_factory=set, init=False)
    spawned_waves: set[int] = field(default_factory=set, init=False)
    spawn_history: list[int] = field(default_factory=list, init=False)

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
        return tuple(spawned)

    @property
    def all_spawned(self) -> bool:
        return len(self.spawned_waves) == len(self.definition.waves)

    def outcome(self, combat: Combat) -> EncounterOutcome | None:
        """Every mandatory enemy must exist and finish; escape is never defeat."""
        if not self.all_spawned:
            return None
        enemies = [combat.enemies.get(enemy_id) for enemy_id in self.definition.mandatory_ids]
        if any(enemy is None or enemy.active for enemy in enemies):
            return None
        if any(enemy.escaped for enemy in enemies):
            return EncounterOutcome.FAILED
        if all(not enemy.alive for enemy in enemies):
            return EncounterOutcome.CLEARED
        return None
