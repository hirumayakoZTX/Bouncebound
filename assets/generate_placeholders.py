"""Rebuild the five original pixel-map placeholders locally; no display/audio needed.

Run with the project's Python/Pygame environment. Coordinates and palette below
are the editable source; output PNGs always have a native size of 16 by 16.
"""

from pathlib import Path
import pygame


PALETTE = {
    '.': (0, 0, 0, 0), '#': (24, 36, 55, 255),
    'w': (239, 250, 242, 255), 'c': (124, 221, 232, 255),
    'b': (52, 133, 190, 255), 'd': (41, 68, 118, 255),
    'g': (94, 193, 119, 255), 'l': (168, 227, 131, 255),
    's': (41, 116, 94, 255), 'r': (222, 83, 82, 255),
    'a': (147, 49, 74, 255), 'o': (246, 163, 70, 255),
    'y': (254, 218, 111, 255),
}

PIXEL_MAPS = {
    'images/player/guardian.png': (
        '................',
        '...#........#...',
        '..#c#......#c#..',
        '.#wc#..##..#cw#.',
        '.#cc#.#cc#.#cc#.',
        '..#cb#cccc#bc#..',
        '...#cccccccc#...',
        '..#ccwccccwcc#..',
        '..#cc#cccc#cc#..',
        '...#cccccccc#...',
        '....#bcyycb#....',
        '.....#bccb#.....',
        '.....#b##b#.....',
        '......#..#......',
        '................',
        '................',
    ),
    'images/enemies/slime.png': (
        '................',
        '................',
        '.......##.......',
        '......#ll#......',
        '.....#lllg#.....',
        '....#lggggg#....',
        '...#lggggggg#...',
        '..#lggggggggg#..',
        '..#ggwggggwgg#..',
        '.#ggg#gggg#ggg#.',
        '.#gggggggggggg#.',
        '.#sggggssggggs#.',
        '..#ssssssssss#..',
        '...##########...',
        '................',
        '................',
    ),
    'images/enemies/bomb.png': (
        '..........o.....',
        '.........oy.....',
        '.......##o......',
        '......#dd#......',
        '.....######.....',
        '....#rrrorra#...',
        '...#rrrrrrraa#..',
        '..#rrrrrrrrraa#.',
        '..#rrwrrrrwrra#.',
        '..#rr#rrrr#raa#.',
        '..#rrrrrrrrraa#.',
        '...#rrrrrraaa#..',
        '....#raaaaaa#...',
        '.....#######....',
        '................',
        '................',
    ),
    'images/ui/bp_crystal.png': (
        '................',
        '.......##.......',
        '......#cw#......',
        '.....#ccww#.....',
        '....#bccwww#....',
        '...#bbccwwcc#...',
        '..#bbbcccwccc#..',
        '..#dbbccccccb#..',
        '...#dbbccbbb#...',
        '....#dbbbbb#....',
        '.....#dbbb#.....',
        '......#db#......',
        '.......##.......',
        '................',
        '................',
        '................',
    ),
    'images/projectiles/orb.png': (
        '................',
        '................',
        '......oooo......',
        '....ooyyyyoo....',
        '...oyywwyyyyo...',
        '...oywwyyyyyo...',
        '..oyyyyyyyyyyo..',
        '..oyyyyyyyyyyo..',
        '..oyyyyyyyyyyo..',
        '..oyyyyyyyyyyo..',
        '...oyyyyyyyyo...',
        '...oyyyyyyyyo...',
        '....ooyyyyoo....',
        '......oooo......',
        '................',
        '................',
    ),
}


def generate(root: Path | None = None) -> None:
    root = root if root is not None else Path(__file__).resolve().parent
    for name, rows in PIXEL_MAPS.items():
        if len(rows) != 16 or any(len(row) != 16 for row in rows):
            raise ValueError(f"Pixel map must be 16 by 16: {name}")
        surface = pygame.Surface((16, 16), pygame.SRCALPHA)
        for y, row in enumerate(rows):
            for x, symbol in enumerate(row):
                surface.set_at((x, y), PALETTE[symbol])
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(surface, str(path))


if __name__ == '__main__':
    generate()
