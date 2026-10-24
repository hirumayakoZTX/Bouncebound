"""One deterministic enemy phase, independent of physics and rendering."""

from collections.abc import Iterable

from src.constants import GRID_COLUMNS
from src.entities import Enemy, EnemyTurnContext


def resolve_enemy_phase(enemies: Iterable[Enemy], context: EnemyTurnContext) -> None:
    """Process action then movement/contact in ascending enemy ID order.

    Active enemies block their current cells. A blocked enemy waits; a cell
    vacated by an earlier ID is available immediately. Crystals do not block.
    """
    ordered = tuple(sorted(enemies, key=lambda enemy: enemy.enemy_id))
    for enemy in ordered:
        if context.player_defeated():
            break
        if not enemy.active or enemy.last_action_turn == context.turn_index:
            continue
        if not enemy.on_turn(context):
            continue
        if context.player_defeated():
            break
        if not enemy.active:
            continue
        if enemy.grid_col == GRID_COLUMNS - 1:
            if enemy.escape(context.turn_index):
                context.damage_player(enemy.contact_damage)
            continue
        destination = (enemy.grid_col + 1, enemy.grid_row)
        if not any(other.active and (other.grid_col, other.grid_row) == destination
                   for other in ordered):
            enemy.advance_one_cell()
