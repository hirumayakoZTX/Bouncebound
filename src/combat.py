"""Damage, FIFO Bomb death chains, and deferred BP collection."""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.collision import Target
from src.constants import BOMB_DAMAGE, MAX_BP
from src.entities import Crystal, Enemy, EnemyType, validate_damage, validate_id
from src.projectile import HitEvent


@dataclass(frozen=True)
class DeathEvent:
    enemy_id: int
    enemy_type: EnemyType
    source: str


@dataclass(frozen=True)
class EnemyDamage:
    """Actual HP loss, including any explosion damage after the direct batch."""

    enemy_id: int
    hp_before: int
    hp_after: int
    direct_damage: int

    @property
    def explosion_damage(self) -> int:
        return self.hp_before - self.hp_after - self.direct_damage


@dataclass(frozen=True)
class BatchDamageResult:
    """Sorted HP changes and newly processed deaths in FIFO resolution order."""

    changes: tuple[EnemyDamage, ...]
    deaths: tuple[DeathEvent, ...]


@dataclass
class Combat:
    enemies: dict[int, Enemy] = field(default_factory=dict)
    crystals: dict[int, Crystal] = field(default_factory=dict)
    pending_bp: int = 0
    death_events: list[DeathEvent] = field(default_factory=list)
    pending_deaths: deque[DeathEvent] = field(default_factory=deque)
    _processed_deaths: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if (any(key != enemy.enemy_id for key, enemy in self.enemies.items())
                or any(key != crystal.crystal_id for key, crystal in self.crystals.items())
                or self.enemies.keys() & self.crystals.keys()):
            raise ValueError("Enemies and crystals require consistent, unique shared IDs")

    def add_enemy(self, enemy: Enemy) -> None:
        self._check_new_id(enemy.enemy_id)
        self.enemies[enemy.enemy_id] = enemy

    def add_crystal(self, crystal: Crystal) -> None:
        self._check_new_id(crystal.crystal_id)
        self.crystals[crystal.crystal_id] = crystal

    def _check_new_id(self, entity_id: int) -> None:
        if entity_id in self.enemies or entity_id in self.crystals:
            raise ValueError("Enemies and crystals must have unique shared IDs")

    def targets(self) -> tuple[Target, ...]:
        targets = [Target(enemy.enemy_id, enemy.bounds)
                   for enemy in self.enemies.values() if enemy.active]
        targets.extend(Target(crystal.crystal_id, crystal.bounds, reflects=False)
                       for crystal in self.crystals.values() if not crystal.collected)
        return tuple(sorted(targets, key=lambda target: target.target_id))

    def _damage(self, enemy_id: int, amount: int, source: str) -> bool:
        enemy = self.enemies.get(enemy_id)
        if enemy is None or not enemy.take_damage(amount):
            return False
        self.pending_deaths.append(DeathEvent(enemy_id, enemy.enemy_type, source))
        return True

    def apply_damage(self, enemy_id: int, amount: int, source: str = "direct") -> bool:
        killed = self._damage(enemy_id, amount, source)
        self.resolve_deaths()
        return killed

    def apply_damage_batch(self, target_ids: Iterable[int], amount: int,
                           source: str = "direct") -> BatchDamageResult:
        """Land every direct hit before draining the shared FIFO death queue.

        Validate the whole request first, deduplicate IDs, and preserve archives.
        Returned changes include nonlethal explosion damage as well as direct hits.
        """
        validate_damage(amount)
        ids = tuple(target_ids)
        for enemy_id in ids:
            validate_id(enemy_id)
        ordered = sorted(set(ids))
        before = {enemy_id: enemy.hp for enemy_id, enemy in self.enemies.items()}
        death_index = len(self.death_events)
        direct: dict[int, int] = {}
        for enemy_id in ordered:
            enemy = self.enemies.get(enemy_id)
            if enemy is None or not enemy.active:
                continue
            hp = enemy.hp
            self._damage(enemy_id, amount, source)
            direct[enemy_id] = hp - enemy.hp
        self.resolve_deaths()
        changes = tuple(EnemyDamage(enemy_id, before[enemy_id], enemy.hp,
                                    direct.get(enemy_id, 0))
                        for enemy_id, enemy in sorted(self.enemies.items())
                        if enemy.hp != before[enemy_id])
        return BatchDamageResult(changes, tuple(self.death_events[death_index:]))

    def resolve_deaths(self) -> None:
        """Drain breadth-first in stable ID order; no recursive damage callbacks."""
        while self.pending_deaths:
            event = self.pending_deaths.popleft()
            if event.enemy_id in self._processed_deaths:
                continue
            self._processed_deaths.add(event.enemy_id)
            self.death_events.append(event)
            if event.enemy_type is not EnemyType.BOMB:
                continue
            bomb = self.enemies[event.enemy_id]
            for enemy in sorted(self.enemies.values(), key=lambda item: item.enemy_id):
                distance = max(abs(enemy.grid_col - bomb.grid_col),
                               abs(enemy.grid_row - bomb.grid_row))
                if enemy.active and distance == 1:
                    self._damage(enemy.enemy_id, BOMB_DAMAGE, "explosion")

    def handle_hit(self, event: HitEvent) -> None:
        """Called once per physics impact, before any later target response."""
        if event.target_id in self.enemies:
            self.apply_damage(event.target_id, event.damage, "projectile")
        elif event.target_id in self.crystals:
            if self.crystals[event.target_id].collect():
                self.pending_bp += 1

    def finish_shot(self, bp: int) -> int:
        self.resolve_deaths()
        result = min(MAX_BP, bp + self.pending_bp)
        self.pending_bp = 0
        return result
