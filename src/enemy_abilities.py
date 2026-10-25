"""Deterministic enemy abilities; World supplies authoritative effect callbacks.

Cadence counts each enemy's surviving phases. Chichu measures column distance
from the player lane (column 14). Newly applied statuses retain their grace phase.
"""

from typing import TYPE_CHECKING

from src.constants import GRID_COLUMNS
from src.statuses import StatusKind

if TYPE_CHECKING:
    from src.entities import Enemy, EnemyTurnContext


def execute_ability(enemy: "Enemy", context: "EnemyTurnContext") -> None:
    kind = enemy.enemy_type.value
    damage = context.ability_player or context.damage_player
    row = context.player_row
    if kind == "cactuar" and row is not None:
        if row != enemy.grid_row:
            next_row = enemy.grid_row + (1 if row > enemy.grid_row else -1)
            if context.cell_is_free is not None and context.cell_is_free(enemy.grid_col, next_row):
                enemy.grid_row = next_row
        if row == enemy.grid_row:
            damage(enemy.attack_damage)
    elif kind == "alligator" and enemy.turns_alive % 3 == 0:
        damage(enemy.attack_damage)
    elif kind in ("bulb", "mandragora") and enemy.turns_alive % 3 == 0:
        if row is not None and context.place_poison_tile is not None:
            context.place_poison_tile(row, 2, enemy.enemy_id)
    elif kind == "morbol" and enemy.turns_alive % 3 == 0:
        if context.apply_status is not None:
            context.apply_status(StatusKind.BIND, 1, enemy.enemy_id)
            context.apply_status(StatusKind.POISON, 3, enemy.enemy_id)
    elif kind == "chichu":
        if GRID_COLUMNS - enemy.grid_col > 3:
            if context.apply_status is not None:
                context.apply_status(StatusKind.POISON, 3, enemy.enemy_id)
        else:
            (context.attack_player or damage)(enemy.attack_damage)
    elif kind == "diremite" and enemy.turns_alive % 2 == 0:
        if context.apply_status is not None:
            context.apply_status(StatusKind.POISON, 2, enemy.enemy_id)
    elif kind == "tonberry" and enemy.enraged:
        damage(enemy.attack_damage)
    elif kind == "gorgon" and enemy.turns_alive % 2 == 0:
        if context.apply_status is not None:
            context.apply_status(StatusKind.DOOM, 5, enemy.enemy_id)
    elif kind == "odin":
        phase = enemy.odin_phase
        if phase == 2 and context.force_knockout is None:
            raise ValueError("Odin EXECUTE requires a forced-knockout resolver")
        enemy.odin_phase = (phase + 1) % 3
        if phase == 2:
            context.force_knockout()
        else:
            (context.attack_player or damage)(enemy.attack_damage)
