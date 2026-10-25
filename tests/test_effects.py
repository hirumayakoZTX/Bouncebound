"""Presentation facts, bounded lifetimes, audio safety, and gameplay invariance."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from itertools import cycle
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import pygame
from src.assets import AssetManager, ASSET_ROOT, SILENT_SOUND
from src.combat import Combat, OBSERVATION_LIMIT
from src.constants import PHYSICS_STEP
from src.effects import FeedbackLayer, AudioCues, VisualEffect, MAX_EFFECTS, MAX_TRAIL_POINTS, MAX_LABELS, CUE_FILES
from src.entities import Enemy, EnemyType, Crystal
from src.projectile import Projectile, BounceEvent
from src.renderer import Renderer
from src.game import Game
from src.states import GameState, GameOverReason
from src.statuses import StatusKind, StatusEventKind
from src.world import World
from stage_one_fixtures import OPENING_ROWS, perform_action
from stage_two_fixtures import STAGE_TWO_CLEAR
from stage_three_fixtures import METEOR_CLEAR, playing, definition


class EffectsTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init();pygame.font.init()
        self.screen=pygame.display.set_mode((960,576));self.assets=AssetManager()
        self.world=World(demo=False);self.world.start_new_run();self.world.transition_to(GameState.PLAYER_AIM)
        self.layer=FeedbackLayer();self.update()

    def tearDown(self):pygame.quit()

    def update(self,dt=0,**kwargs):self.layer.update(self.world.snapshot(),dt,self.assets,**kwargs)
    def kinds(self):return [effect.kind for effect in self.layer.last_events]
    def enemy(self,kind=EnemyType.BASIC,identifier=1,col=4,row=3):
        enemy=Enemy(identifier,kind,col,row);self.world.combat.add_enemy(enemy);return enemy
    def fire(self):self.world.set_aim_target((96,240));self.assertTrue(self.world.fire())
    def cast(self,spell):
        self.world.select_spell(spell);result=self.world.cast_selected_spell();self.assertTrue(result.valid)
        self.update();return result

    def test_launch_reports_one_actual_volley_and_no_additional_projectiles(self):
        self.world.bp=5;self.fire();before=deepcopy(vars(self.world));self.update()
        self.assertEqual(self.kinds(),['launch']);self.assertEqual(self.layer.last_events[0].label,'Volley x5')
        self.assertEqual(len(self.world.projectiles),5);self.assertEqual(vars(self.world),before)

    def test_one_wall_bounce_records_one_fact_without_changing_physics(self):
        left=Projectile(1,(104,240),(-520,0));right=deepcopy(left);events=[]
        left.step(PHYSICS_STEP,on_bounce=events.append);right.step(PHYSICS_STEP)
        self.assertEqual(vars(left),vars(right));self.assertEqual(len(events),1)
        self.assertEqual(events[0].normal,(1,0))
        self.world.combat.observe_bounce(events[0]);self.update();self.assertEqual(self.kinds(),['bounce'])

    def test_corner_bounce_is_one_observation_with_both_normal_components(self):
        orb=Projectile(1,(104,80),(-520,-520));events=[];orb.step(PHYSICS_STEP,on_bounce=events.append)
        self.assertEqual(len(events),1);self.assertEqual(events[0].normal,(1,1))
        self.assertEqual(orb.velocity,(520,520))

    def test_enemy_reflection_is_not_misreported_as_a_wall_bounce(self):
        self.enemy();self.fire();self.world.projectiles=[Projectile(1,(343,240),(-520,0))]
        self.world.advance_time(PHYSICS_STEP)
        self.assertEqual([e.kind for e in self.world.combat.observations],['hit','death'])

    def test_substep_hit_and_death_are_captured_even_when_enemy_disappears(self):
        self.enemy();self.fire();self.update();self.world.projectiles=[Projectile(1,(343,240),(-520,0))]
        self.world.advance_time(PHYSICS_STEP);self.assertFalse(self.world.snapshot().enemies)
        self.update();self.assertEqual(self.kinds(),['hit','death'])
        self.assertEqual([e.position for e in self.layer.last_events],[(312,240),(312,240)])

    def test_multiple_same_substep_contacts_preserve_projectile_and_enemy_order(self):
        self.enemy(EnemyType.MORBOL);self.world.bp=3;self.fire();self.update()
        self.world.projectiles=[Projectile(i,(343,240),(-520,0))for i in (3,1,2)]
        hits=self.world.advance_time(PHYSICS_STEP);self.update()
        self.assertEqual([e.projectile_id for e in hits],[1,2,3])
        self.assertEqual(self.kinds(),['hit']*3)
        self.assertEqual([e.label for e in self.layer.last_events],['-5']*3)

    def test_hit_and_death_do_not_replay_on_repeated_updates_or_draws(self):
        self.enemy();self.world.combat.apply_damage(1,5);self.update()
        count=len(self.layer.effects);before=tuple(self.layer.effects)
        for _ in range(10):self.layer.draw(self.screen,self.world.snapshot())
        self.assertEqual(tuple(self.layer.effects),before)
        self.update();self.assertEqual(self.kinds(),[]);self.assertEqual(len(self.layer.effects),count)

    def test_dead_and_escaped_enemies_do_not_generate_further_hit_facts(self):
        enemy=self.enemy(col=13);self.assertTrue(enemy.escape(1))
        self.world.combat.apply_damage(1,10);self.update();self.assertEqual(self.kinds(),[])
        self.assertFalse(self.world.combat.observations)

    def test_zero_damage_does_not_make_a_hit_or_enrage_effect(self):
        self.enemy(EnemyType.TONBERRY);self.update();self.world.combat.apply_damage(1,0);self.update()
        self.assertEqual(self.kinds(),[])

    def test_positive_tonberry_damage_exposes_real_enrage_without_extra_action(self):
        enemy=self.enemy(EnemyType.TONBERRY);self.update();self.world.combat.apply_damage(1,1);self.update()
        self.assertEqual(self.kinds(),['hit','warning']);self.assertEqual(self.layer.last_events[-1].label,'ENRAGED')
        self.assertEqual(enemy.turns_alive,0)

    def test_bomb_chain_observations_follow_actual_fifo_death_order(self):
        for identifier,col,kind in ((1,1,EnemyType.BOMB),(2,2,EnemyType.BOMB),(3,3,EnemyType.BASIC)):
            self.enemy(kind,identifier,col)
        self.world.combat.apply_damage(1,5);self.update()
        self.assertEqual(self.kinds(),['hit','explosion','hit','explosion','hit','death'])
        self.assertEqual([e.entity_id for e in self.layer.last_events if e.kind in ('explosion','death')],[1,2,3])
        self.assertEqual(len(self.world.combat.death_events),3)

    def test_aoe_direct_damage_facts_precede_bomb_death_chains(self):
        for i in (1,2):self.enemy(EnemyType.BOMB,i,i)
        self.world.combat.apply_damage_batch((2,1),10,source='spell:starstorm');self.update()
        self.assertEqual(self.kinds(),['hit','hit','explosion','explosion'])
        self.assertEqual([e.entity_id for e in self.layer.last_events],[1,2,1,2])

    def test_boss_death_is_identified_and_never_retained_as_collision_target(self):
        self.enemy(EnemyType.ODIN);self.world.combat.apply_damage(1,50);self.update()
        self.assertTrue(self.layer.last_events[-1].boss)
        self.assertFalse(self.world.combat.targets())

    def test_crystal_collection_is_a_reward_spark_not_damage_or_death(self):
        self.world.combat.add_crystal(Crystal(1,4,3));self.fire();self.update()
        self.world.projectiles=[Projectile(1,(343,240),(-520,0))]
        self.world.advance_time(PHYSICS_STEP);self.update()
        self.assertEqual(self.kinds(),['crystal'])
        self.assertEqual(self.world.pending_bp,1);self.assertEqual(self.world.bp,1)
        self.assertFalse(self.world.combat.death_events)

    def test_combat_journal_and_effect_pool_are_bounded(self):
        enemy=self.enemy(EnemyType.ODIN);enemy.hp=2000  # Long-lived fixture stresses storage only.
        for _ in range(700):self.world.combat.apply_damage(1,1)
        self.assertEqual(len(self.world.combat.observations),OBSERVATION_LIMIT)
        self.update();self.assertEqual(len(self.layer.effects),MAX_EFFECTS)
        self.assertEqual(len(self.layer.last_events),MAX_EFFECTS)
        self.assertFalse(hasattr(self.layer._previous,'status_events'))

    def test_observations_and_effect_descriptions_are_immutable(self):
        self.enemy();self.world.combat.apply_damage(1,1);self.update()
        with self.assertRaises(FrozenInstanceError):self.world.combat.observations[0].amount=9
        with self.assertRaises(FrozenInstanceError):self.layer.last_events[0].age=10

    def test_lifetimes_expire_only_on_update_and_stalls_are_bounded(self):
        self.fire();self.update();before=tuple(self.layer.effects)
        for _ in range(5):self.layer.draw(self.screen,self.world.snapshot())
        self.assertEqual(tuple(self.layer.effects),before)
        self.update(10000);self.assertAlmostEqual(self.layer.effects[0].age,.25)
        self.update(10000);self.assertFalse(self.layer.effects)

    def test_invalid_presentation_time_is_rejected_without_touching_world(self):
        before=deepcopy(vars(self.world))
        for time in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):self.update(time)
        self.assertEqual(vars(self.world),before)

    def test_trails_are_short_bounded_and_removed_with_authoritative_projectiles(self):
        self.world.bp=5;self.fire();self.update()
        for _ in range(20):self.world.advance_time(.01);self.update(.01)
        self.assertEqual(len(self.layer.trails),5)
        self.assertTrue(all(len(points)<=MAX_TRAIL_POINTS for points in self.layer.trails.values()))
        for _ in range(21):self.world.advance_time(.25);self.update(.25)
        self.assertFalse(self.layer.trails)

    def test_pause_freezes_effects_trails_and_resume_drops_paused_elapsed(self):
        self.fire();self.update();self.world.advance_time(.03);self.update(.03)
        self.world.pause();self.update(10000)
        held=(tuple(self.layer.effects),deepcopy(self.layer.trails),self.world.snapshot())
        for _ in range(4):self.world.advance_time(10000);self.update(10000);self.layer.draw(self.screen,self.world.snapshot())
        self.assertEqual((tuple(self.layer.effects),self.layer.trails,self.world.snapshot()),held)
        self.world.resume();self.update(10000)
        self.assertEqual(tuple(self.layer.effects),held[0])

    def test_epoch_reset_forgets_reused_action_ids_and_old_cues(self):
        self.fire();self.update();self.world.start_new_run();self.world.transition_to(GameState.PLAYER_AIM)
        self.fire();self.update(epoch=1)
        self.assertEqual(self.kinds(),['launch']);self.assertEqual(len(self.layer.effects),1)
        self.assertEqual(self.layer.effects[0].event_id,1)

    def test_initial_attachment_does_not_replay_cached_combat_history(self):
        self.enemy();self.world.combat.apply_damage(1,5)
        layer=FeedbackLayer();layer.update(self.world.snapshot(),0,self.assets)
        self.assertFalse(layer.effects)

    def test_fire_uses_actual_cast_target_position(self):
        self.enemy();result=self.cast('fire');effect=self.layer.last_events[0]
        self.assertEqual(effect.kind,'spell:fire');self.assertEqual(effect.targets,((312,240),))
        self.assertEqual(result.cast.targets.enemy_ids,(1,));self.assertEqual(self.world.mp,70)

    def test_starstorm_uses_authoritative_area_center_and_radius(self):
        self.enemy(col=6);result=self.cast('starstorm');effect=self.layer.last_events[0]
        self.assertEqual((effect.position,effect.radius),(result.cast.targets.center,result.cast.targets.radius))
        self.assertEqual(effect.radius,96)

    def test_meteor_uses_actual_global_targets_without_extra_damage(self):
        self.world=playing(definition((1,'tonberry',4,3),(2,'gorgon',2,2)))
        self.layer=FeedbackLayer();self.update();self.cast('meteor')
        effect=self.layer.last_events[0];self.assertEqual(effect.kind,'spell:meteor')
        self.assertEqual(len(effect.targets),2);self.assertEqual((self.world.enemies[1].hp,self.world.enemies[2].hp),(3,0))
        before=deepcopy(vars(self.world))
        for _ in range(5):self.layer.draw(self.screen,self.world.snapshot())
        self.assertEqual(vars(self.world),before)

    def test_cure_labels_only_actual_healing(self):
        self.world.apply_player_damage(20);self.update();self.cast('cure')
        self.assertEqual(self.layer.last_events[0].label,'+20 HP');self.assertEqual(self.world.hp,100)

    def test_invalid_full_hp_cure_or_fire_does_not_emit_success(self):
        for spell in ('cure','fire'):
            self.world.select_spell(spell);self.assertFalse(self.world.cast_selected_spell().valid)
            self.update();self.assertFalse(self.layer.last_events)
        self.assertEqual(self.world.mp,100)

    def test_esuna_reports_only_actual_removed_status_count(self):
        self.world=playing();self.layer=FeedbackLayer();self.update()
        for kind in (StatusKind.POISON,StatusKind.BIND,StatusKind.DOOM):self.world.apply_status(kind)
        self.update();self.cast('esuna')
        self.assertEqual(self.layer.last_events[0].label,'Cleansed 2')
        self.assertEqual([s.kind for s in self.world.snapshot().statuses],[StatusKind.DOOM])

    def test_cleansing_retires_old_poison_bind_markers_and_keeps_cleanse_readable(self):
        self.world=playing();self.layer=FeedbackLayer();self.update()
        for kind in (StatusKind.POISON,StatusKind.BIND,StatusKind.DOOM):self.world.apply_status(kind)
        self.update();self.cast('esuna')
        labels=[effect.label for effect in self.layer.effects]
        self.assertIn('DOOM',labels);self.assertNotIn('POISON',labels);self.assertNotIn('BIND',labels)
        with patch.object(self.layer,'_label',wraps=self.layer._label)as text:
            self.layer.draw(self.screen,self.world.snapshot())
        self.assertIn('Cleansed 2',[call.args[1]for call in text.call_args_list])

    def test_consumed_revive_grant_does_not_keep_showing_reraise_ready(self):
        self.cast('reraise');self.world.force_player_knockout(source='odin_execute');self.update()
        self.assertFalse(any(effect.kind=='spell:reraise'for effect in self.layer.effects))
        self.assertTrue(any(effect.kind=='revive'for effect in self.layer.effects))

    def test_empty_esuna_does_not_invent_cleansed_effects(self):
        self.world=playing();self.layer=FeedbackLayer();self.update();self.cast('esuna')
        self.assertEqual(self.layer.last_events[0].label,'Cleansed 0')

    def test_ward_and_reraise_grants_are_distinct_from_activation(self):
        for spell in ('ward','reraise'):
            self.world.start_new_run();self.world.transition_to(GameState.PLAYER_AIM)
            self.layer=FeedbackLayer();self.update();self.cast(spell)
            self.assertEqual(self.kinds(),['spell:'+spell]);self.assertNotIn('revive',self.kinds())

    def test_levitation_visual_is_not_ordinary_damage_immunity(self):
        self.world=playing();self.layer=FeedbackLayer();self.update();self.cast('levitation')
        self.assertEqual(self.kinds(),['spell:levitation'])
        self.world.apply_player_damage(5);self.update()
        self.assertEqual(self.kinds(),['damage']);self.assertEqual(self.world.hp,95)

    def test_ward_block_is_not_shown_as_hp_loss(self):
        self.world.apply_status(StatusKind.WARD);self.update();self.world.apply_player_damage(100);self.update()
        self.assertEqual(self.kinds(),['ward_block']);self.assertEqual(self.world.hp,100)

    def test_floor_block_comes_from_real_levitation_event(self):
        self.world.apply_status(StatusKind.LEVITATION)
        self.world.place_poison_tile(3)
        tile=self.world.hazards.snapshot()[0];self.world.hazards.put(replace(tile,applied_turn=1))
        self.world.turn_index=2;self.update()
        self.fire()
        for _ in range(21):self.world.advance_time(.25)
        self.world.resolve_turn();self.update()
        self.assertIn('floor_block',self.kinds());self.assertNotIn('damage',self.kinds())

    def test_real_reraise_occurs_once_before_any_terminal_defeat(self):
        self.world.apply_status(StatusKind.RERAISE);self.update();self.world.apply_player_damage(100);self.update()
        self.assertEqual(self.kinds(),['damage','revive']);self.assertEqual(self.world.hp,50)
        self.assertNotIn('defeat',self.kinds());self.update();self.assertEqual(self.kinds(),[])
        self.world.apply_player_damage(50);self.update();self.assertIn('defeat',self.kinds())

    def test_forced_execute_with_reraise_has_warning_and_one_revival_not_defeat(self):
        self.world.apply_status(StatusKind.RERAISE);self.world.apply_status(StatusKind.WARD);self.update()
        self.world.force_player_knockout(source='odin_execute');self.update()
        self.assertEqual(self.kinds(),['warning','revive']);self.assertEqual(self.world.hp,50)
        self.assertTrue(self.world.statuses.get(StatusKind.WARD))

    def test_poison_and_doom_knockouts_emit_only_authoritative_terminal_feedback(self):
        for source in ('poison','doom'):
            self.world.start_new_run();self.world.transition_to(GameState.PLAYER_AIM)
            self.layer=FeedbackLayer();self.update()
            if source=='poison':self.world.apply_player_damage(100,source='poison')
            else:self.world.force_player_knockout(source='doom')
            self.update();self.assertEqual(self.kinds()[-1],'defeat')
            self.assertEqual(self.world.game_over_reason,GameOverReason.HP_DEPLETED)

    def test_terminal_transition_is_emitted_once_and_results_does_not_replay_victory(self):
        snapshot=replace(self.world.snapshot(),state=GameState.VICTORY)
        self.layer.update(snapshot,0,self.assets);self.assertEqual(self.kinds(),['victory'])
        for _ in range(4):self.layer.update(snapshot,.01,self.assets);self.assertEqual(self.kinds(),[])
        self.layer.update(replace(snapshot,state=GameState.RESULTS),0,self.assets)
        self.assertEqual(self.kinds(),[])

    def test_stage_change_clears_old_effects_and_history(self):
        self.fire();self.update()
        snap=replace(self.world.snapshot(),stage=2,state=GameState.STAGE_INTRO,pending_action=None,
                     projectiles=(),combat_observations=(),status_events=())
        self.layer.update(snap,0,self.assets)
        self.assertFalse(self.layer.effects);self.assertFalse(self.layer.trails);self.assertEqual(self.layer._combat_cursor,0)

    def test_spell_visual_never_outlives_authorized_spell_phase(self):
        self.cast('ward');self.world.advance_time(.45);self.update()
        self.assertFalse(any(e.kind.startswith('spell:')for e in self.layer.effects))
        self.assertIs(self.world.state,GameState.TURN_RESOLVE)

    def test_disabled_effects_leave_gameplay_and_audio_routing_independent(self):
        self.layer.enabled=False;self.enemy();self.fire();self.update()
        self.world.combat.apply_damage(1,5);self.update()
        self.assertFalse(self.layer.effects);self.assertFalse(self.layer.trails)
        self.assertEqual(len(self.world.combat.death_events),1)

    def test_draw_preserves_clip_world_and_effect_ages_and_avoids_hud(self):
        self.cast('ward');before=deepcopy(vars(self.world));effects=tuple(self.layer.effects)
        color=(7,8,9);self.screen.fill(color);clip=self.screen.get_clip()
        self.layer.draw(self.screen,self.world.snapshot())
        self.assertEqual(self.screen.get_clip(),clip);self.assertEqual(vars(self.world),before)
        self.assertEqual(tuple(self.layer.effects),effects)
        for rect in ((0,0,960,64),(0,464,960,112)):
            pixels=pygame.image.tobytes(self.screen.subsurface(rect),'RGB')
            self.assertEqual(pixels,bytes(color)*(rect[2]*rect[3]))

    def test_all_effect_draw_styles_work_at_arena_edges_and_preserve_canvas(self):
        self.layer.effects.clear()
        kinds=['hit','death','explosion','bounce','crystal','launch','damage','warning','revive','ward_block','floor_block']
        kinds+=['spell:'+name for name in ('fire','starstorm','meteor','cure','esuna','levitation','ward','reraise')]
        for i,kind in enumerate(kinds):
            self.layer.effects.append(VisualEffect(i,kind,(103,79),targets=((120,96),),radius=96,label='Test'))
        self.layer.draw(self.screen,self.world.snapshot());self.assertEqual(self.screen.get_size(),(960,576))

    def test_simultaneous_floating_labels_stack_instead_of_overlapping(self):
        for i,kind in enumerate(('damage','warning','revive')):
            self.layer.effects.append(VisualEffect(i,kind,(824,240),label=str(i)))
        with patch.object(self.layer,'_label',wraps=self.layer._label)as text:
            self.layer.draw(self.screen,self.world.snapshot())
        positions=[call.args[2]for call in text.call_args_list]
        self.assertEqual(len(set(positions)),3)
        self.assertEqual([position[1]for position in positions],[198,180,162])

    def test_corner_explosion_marks_only_valid_neighbor_cells_not_player_lane(self):
        self.layer.effects.append(VisualEffect(1,'explosion',(744,432)))
        with patch('src.effects.pygame.draw.rect',wraps=pygame.draw.rect)as rect:
            self.layer.draw(self.screen,self.world.snapshot())
        bounds=[pygame.Rect(call.args[2])for call in rect.call_args_list]
        self.assertEqual(len(bounds),3)
        self.assertTrue(all(pygame.Rect(96,72,672,384).contains(bound)for bound in bounds))

    def test_effect_text_cache_and_fonts_are_bounded_and_reused(self):
        for i in range(90):self.layer._label(self.screen,str(i),(800,200),(255,255,255))
        self.assertEqual(len(self.layer._labels),MAX_LABELS)
        with patch('src.effects.pygame.font.Font',side_effect=AssertionError('Font rebuilt')):
            self.layer._label(self.screen,'89',(800,200),(255,255,255))

    def test_clear_removes_trails_instances_event_cursors_and_cues(self):
        self.fire();self.update();self.layer.clear()
        self.assertFalse(self.layer.effects);self.assertFalse(self.layer.trails)
        self.assertFalse(self.layer.last_events);self.assertFalse(self.layer.audio._sounds)
        self.assertEqual(self.layer._combat_cursor,0)

    def test_improved_aim_preview_tracks_origin_without_predicting_bounces(self):
        renderer=Renderer();self.world.move_player(-1);self.world.set_aim_target((200,192))
        before=deepcopy(vars(self.world))
        with patch('src.renderer.pygame.draw.line',wraps=pygame.draw.line)as line:
            renderer.draw(self.screen,self.world.snapshot())
        self.assertEqual(line.call_count,1)
        self.assertEqual(line.call_args.args[2:4],((808,192),(200,192)))
        self.assertEqual(vars(self.world),before)
        self.world.set_aim_target((900,192))
        with patch('src.renderer.pygame.draw.line',wraps=pygame.draw.line)as line:
            renderer.draw(self.screen,self.world.snapshot());line.assert_not_called()


class AudioFeedbackTests(unittest.TestCase):
    def tearDown(self):pygame.quit()

    def test_audio_disabled_by_default_does_not_load_or_initialize(self):
        assets=AssetManager();router=AudioCues()
        with patch.object(assets,'load_sound',side_effect=AssertionError('Disabled audio loaded')),patch('pygame.mixer.init',side_effect=AssertionError('Audio initialized')):
            for cue in CUE_FILES:router.play(cue,assets)
        self.assertFalse(router._sounds)

    def test_each_cue_is_lazy_cached_and_reset_stops_old_streams(self):
        assets=AssetManager(audio_enabled=True);router=AudioCues();sound=Mock()
        with patch.object(assets,'load_sound',return_value=sound)as load:
            for _ in range(3):router.play('shoot',assets)
            self.assertEqual(load.call_count,1);self.assertEqual(sound.play.call_count,3)
            for cue in CUE_FILES:router.play(cue,assets)
            self.assertEqual(len(router._sounds),8)
            router.clear();self.assertFalse(router._sounds);self.assertTrue(sound.stop.called)

    def test_missing_files_are_silent_without_mixer_initialization(self):
        with tempfile.TemporaryDirectory()as root:
            assets=AssetManager(root,audio_enabled=True);router=AudioCues()
            with self.assertLogs('src.assets',level='WARNING'),patch('pygame.mixer.init',side_effect=AssertionError('Missing file initialized mixer')):
                router.play('shoot',assets);router.play('shoot',assets)
            self.assertTrue(router._sounds['shoot'].is_silent)

    def test_corrupt_audio_and_mixer_failure_are_silent(self):
        with tempfile.TemporaryDirectory()as root:
            path=Path(root)/'sounds/shoot.wav';path.parent.mkdir();path.write_bytes(b'bad wav')
            for fail in (True,False):
                assets=AssetManager(root,audio_enabled=True);router=AudioCues()
                if fail:
                    with self.assertLogs('src.assets',level='WARNING'),patch('pygame.mixer.init',side_effect=pygame.error('No device')):
                        router.play('shoot',assets)
                else:
                    pygame.mixer.init()
                    with self.assertLogs('src.assets',level='WARNING'):router.play('shoot',assets)
                self.assertTrue(router._sounds['shoot'].is_silent);pygame.mixer.quit()

    def test_device_loss_and_playback_error_do_not_end_gameplay(self):
        from src.assets import SafeSound
        underlying=Mock();underlying.play.side_effect=pygame.error('Device lost')
        sound=SafeSound(underlying)
        with patch('pygame.mixer.get_init',return_value=(22050,-16,1)):sound.play()
        with patch('pygame.mixer.get_init',return_value=None):sound.play()
        self.assertEqual(underlying.play.call_count,1)

    def test_generated_wavs_match_editable_source_exactly(self):
        source=runpy.run_path(str(ASSET_ROOT/'generate_cues.py'))
        with tempfile.TemporaryDirectory()as root:
            source['generate'](Path(root))
            for cue in CUE_FILES:
                self.assertEqual((Path(root)/f'{cue}.wav').read_bytes(),(ASSET_ROOT/f'sounds/{cue}.wav').read_bytes())

    def test_opt_in_software_playback_loads_all_small_original_cues(self):
        assets=AssetManager(audio_enabled=True);router=AudioCues()
        for cue in CUE_FILES:router.play(cue,assets)
        self.assertTrue(pygame.mixer.get_init());self.assertEqual(len(assets._sounds),8)
        self.assertFalse(any(sound.is_silent for sound in router._sounds.values()))
        router.clear()

    def test_terminal_cues_do_not_replay_after_repeated_updates_or_results(self):
        layer=FeedbackLayer();assets=AssetManager();world=World()
        layer.update(world.snapshot(),0,assets)
        with patch.object(layer.audio,'play')as play:
            for state in (GameState.VICTORY,GameState.VICTORY,GameState.RESULTS):
                layer.update(replace(world.snapshot(),state=state),0,assets)
            self.assertEqual([call.args[0]for call in play.call_args_list],['victory'])
            layer.clear();layer.update(world.snapshot(),0,assets)
            for _ in range(3):layer.update(replace(world.snapshot(),state=GameState.GAME_OVER),0,assets)
            self.assertEqual([call.args[0]for call in play.call_args_list],['victory','defeat'])

    def test_cli_flags_are_explicit_and_default_silent(self):
        import main
        for args,enabled,audio in (([],True,False),(['--audio'],True,True),(['--no-effects'],False,False)):
            with patch('main.Game')as game:
                main.main(args);game.assert_called_once_with(audio_enabled=audio,effects_enabled=enabled)
                game.return_value.run.assert_called_once_with()

    def test_repeated_draws_and_snapshots_do_not_replay_cues(self):
        pygame.display.init();pygame.font.init();screen=pygame.display.set_mode((960,576))
        w=World(demo=False);w.start_new_run();w.transition_to(GameState.PLAYER_AIM)
        r=Renderer();r.update_feedback(w.snapshot(),0)
        w.set_aim_target((96,240));w.fire()
        with patch.object(r.feedback.audio,'play')as play:
            r.update_feedback(w.snapshot(),0)
            for _ in range(5):r.draw(screen,w.snapshot());r.update_feedback(w.snapshot(),0)
            self.assertEqual([c.args[0]for c in play.call_args_list],['shoot'])


class EffectsCampaignTests(unittest.TestCase):
    def test_complete_campaign_effects_on_off_and_four_schedules_have_identical_gameplay(self):
        pygame.display.init();pygame.font.init();self.addCleanup(pygame.quit)
        screen=pygame.display.set_mode((960,576));reference=None
        routes=(tuple(('shot',r)for r in OPENING_ROWS+(2,5)),STAGE_TWO_CLEAR,METEOR_CLEAR)
        for enabled,schedule in ((True,(1/30,)),(True,(1/60,)),(True,(1/144,)),(True,(.007,.041,.013,.09)),(False,(1/60,))):
            game=Game(effects_enabled=enabled);game.running=True;w=game.world;r=Renderer();r.feedback.enabled=enabled
            history=[];times=cycle(schedule);r.update_feedback(w.snapshot(),0,epoch=game._presentation_epoch)
            def key(value):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=value))
                for event in pygame.event.get():game.handle_event(event)
            key(pygame.K_RETURN)
            for stage,route in enumerate(routes,1):
                r.update_feedback(w.snapshot(),0,epoch=game._presentation_epoch)
                self.assertFalse(r.feedback.effects);key(pygame.K_RETURN)
                for kind,row in route:
                    while w.player_row!=row:key(pygame.K_DOWN if w.player_row<row else pygame.K_UP)
                    if kind=='shot':
                        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(96,96+48*row)))
                        for event in pygame.event.get():game.handle_event(event)
                    else:
                        key(pygame.K_2 if kind=='starstorm'else pygame.K_3);key(pygame.K_SPACE)
                    r.update_feedback(w.snapshot(),0,epoch=game._presentation_epoch)
                    while w.state in (GameState.SHOT_ANIMATION,GameState.SPELL_ANIMATION):
                        dt=next(times);w.advance_time(dt);r.update_feedback(w.snapshot(),dt,epoch=game._presentation_epoch)
                        r.draw(screen,w.snapshot())
                    self.assertTrue(w.resolve_turn());r.update_feedback(w.snapshot(),0,epoch=game._presentation_epoch)
                    snap=w.snapshot();before=deepcopy(vars(w));r.draw(screen,snap)
                    self.assertEqual(vars(w),before)
                    history.append((snap,tuple(w.combat.death_events),tuple(w.encounter.spawn_history)))
                    self.assertLessEqual(len(r.feedback.effects),MAX_EFFECTS)
                if stage<3:key(pygame.K_RETURN)
            self.assertIs(w.state,GameState.VICTORY);key(pygame.K_RETURN)
            r.update_feedback(w.snapshot(),0,epoch=game._presentation_epoch)
            self.assertIs(w.state,GameState.RESULTS)
            self.assertEqual((w.stage,w.turn_index,w.hp,w.mp,w.bp),(3,22,5,20,5))
            if reference is None:reference=history
            self.assertEqual(history,reference,(enabled,schedule))
            key(pygame.K_r);r.update_feedback(w.snapshot(),0,epoch=game._presentation_epoch)
            self.assertFalse(r.feedback.effects);self.assertFalse(r.feedback.trails)
