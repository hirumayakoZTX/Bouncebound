"""Shared scene and turn-phase names, independent of Pygame."""

from enum import Enum, auto


class GameState(Enum):
    MENU = auto()
    INSTRUCTIONS = auto()
    STAGE_INTRO = auto()
    PLAYER_AIM = auto()
    SHOT_ANIMATION = auto()
    SPELL_ANIMATION = auto()
    TURN_RESOLVE = auto()
    STAGE_CLEAR = auto()
    GAME_OVER = auto()
    VICTORY = auto()
    RESULTS = auto()
    PAUSED = auto()


class GameOverReason(Enum):
    HP_DEPLETED = "Player HP depleted"
    DEFENSE_FAILED = "Defense failed: a required enemy escaped"


ACTIVE_STATES = frozenset({
    GameState.PLAYER_AIM,
    GameState.SHOT_ANIMATION,
    GameState.SPELL_ANIMATION,
    GameState.TURN_RESOLVE,
})


# Presentation navigation only; no turn or combat behavior.
INSTRUCTION_PAGE_COUNT = 2
