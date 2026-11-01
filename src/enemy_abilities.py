"""Deterministic enemy abilities; World supplies authoritative effect callbacks.

Cadence counts each enemy's surviving phases. Seedling measures column distance
from the player lane (column 14). Newly applied Poison retains its grace phase.
"""

from typing import TYPE_CHECKING

from src.constants import GRID_COLUMNS
from src.statuses import StatusKind


IRON_REGENT_HEAVY_DAMAGE = 50

if TYPE_CHECKING:
    from src.entities import Enemy, EnemyTurnContext


def execute_ability(enemy: "Enemy", context: "EnemyTurnContext") -> None:
    kind = enemy.enemy_type.value
    row = context.player_row

    def hit(amount: int, attack: str = "ability") -> int:
        if context.damage_from_enemy is not None:
            return context.damage_from_enemy(enemy.enemy_id, amount, attack)
        callback = context.attack_player if attack in ("slash", "heavy_blow") else None
        return (callback or context.ability_player or context.damage_player)(amount)

    if kind == "needleling" and row is not None:
        if row != enemy.grid_row:
            next_row = enemy.grid_row + (1 if row > enemy.grid_row else -1)
            if context.cell_is_free is not None and context.cell_is_free(enemy.grid_col, next_row):
                enemy.grid_row = next_row
        if row == enemy.grid_row:
            hit(enemy.attack_damage, "needle_attack")
    elif kind == "marshmaw" and enemy.turns_alive % 3 == 0:
        hit(enemy.attack_damage, "scheduled_attack")
    elif kind == "mawroot" and enemy.turns_alive % 3 == 0:
        if context.apply_status is not None:
            context.apply_status(StatusKind.POISON, 3, enemy.enemy_id)
    elif kind == "briarheart":
        if GRID_COLUMNS - enemy.grid_col > 3:
            if context.apply_status is not None:
                context.apply_status(StatusKind.POISON, 3, enemy.enemy_id)
        else:
            hit(enemy.attack_damage, "close_attack")
    elif kind == "venomcrawler" and enemy.turns_alive % 2 == 0:
        if context.apply_status is not None:
            context.apply_status(StatusKind.POISON, 2, enemy.enemy_id)
    elif kind == "hooded_stalker" and enemy.enraged:
        hit(enemy.attack_damage, "retaliation")
    elif kind == "iron_regent":
        phase = enemy.boss_phase
        enemy.boss_phase = (phase + 1) % 3
        if phase == 2:
            hit(IRON_REGENT_HEAVY_DAMAGE, "heavy_blow")
        else:
            hit(enemy.attack_damage, "slash")
