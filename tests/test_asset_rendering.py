"""Sprite placement, procedural fallback, and full campaign rendering regressions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError,replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from src.assets import ASSET_ROOT,AssetManager
from src.entities import Enemy,EnemyType,Crystal
from src.game import Game
from src.renderer import Renderer,PLAYER_SPRITE,ENEMY_SPRITES,CRYSTAL_SPRITE,ORB_SPRITE,SpriteSpec
from src.states import GameState
from src.statuses import StatusKind
from src.world import World
from stage_one_fixtures import OPENING_ROWS
from stage_two_fixtures import STAGE_TWO_CLEAR
from stage_three_fixtures import DEFENDED_CLEAR


class AssetRenderingTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init();pygame.font.init()
        self.screen=pygame.display.set_mode((960,576))
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.empty=Path(self.directory.name)

    def tearDown(self):pygame.quit()

    def renderer(self,root=ASSET_ROOT):
        if root==ASSET_ROOT:return Renderer(AssetManager(root))
        with self.assertLogs('src.assets',level='WARNING'):return Renderer(AssetManager(root))

    def playing(self):
        w=World();w.start_new_run();w.transition_to(GameState.PLAYER_AIM);return w

    def test_original_representative_sprites_load_with_exact_native_dimensions(self):
        manager=AssetManager()
        for spec in (PLAYER_SPRITE,*ENEMY_SPRITES.values(),CRYSTAL_SPRITE,ORB_SPRITE):
            result=manager.load_image(spec.path,native_size=spec.native_size,scale=spec.scale)
            self.assertFalse(result.is_fallback)
            self.assertEqual(result.source_size,(16,16))
            self.assertEqual(result.surface.get_size(),(16*spec.scale,16*spec.scale))

    def test_supplied_pngs_match_their_original_editable_pixel_maps(self):
        import runpy
        source=runpy.run_path(str(ASSET_ROOT/'generate_placeholders.py'))
        source['generate'](self.empty)
        for name in source['PIXEL_MAPS']:
            actual=pygame.image.load(str(ASSET_ROOT/name))
            rebuilt=pygame.image.load(str(self.empty/name))
            self.assertEqual(pygame.image.tobytes(actual,'RGBA'),pygame.image.tobytes(rebuilt,'RGBA'))

    def test_known_sources_decode_once_and_never_reopen_per_frame(self):
        with patch('src.assets.pygame.image.load',wraps=pygame.image.load) as load:
            renderer=Renderer();w=self.playing();count=load.call_count
            self.assertEqual(count,3+len(ENEMY_SPRITES))
            for _ in range(15):renderer.draw(self.screen,w.snapshot())
            self.assertEqual(load.call_count,count)

    def test_missing_sources_warn_and_load_once_then_draw_procedural_each_frame(self):
        with self.assertLogs('src.assets',level='WARNING') as messages:
            with patch('src.assets.pygame.image.load',wraps=pygame.image.load) as load:
                renderer=Renderer(AssetManager(self.empty));w=self.playing()
                for _ in range(10):renderer.draw(self.screen,w.snapshot())
                self.assertEqual(load.call_count,3+len(ENEMY_SPRITES))
        self.assertEqual(len(messages.output),3+len(ENEMY_SPRITES))

    def test_sprite_rects_center_on_unchanged_player_grid_enemy_and_orb_coordinates(self):
        renderer=self.renderer();w=self.playing();before=deepcopy(vars(w))
        for row in range(8):
            rect=renderer._draw_sprite(self.screen,PLAYER_SPRITE,(824,96+48*row))
            self.assertEqual(rect.center,(824,96+48*row));self.assertEqual(rect.size,(48,48))
        for kind in (EnemyType.BASIC,EnemyType.BOMB):
            enemy=Enemy(100,kind,4,3);bounds=enemy.bounds
            rect=renderer._draw_sprite(self.screen,ENEMY_SPRITES[kind],enemy.position)
            self.assertEqual(tuple(rect),(bounds.left,bounds.top,48,48))
            self.assertEqual(enemy.bounds,bounds)
        self.assertEqual(renderer._draw_sprite(self.screen,ORB_SPRITE,(500,240)).center,(500,240))
        self.assertEqual(vars(w),before)

    def test_replacement_sprite_visual_dimensions_do_not_change_collision_bounds(self):
        image=pygame.Surface((32,32),pygame.SRCALPHA);image.fill((200,70,80))
        pygame.image.save(image,str(self.empty/'replacement.png'))
        renderer=self.renderer();renderer.assets=AssetManager(self.empty)
        enemy=Enemy(1,EnemyType.BASIC,4,3);before=deepcopy(vars(enemy))
        rect=renderer._draw_sprite(self.screen,SpriteSpec('replacement.png',(32,32),1),enemy.position)
        self.assertEqual(rect.size,(32,32));self.assertEqual(rect.center,enemy.position)
        self.assertEqual(vars(enemy),before);self.assertEqual(enemy.bounds.right-enemy.bounds.left,48)

    def test_overlapping_crystal_uses_native_integer_scale_inside_cell_corner(self):
        w=World(demo=False);w.start_new_run();w.transition_to(GameState.PLAYER_AIM)
        w.combat.add_enemy(Enemy(1,EnemyType.BASIC,4,3));w.combat.add_crystal(Crystal(2,4,3))
        renderer=self.renderer();before=deepcopy(vars(w))
        with patch.object(renderer,'_draw_sprite',wraps=renderer._draw_sprite) as draw:
            renderer.draw(self.screen,w.snapshot())
        call=next(c for c in draw.call_args_list if c.args[1]==CRYSTAL_SPRITE)
        self.assertEqual(call.kwargs,{'scale':1})
        self.assertEqual(call.args[2],(w.enemies[1].bounds.right-8,w.enemies[1].bounds.top+8))
        self.assertEqual(vars(w),before)

    def test_all_enemy_kinds_render_with_missing_or_partial_sprite_catalog(self):
        w=World(demo=False);w.start_new_run();w.transition_to(GameState.PLAYER_AIM)
        for i,kind in enumerate(EnemyType,1):w.combat.add_enemy(Enemy(i,kind,(i-1)%14,(i-1)//14))
        before=deepcopy(vars(w));snapshot=w.snapshot()
        for root in (ASSET_ROOT,self.empty):
            renderer=self.renderer(root)
            renderer.draw(self.screen,snapshot)
            self.assertEqual(vars(w),before);self.assertEqual(w.snapshot(),snapshot)

    def test_missing_boss_sprites_keep_procedural_identity_without_disk_probes(self):
        # Boss kinds now have art; an empty optional root exercises the same fallback.
        renderer=self.renderer(self.empty);w=World(demo=False);w.start_new_run();w.transition_to(GameState.PLAYER_AIM)
        for i,kind in enumerate((EnemyType.INKMAW,EnemyType.GALEJAW,EnemyType.BRIARHEART,EnemyType.IRON_REGENT),1):
            w.combat.add_enemy(Enemy(i,kind,i,3))
        with patch('src.assets.pygame.image.load',side_effect=AssertionError('Unexpected disk read')):
            renderer.draw(self.screen,w.snapshot())

    def test_hp_labels_and_existing_feedback_remain_available_with_sprites(self):
        renderer=self.renderer();w=self.playing();w.select_spell('mend');w.cast_selected_spell()
        labels=[]
        class Font:
            def __init__(self,font):self.font=font
            def render(self,text,*args):labels.append(text);return self.font.render(text,*args)
        renderer.hud_font=Font(renderer.hud_font);renderer.body_font=Font(renderer.body_font)
        # The real canonical first wave includes both provided enemy sprite kinds.
        with patch.object(renderer.hud, '_text', wraps=renderer.hud._text) as hud_text:
            renderer.draw(self.screen,w.snapshot())
        labels.extend(call.args[1] for call in hud_text.call_args_list)
        self.assertIn('S5',labels);self.assertIn('B10',labels)
        self.assertIn('Cure requires missing HP',labels)
        self.assertTrue(any('HP 100/100' in text for text in labels))
        self.assertIn('[2] Cure',labels);self.assertIn('MP 10',labels)


    def test_flying_paused_spell_and_terminal_scenes_with_missing_assets(self):
        w=self.playing();renderer=self.renderer(self.empty)
        w.set_aim_target((96,240));w.fire();w.advance_time(.1)
        before=deepcopy(vars(w));snapshot=w.snapshot()
        renderer.draw(self.screen,snapshot)
        renderer.draw(self.screen,replace(snapshot,state=GameState.PAUSED,paused_state=GameState.SHOT_ANIMATION))
        for state in (GameState.STAGE_CLEAR,GameState.VICTORY,GameState.RESULTS,GameState.GAME_OVER):
            renderer.draw(self.screen,replace(snapshot,state=state))
        self.assertEqual(vars(w),before)

    def test_explicit_reload_replaces_surfaces_without_stale_renderer_references(self):
        image=pygame.Surface((16,16),pygame.SRCALPHA);image.fill((1,2,3))
        pygame.image.save(image,str(self.empty/'replacement.png'))
        renderer=self.renderer();renderer.assets=AssetManager(self.empty);spec=SpriteSpec('replacement.png')
        renderer._draw_sprite(self.screen,spec,(200,200))
        self.assertEqual(self.screen.get_at((200,200)),(1,2,3,255))
        image.fill((4,5,6));pygame.image.save(image,str(self.empty/'replacement.png'))
        renderer.assets.clear_cache();renderer._draw_sprite(self.screen,spec,(200,200))
        self.assertEqual(self.screen.get_at((200,200)),(4,5,6,255))



if __name__=='__main__':unittest.main()
