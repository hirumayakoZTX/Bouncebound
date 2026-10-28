"""Complete sprite coverage, editable provenance, pixel fidelity, and safe fallback."""

from copy import deepcopy
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame

from src.assets import ASSET_ROOT, AssetManager
from src.entities import Enemy, EnemyType
from src.renderer import ENEMY_SPRITES, Renderer
from src.states import GameState
from src.world import World


NEW_KINDS = (
    EnemyType.ULTROS, EnemyType.TYPHON, EnemyType.CACTUAR, EnemyType.ALLIGATOR,
    EnemyType.BULB, EnemyType.MORBOL, EnemyType.LANDTRAP, EnemyType.CHICHU,
    EnemyType.MANDRAGORA, EnemyType.DIREMITE, EnemyType.TONBERRY,
    EnemyType.GORGON, EnemyType.ODIN,
)


def roster():
    """Detached mixed-stage rendering fixture; never changes campaign encounters."""
    world = World(demo=False)
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    for index, kind in enumerate(NEW_KINDS):
        world.combat.add_enemy(Enemy(index + 1, kind, index % 7, index // 7 + 2))
    return world


class EnemyArtTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((960, 576))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def tearDown(self):
        pygame.quit()

    def test_all_enemy_and_boss_kinds_have_explicit_correct_asset_paths(self):
        self.assertEqual(set(ENEMY_SPRITES), set(EnemyType))
        self.assertEqual(len(NEW_KINDS), 13)
        for kind in NEW_KINDS:
            with self.subTest(kind=kind):
                spec = ENEMY_SPRITES[kind]
                self.assertEqual(spec.path, f'images/enemies/{kind.value}.png')
                self.assertEqual(spec.native_size, (16, 16))
                self.assertEqual(spec.scale, 3)

    def test_original_pngs_have_small_palettes_binary_alpha_and_distinct_silhouettes(self):
        masks = set()
        for kind in NEW_KINDS:
            with self.subTest(kind=kind):
                image = pygame.image.load(str(ASSET_ROOT / ENEMY_SPRITES[kind].path))
                colors = {tuple(image.get_at((x, y))) for x in range(16) for y in range(16)}
                self.assertEqual(image.get_size(), (16, 16))
                self.assertEqual({c[3] for c in colors}, {0, 255})
                self.assertLessEqual(len(colors), 10)
                self.assertIn((24, 36, 55, 255), colors)
                mask = tuple(image.get_at((x, y)).a for y in range(16) for x in range(16))
                self.assertNotIn(mask, masks)
                masks.add(mask)

    def test_editable_maps_reproduce_all_thirteen_pngs_without_display_or_audio(self):
        pygame.quit()
        source = runpy.run_path(str(ASSET_ROOT / 'generate_enemies.py'))
        self.assertEqual(set(source['PIXEL_MAPS']), {kind.value for kind in NEW_KINDS})
        source['generate'](self.root)
        for kind in NEW_KINDS:
            name = ENEMY_SPRITES[kind].path
            actual = pygame.image.load(str(ASSET_ROOT / name))
            rebuilt = pygame.image.load(str(self.root / name))
            self.assertEqual(pygame.image.tobytes(actual, 'RGBA'),
                             pygame.image.tobytes(rebuilt, 'RGBA'))
        self.assertEqual(len(list(self.root.rglob('*.png'))), 13)
        self.assertFalse(pygame.display.get_init())
        self.assertFalse(pygame.mixer.get_init())

    def test_all_sprites_scale_to_exact_three_by_three_pixel_blocks_without_smoothing(self):
        manager = AssetManager()
        with patch('pygame.transform.smoothscale', side_effect=AssertionError('Smoothing pixel art')):
            for kind in NEW_KINDS:
                with self.subTest(kind=kind):
                    spec = ENEMY_SPRITES[kind]
                    source = manager.load_image(spec.path).surface
                    image = manager.load_image(spec.path, scale=3)
                    self.assertFalse(image.is_fallback)
                    self.assertEqual(image.surface.get_size(), (48, 48))
                    for y in range(48):
                        for x in range(48):
                            self.assertEqual(image.surface.get_at((x, y)), source.get_at((x // 3, y // 3)))

    def test_sprite_blits_match_supplied_pixels_and_do_not_change_collision_bounds(self):
        renderer = Renderer()
        for kind in NEW_KINDS:
            for col, row in ((0, 0), (6, 3), (13, 7)):
                with self.subTest(kind=kind, cell=(col, row)):
                    enemy = Enemy(1, kind, col, row)
                    before = deepcopy(vars(enemy))
                    self.screen.fill((11, 22, 33))
                    spec = ENEMY_SPRITES[kind]
                    rect = renderer._draw_sprite(self.screen, spec, enemy.position)
                    self.assertEqual(tuple(rect), (enemy.bounds.left, enemy.bounds.top, 48, 48))
                    expected = pygame.Surface((48, 48))
                    expected.fill((11, 22, 33))
                    expected.blit(renderer.assets.load_image(spec.path, scale=3).surface, (0, 0))
                    self.assertEqual(pygame.image.tobytes(self.screen.subsurface(rect), 'RGBA'),
                                     pygame.image.tobytes(expected, 'RGBA'))
                    self.assertEqual(vars(enemy), before)

    def test_full_renderer_uses_every_sprite_preserves_hp_labels_and_world(self):
        world = roster()
        renderer = Renderer()
        snapshot = world.snapshot()
        before = deepcopy(vars(world))
        with patch.object(renderer, '_draw_sprite', wraps=renderer._draw_sprite) as draw, \
                patch.object(renderer, 'hud_font', wraps=renderer.hud_font) as font:
            for _ in range(3):
                renderer.draw(self.screen, snapshot)
        specs = [call.args[1] for call in draw.call_args_list]
        for kind in NEW_KINDS:
            self.assertEqual(specs.count(ENEMY_SPRITES[kind]), 3)
        self.assertEqual(font.render.call_count, 3 * len(NEW_KINDS))
        self.assertEqual(world.snapshot(), snapshot)
        self.assertEqual(vars(world), before)

    def assert_fallback_roster(self):
        world = roster()
        before = deepcopy(vars(world))
        with self.assertLogs('src.assets', level='WARNING'):
            renderer = Renderer(AssetManager(self.root))
        with patch('src.assets.pygame.image.load', side_effect=AssertionError('Fallback reopened file')):
            renderer.draw(self.screen, world.snapshot())
            for enemy in world.enemies.values():
                spec = ENEMY_SPRITES[enemy.enemy_type]
                self.assertTrue(renderer.assets.load_image(spec.path, scale=3).is_fallback)
                self.assertIsNone(renderer._draw_sprite(self.screen, spec, enemy.position))
                # An unlabelled corner remains the established colored fallback,
                # rather than the empty battlefield or a generic missing texture.
                pixel = self.screen.get_at((enemy.bounds.left + 10, enemy.bounds.top + 8))[:3]
                self.assertNotEqual(pixel, (30, 43, 63))
        self.assertEqual(vars(world), before)

    def test_each_new_kind_keeps_procedural_fallback_when_missing(self):
        self.assert_fallback_roster()

    def test_each_new_kind_keeps_procedural_fallback_when_corrupt(self):
        for kind in NEW_KINDS:
            path = self.root / ENEMY_SPRITES[kind].path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'Not a PNG')
        self.assert_fallback_roster()

    def test_each_new_kind_keeps_procedural_fallback_when_wrong_sized(self):
        for kind in NEW_KINDS:
            path = self.root / ENEMY_SPRITES[kind].path
            path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(pygame.Surface((32, 32)), str(path))
        self.assert_fallback_roster()

    def test_each_new_kind_keeps_procedural_fallback_when_unreadable(self):
        # Inject PermissionError: permission-bit tests are unreliable under elevated runners.
        with patch('src.assets.pygame.image.load', side_effect=PermissionError('Unreadable resource')):
            self.assert_fallback_roster()

    def test_mixed_art_and_fallback_only_replace_the_unavailable_kind(self):
        source = runpy.run_path(str(ASSET_ROOT / 'generate_enemies.py'))
        source['generate'](self.root)
        (self.root / ENEMY_SPRITES[EnemyType.ODIN].path).unlink()
        with self.assertLogs('src.assets', level='WARNING'):
            renderer = Renderer(AssetManager(self.root))
        world = roster()
        before = deepcopy(vars(world))
        renderer.draw(self.screen, world.snapshot())
        for kind in NEW_KINDS:
            self.assertEqual(renderer.assets.load_image(ENEMY_SPRITES[kind].path).is_fallback,
                             kind is EnemyType.ODIN)
        self.assertEqual(vars(world), before)


if __name__ == '__main__':
    unittest.main()
