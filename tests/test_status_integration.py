"""Real application/World resolution with fixture statuses and no spell hotkeys."""
from copy import deepcopy
from itertools import cycle
import os
import unittest
from unittest.mock import Mock, patch
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame
from src.constants import LOGICAL_SIZE
from src.game import Game
from src.renderer import Renderer
from src.states import GameState
from src.statuses import StatusKind as Kind, StatusState
from src.world import World
from test_status_runtime import finish_turn, world

class StatusIntegrationTests(unittest.TestCase):

    def tearDown(self):
        pygame.quit()





if __name__ == '__main__':
    unittest.main()
