"""Offline image/sound cache, failure, and exact pixel-scaling contracts."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from src.assets import ASSET_ROOT,AssetManager,SafeSound


class AssetManagerTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.assets=AssetManager(self.root)

    def tearDown(self):pygame.quit()

    def image(self,name='sprite.png',size=(16,16),color=(20,80,120,255)):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        surface=pygame.Surface(size,pygame.SRCALPHA);surface.fill(color)
        pygame.image.save(surface,str(path));return path

    def sound(self,name='cue.wav'):
        path=self.root/name
        with wave.open(str(path),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(22050)
            output.writeframes(bytes(2205*2))
        return path

    def test_default_root_is_derived_from_module_location(self):
        self.assertEqual(ASSET_ROOT,Path(__file__).resolve().parents[1]/'assets')
        self.assertEqual(AssetManager().resolve_path('images/player/guardian.png'),
                         ASSET_ROOT/'images/player/guardian.png')

    def test_loading_from_an_unrelated_working_directory(self):
        before=Path.cwd();self.image()
        with tempfile.TemporaryDirectory() as elsewhere:
            try:
                os.chdir(elsewhere)
                result=self.assets.load_image('sprite.png')
                self.assertFalse(result.is_fallback)
                self.assertFalse(AssetManager().load_image('images/player/guardian.png').is_fallback)
            finally:os.chdir(before)

    def test_relative_paths_cannot_escape_the_root(self):
        for name in ('../outside.png',self.root/'absolute.png','',None,7):
            with self.subTest(name=name),self.assertRaises(ValueError):self.assets.resolve_path(name)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root/'link').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):self.assets.resolve_path('link/sprite.png')

    def test_successful_png_and_bmp_loads_without_a_display(self):
        for name in ('sprite.png','sprite.bmp'):
            self.image(name)
            result=self.assets.load_image(name)
            self.assertFalse(result.is_fallback)
            self.assertEqual(result.source_size,(16,16))
            self.assertEqual(result.surface.get_size(),(16,16))
        self.assertFalse(pygame.display.get_init());self.assertFalse(pygame.mixer.get_init())

    def test_loaded_transparency_survives_display_conversion(self):
        path=self.image();source=pygame.Surface((16,16),pygame.SRCALPHA)
        source.fill((11,22,33,0));source.set_at((1,1),(40,50,60,255));pygame.image.save(source,str(path))
        pygame.display.init();pygame.display.set_mode((960,576))
        result=self.assets.load_image('sprite.png',scale=3)
        self.assertEqual(result.surface.get_at((0,0)).a,0)
        self.assertEqual(result.surface.get_at((3,3)),(40,50,60,255))

    def test_cached_result_reuses_identity_and_one_disk_read(self):
        self.image()
        with patch('src.assets.pygame.image.load',wraps=pygame.image.load) as load:
            first=self.assets.load_image('sprite.png',scale=3)
            self.assertIs(first,self.assets.load_image('sprite.png',scale=3))
            load.assert_called_once()

    def test_different_integer_scales_reuse_the_same_source(self):
        self.image()
        with patch('src.assets.pygame.image.load',wraps=pygame.image.load) as load:
            for scale in (1,2,3,4):
                self.assertEqual(self.assets.load_image('sprite.png',scale=scale).surface.get_size(),
                                 (16*scale,16*scale))
            load.assert_called_once()

    def test_cached_image_does_not_repeat_filesystem_path_resolution(self):
        self.image();self.assets.load_image('sprite.png')
        with patch.object(Path,'resolve',side_effect=AssertionError('Repeated filesystem resolution')):
            for _ in range(10):self.assets.load_image('sprite.png')
        self.assets.clear_cache()
        with patch.object(Path,'resolve',wraps=(self.root/'sprite.png').resolve) as resolve:
            self.assets.load_image('sprite.png');resolve.assert_called_once()

    def test_clear_cache_reloads_changed_image(self):
        self.image(color=(1,2,3,255));old=self.assets.load_image('sprite.png')
        self.image(color=(4,5,6,255))
        self.assertIs(self.assets.load_image('sprite.png'),old)
        self.assets.clear_cache();new=self.assets.load_image('sprite.png')
        self.assertIsNot(old,new);self.assertEqual(new.surface.get_at((0,0)),(4,5,6,255))

    def test_fallback_is_cached_until_explicit_reload(self):
        with self.assertLogs('src.assets',level='WARNING'):
            missing=self.assets.load_image('sprite.png')
        self.image()
        self.assertIs(self.assets.load_image('sprite.png'),missing)
        self.assets.clear_cache()
        self.assertFalse(self.assets.load_image('sprite.png').is_fallback)

    def test_nearest_neighbor_preserves_every_color_block_without_smoothing(self):
        source=pygame.Surface((2,2),pygame.SRCALPHA)
        colors=[(255,0,0,255),(0,255,0,255),(0,0,255,255),(0,0,0,0)]
        for i,color in enumerate(colors):source.set_at((i%2,i//2),color)
        pygame.image.save(source,str(self.root/'pixels.png'))
        with patch('src.assets.pygame.transform.smoothscale',side_effect=AssertionError('smoothing')):
            image=self.assets.load_image('pixels.png',native_size=(2,2),scale=3)
        self.assertEqual(image.surface.get_size(),(6,6))
        for y in range(6):
            for x in range(6):self.assertEqual(image.surface.get_at((x,y)),colors[(y//3)*2+x//3])

    def test_32_pixel_native_source_has_explicit_integer_dimensions(self):
        self.image(size=(32,32))
        result=self.assets.load_image('sprite.png',native_size=(32,32),scale=2)
        self.assertEqual((result.source_size,result.surface.get_size()),((32,32),(64,64)))

    def test_invalid_sizes_and_noninteger_scales_are_clear_caller_errors(self):
        for size in ((0,16),(16,False),(1,),[16,16],None):
            with self.assertRaises(ValueError):self.assets.load_image('sprite.png',native_size=size)
        for scale in (0,-1,1.5,True,None):
            with self.assertRaises(ValueError):self.assets.load_image('sprite.png',scale=scale)

    def test_wrong_source_dimensions_use_safe_declared_size_fallback(self):
        self.image(size=(32,32))
        with self.assertLogs('src.assets',level='WARNING') as messages:
            result=self.assets.load_image('sprite.png',scale=3)
        self.assertTrue(result.is_fallback);self.assertEqual(result.surface.get_size(),(48,48))
        self.assertIn('Expected native size',messages.output[0])

    def test_missing_file_and_empty_directory_use_predictable_placeholder(self):
        with self.assertLogs('src.assets',level='WARNING'):
            result=self.assets.load_image('missing.png',scale=3)
        self.assertTrue(result.is_fallback);self.assertEqual(result.surface.get_size(),(48,48))
        self.assertEqual(result.surface.get_at((0,0)),(225,92,175,255))

    def test_missing_root_also_falls_back(self):
        manager=AssetManager(self.root/'absent')
        with self.assertLogs('src.assets',level='WARNING'):
            self.assertTrue(manager.load_image('sprite.png').is_fallback)

    def test_unreadable_image_returns_cached_fallback(self):
        self.image()
        with patch('src.assets.pygame.image.load',side_effect=PermissionError('Unreadable')) as load:
            with self.assertLogs('src.assets',level='WARNING'):
                first=self.assets.load_image('sprite.png')
                self.assertIs(self.assets.load_image('sprite.png'),first)
            load.assert_called_once()
        self.assertTrue(first.is_fallback)

    def test_corrupt_and_unsupported_image_contents_fall_back(self):
        for name in ('corrupt.png','unsupported.txt'):
            (self.root/name).write_text('This is not an image')
            with self.assertLogs('src.assets',level='WARNING'):
                self.assertTrue(self.assets.load_image(name).is_fallback)

    def test_missing_image_warns_once_across_frames_and_scales(self):
        with self.assertLogs('src.assets',level='WARNING') as messages:
            for _ in range(20):
                for scale in (1,2,3):self.assets.load_image('missing.png',scale=scale)
        self.assertEqual(len(messages.output),1)

    def test_disabled_audio_never_initializes_or_loads_mixer(self):
        self.sound()
        with patch('src.assets.pygame.mixer.init') as init,patch('src.assets.pygame.mixer.Sound') as load:
            handle=self.assets.load_sound('cue.wav')
            self.assertTrue(handle.is_silent);self.assertIsNone(handle.play())
            init.assert_not_called();load.assert_not_called()

    def test_images_and_construction_never_initialize_audio(self):
        self.image()
        with patch('src.assets.pygame.mixer.init') as init:
            manager=AssetManager(self.root,audio_enabled=True)
            manager.load_image('sprite.png');init.assert_not_called()

    def test_missing_sound_does_not_attempt_mixer_initialization(self):
        manager=AssetManager(self.root,audio_enabled=True)
        with patch('src.assets.pygame.mixer.init') as init:
            with self.assertLogs('src.assets',level='WARNING'):
                handle=manager.load_sound('missing.wav')
            self.assertTrue(handle.is_silent);self.assertIs(manager.load_sound('missing.wav'),handle)
            init.assert_not_called()

    def test_unavailable_audio_device_is_silent_and_attempted_only_once(self):
        self.sound();self.sound('another.wav');manager=AssetManager(self.root,audio_enabled=True)
        with patch('src.assets.pygame.mixer.init',side_effect=pygame.error('No device')) as init:
            with self.assertLogs('src.assets',level='WARNING'):
                first=manager.load_sound('cue.wav');second=manager.load_sound('another.wav')
            self.assertTrue(first.is_silent);self.assertTrue(second.is_silent);init.assert_called_once()

    def test_unavailable_mixer_module_is_silent_without_affecting_images(self):
        self.sound();self.sound('another.wav');self.image()
        manager=AssetManager(self.root,audio_enabled=True)
        with patch('src.assets.pygame.mixer.get_init',side_effect=NotImplementedError('No SDL_mixer')) as ready:
            with self.assertLogs('src.assets',level='WARNING'):
                self.assertTrue(manager.load_sound('cue.wav').is_silent)
                self.assertTrue(manager.load_sound('another.wav').is_silent)
            ready.assert_called_once()
            self.assertFalse(manager.load_image('sprite.png').is_fallback)

    def test_asset_import_does_not_require_mixer_symbols(self):
        code=("import pygame;"
              "Missing=type('Missing',(),{'__getattr__':lambda self,name: "
              "(_ for _ in ()).throw(NotImplementedError('No SDL_mixer'))});"
              "pygame.mixer=Missing();import src.assets;"
              "assert src.assets.SafeSound().is_silent;"
              "src.assets.AssetManager()")
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_explicit_cache_clear_allows_audio_retry(self):
        self.sound();manager=AssetManager(self.root,audio_enabled=True)
        with patch('src.assets.pygame.mixer.init',side_effect=pygame.error('No device')) as init:
            with self.assertLogs('src.assets',level='WARNING'):
                manager.load_sound('cue.wav');manager.clear_cache();manager.load_sound('cue.wav')
            self.assertEqual(init.call_count,2)

    def test_valid_sound_loads_lazily_and_caches_with_dummy_audio(self):
        self.sound();manager=AssetManager(self.root,audio_enabled=True)
        self.assertFalse(pygame.mixer.get_init())
        handle=manager.load_sound('cue.wav')
        self.assertFalse(handle.is_silent);self.assertIs(manager.load_sound('cue.wav'),handle)
        self.assertIsNotNone(pygame.mixer.get_init())
        handle.set_volume(.2);handle.play();handle.stop();handle.fadeout(1)

    def test_corrupt_sound_is_cached_silent_fallback(self):
        (self.root/'bad.wav').write_text('not a wave')
        manager=AssetManager(self.root,audio_enabled=True)
        with self.assertLogs('src.assets',level='WARNING'):
            handle=manager.load_sound('bad.wav')
        self.assertTrue(handle.is_silent);self.assertIs(manager.load_sound('bad.wav'),handle)

    def test_sound_read_error_is_nonfatal(self):
        self.sound();manager=AssetManager(self.root,audio_enabled=True)
        with patch('src.assets.pygame.mixer.Sound',side_effect=OSError('Unreadable')):
            with self.assertLogs('src.assets',level='WARNING'):
                self.assertTrue(manager.load_sound('cue.wav').is_silent)

    def test_noop_sound_and_device_loss_are_safe(self):
        silent=SafeSound();self.assertIsNone(silent.play());silent.stop();silent.set_volume(1);silent.fadeout(1)
        self.sound();handle=AssetManager(self.root,audio_enabled=True).load_sound('cue.wav')
        pygame.mixer.quit()
        self.assertTrue(handle.is_silent);self.assertIsNone(handle.play());handle.stop()

    def test_post_load_playback_device_error_cannot_escape(self):
        self.sound();manager=AssetManager(self.root,audio_enabled=True);pygame.mixer.init()
        with patch('src.assets.pygame.mixer.Sound') as sound:
            sound.return_value.play.side_effect=pygame.error('Device lost')
            handle=manager.load_sound('cue.wav')
            self.assertIsNone(handle.play())

    def test_importing_assets_and_models_initializes_no_subsystems(self):
        result=subprocess.run([sys.executable,'-B','-c',
            'import pygame;from src.assets import AssetManager;AssetManager();'
            'assert not pygame.display.get_init();assert not pygame.font.get_init();'
            'assert not pygame.mixer.get_init()'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
