"""Replaceable static combat demonstration; no waves or encounter progression."""

from src.combat import Combat
from src.entities import Crystal, Enemy, EnemyType


def create_demo_combat() -> Combat:
    return Combat(
        enemies={
            1: Enemy(1, EnemyType.BASIC, 6, 3),
            2: Enemy(2, EnemyType.BOMB, 9, 3),
            3: Enemy(3, EnemyType.BOMB, 8, 3),
        },
        crystals={4: Crystal(4, 11, 3)},
    )
