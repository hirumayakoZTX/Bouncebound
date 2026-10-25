"""Explicit historical encounter selection for pre-canonical gameplay regressions."""

from config.prototype import PROTOTYPE
from src.game import Game
from src.world import World


def prototype_game() -> Game:
    game = Game()
    game.world = World(encounter=PROTOTYPE)
    return game
