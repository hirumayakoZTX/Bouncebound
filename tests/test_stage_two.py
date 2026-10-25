"""Canonical Stage 2 configuration, campaign, input, lifecycle, and determinism."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT','1')
import pygame
from src.combat import Combat
from src.encounter import Encounter, EncounterOutcome
from src.entities import Enemy, EnemyType
from src.game import Game
from src.renderer import Renderer
from src.spells import SpellId
from src.stage_config import load_stage, parse_stage, StageConfigurationError, STAGE_DIRECTORY
from src.states import GameState, GameOverReason
from src.statuses import StatusKind
from src.world import World, STAGE_ONE, STAGE_TWO, STAGE_THREE
from stage_one_fixtures import perform_action, OPENING_ROWS
from stage_two_fixtures import (definition, playing, enter_stage_two, STAGE_TWO_CLEAR,
                                DEFENSE_AIMS, perform_aimed_shot)


class StageTwoConfigurationTests(unittest.TestCase):
    def test_canonical_configuration_has_six_ordered_waves_and_chichu(self):
        stage=load_stage('stage_02.json')
        self.assertEqual(stage,STAGE_TWO)
        self.assertEqual((stage.stage,stage.final,stage.capacity),(2,False,25))
        self.assertEqual([w.turn for w in stage.waves],[1,4,7,10,13,16])
        self.assertEqual([sum(s.kind!='crystal' for s in w.spawns) for w in stage.waves],[4,4,5,5,5,6])
        self.assertEqual(sum(s.kind=='crystal' for w in stage.waves for s in w.spawns),6)
        self.assertEqual(len(stage.mandatory_ids),30)
        self.assertEqual([(s.entity_id,s.kind,s.col,s.row) for s in stage.boss_wave.spawns],[(300,'chichu',7,3)])
        self.assertTrue(stage.playable)
        with self.assertRaises(FrozenInstanceError):stage.stage=1

    def test_new_ordinary_kinds_are_stage_locked_and_bosses_cannot_be_ordinary(self):
        data=json.loads((STAGE_DIRECTORY/'stage_02.json').read_text())
        for kind in ('cactuar','alligator','bulb','morbol','landtrap'):
            modified=deepcopy(data);modified['stage']=1;modified.pop('boss_wave')
            modified['completion']['mandatory_enemy_ids'].remove(300)
            modified['waves'][0]['spawns'][0]['kind']=kind
            with self.assertRaisesRegex(StageConfigurationError,'unavailable'):parse_stage(modified)
        for kind in ('chichu','odin','unknown'):
            modified=deepcopy(data);modified['waves'][0]['spawns'][0]['kind']=kind
            with self.assertRaises(StageConfigurationError):parse_stage(modified)

    def test_strict_validation_still_rejects_invalid_stage_two_data(self):
        base=json.loads((STAGE_DIRECTORY/'stage_02.json').read_text())
        variants=[]
        for field,value in (('id',True),('kind','gorgon'),('col',14),('row',-1),('hp',8)):
            data=deepcopy(base);data['waves'][0]['spawns'][0][field]=value;variants.append(data)
        data=deepcopy(base);data['waves'][1]['turn']=1;variants.append(data)
        data=deepcopy(base);data['waves'][1]['spawns'][0]['id']=201;variants.append(data)
        data=deepcopy(base);data['completion']['mandatory_enemy_ids'].append(9999);variants.append(data)
        data=deepcopy(base);data['boss_wave']['spawns'][0]['kind']='ultros';variants.append(data)
        for data in variants:
            with self.assertRaises(StageConfigurationError):parse_stage(data)

    def test_chichu_and_odin_live_registration_remain_atomic(self):
        world=World();self.assertEqual(dict(world.stage_definitions),{1:STAGE_ONE,2:STAGE_TWO,3:STAGE_THREE})
        data=json.loads((STAGE_DIRECTORY/'stage_02.json').read_text())
        data['stage']=3;data['completion']['final']=True;data['boss_wave']['spawns'][0]['kind']='odin'
        implemented=parse_stage(data);self.assertTrue(implemented.playable)
        before=deepcopy(vars(world))
        self.assertIsNotNone(World(stages={1:STAGE_ONE,2:STAGE_TWO,3:implemented}))
        with self.assertRaises(ValueError):
            World(stages={1:STAGE_ONE,2:STAGE_TWO,4:implemented})
        self.assertEqual(vars(world),before)

    def test_capacity_occupied_cells_partial_wave_and_retry_preserve_ids(self):
        stage=definition((1,'morbol',0,3),(2,'bulb',1,3),(3,'crystal',1,3),capacity=1)
        combat=Combat();encounter=Encounter(stage)
        self.assertEqual(encounter.spawn_due(1,combat),(1,3))
        self.assertFalse(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(2,combat),())
        combat.apply_damage(1,100)
        blocker=Enemy(10,EnemyType.LANDTRAP,1,3);combat.add_enemy(blocker)
        self.assertEqual(encounter.spawn_due(3,combat),())
        combat.apply_damage(10,100)
        self.assertEqual(encounter.spawn_due(4,combat),(2,))
        self.assertTrue(encounter.all_spawned);self.assertEqual(encounter.spawn_due(5,combat),())
        self.assertEqual(encounter.spawn_history,[1,3,2])

    def test_boss_spawn_requires_all_scripted_defeats_and_safe_boundary(self):
        world=playing(definition((1,'landtrap',7,3),boss=(100,7,5)))
        world.set_aim_target((96,240));world.fire()
        world.advance_time(.25)
        self.assertFalse(world.spawn_waves());self.assertFalse(world.encounter.boss_wave_spawned)
        world.pause();self.assertFalse(world.spawn_waves());world.resume()
        while world.state is GameState.SHOT_ANIMATION:world.advance_time(.25)
        self.assertFalse(world.encounter.boss_wave_spawned)
        world.resolve_turn()
        self.assertTrue(world.encounter.boss_wave_spawned)
        self.assertEqual(world.encounter.spawn_history,[1,100])
        for _ in range(3):self.assertFalse(world.spawn_waves())
        self.assertEqual(world.enemies[100].turns_alive,0)

    def test_mandatory_escape_never_spawns_or_defeats_chichu(self):
        world=playing(definition((1,'landtrap',13,6),boss=(100,7,3)))
        perform_action(world,'shot',0)
        self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertNotIn(100,world.enemies);self.assertEqual(world.combat.death_events,[])

    def test_chichu_death_clears_before_enemy_status_hazard_processing(self):
        world=playing(definition(boss=(100,5,3)))
        # Fire leaves ten HP; Starstorm can finish the boss in its circle.
        perform_action(world,'fire',3)
        self.assertIs(world.state,GameState.PLAYER_AIM)
        world.apply_status(StatusKind.POISON);world.apply_status(StatusKind.DOOM,1)
        world.place_poison_tile(3)
        for effect in world.statuses.snapshot():
            world.statuses.put(replace(effect,applied_turn=world.turn_index-1))
        tile=world.hazards.snapshot()[0]
        world.hazards.put(replace(tile,applied_turn=world.turn_index-1))
        hp=world.hp;before=world.snapshot();events=world.status_events
        perform_action(world,'starstorm',3)
        self.assertIs(world.state,GameState.STAGE_CLEAR)
        self.assertEqual(world.hp,hp);self.assertEqual(world.status_events,events)
        self.assertEqual(world.snapshot().hazards,before.hazards)
        self.assertEqual(world.enemies[100].turns_alive,1)
        history=deepcopy(vars(world))
        for _ in range(3):self.assertFalse(world.resolve_turn())
        self.assertEqual(vars(world),history)


class StageTwoCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init();pygame.font.init();pygame.display.set_mode((960,576))

    @classmethod
    def tearDownClass(cls):pygame.quit()

    def test_complete_two_stage_campaign_through_posted_gameplay_events(self):
        # Preserve the historical two-stage terminal contract explicitly.
        game=Game();game.world=World(stages={1:STAGE_ONE,2:STAGE_TWO});game.running=True
        for _ in range(2):pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        for event in pygame.event.get():game.handle_event(event)
        enter_stage_two(game.world,game=game)
        world=game.world
        self.assertEqual((world.hp,world.mp,world.bp,world.player_row),(100,100,1,3))
        self.assertEqual(world.encounter.definition,STAGE_TWO)
        self.assertEqual(world.snapshot().spawned_waves,1)
        for kind,row in STAGE_TWO_CLEAR:perform_action(world,kind,row,game=game)
        self.assertIs(world.state,GameState.STAGE_CLEAR)
        self.assertEqual((world.stage,world.turn_index,world.hp,world.mp,world.bp),(2,18,95,60,5))
        self.assertEqual(len(world.combat.death_events),30)
        self.assertTrue(world.encounter.boss_wave_spawned)
        self.assertEqual(world.encounter.spawn_history[-1],300)
        self.assertFalse(any(e.escaped for e in world.enemies.values()))
        self.assertFalse(world.can_advance_stage)
        before=deepcopy(vars(world))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertEqual(vars(world),before)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_r))
        self.assertEqual((world.stage,world.state,world.hp,world.mp,world.bp),(1,GameState.STAGE_INTRO,100,100,1))
        self.assertEqual(world.encounter.definition,STAGE_ONE)
        game.handle_event(pygame.event.Event(pygame.QUIT));self.assertFalse(game.running)

    def test_cross_stage_transition_resets_every_owned_system(self):
        world=World();world.start_new_run();world.transition_to(GameState.PLAYER_AIM)
        for row in OPENING_ROWS:perform_action(world,'shot',row)
        for spell,row in (('fire',2),('starstorm',5),('shot',5)):perform_action(world,spell,row)
        old=world.encounter
        committed_ids=tuple(world.spells._committed_actions)
        self.assertTrue(committed_ids)
        world.apply_status(StatusKind.POISON);world.place_poison_tile(3)
        world.reraise_used=True
        self.assertTrue(world.advance_stage())
        self.assertIs(world.state,GameState.STAGE_INTRO)
        self.assertEqual((world.stage,world.turn_index,world.hp,world.mp,world.bp,world.player_row),(2,1,100,100,1,3))
        self.assertEqual(world.enemies,{});self.assertEqual(world.crystals,{})
        self.assertEqual(world.projectiles,[]);self.assertEqual(world.combat.death_events,[])
        self.assertEqual(world.status_events,());self.assertEqual(world.hazards.snapshot(),())
        self.assertEqual(world.statuses.snapshot(),());self.assertFalse(world.reraise_used)
        self.assertEqual(dict(world.spells.cooldowns),{});self.assertIsNone(world.selected_spell)
        self.assertFalse(any(world.spells.has_committed_action(key) for key in committed_ids))
        self.assertIsNone(world._pending_action);self.assertEqual(world._next_action_id,1)
        self.assertEqual(world._next_projectile_id,1)
        self.assertEqual(world._physics.accumulator,0);self.assertEqual(world._spell_remaining,0)
        self.assertIsNot(world.encounter,old);self.assertEqual(world.encounter.spawn_history,[])
        self.assertFalse(world.encounter.boss_wave_spawned)
        world.transition_to(GameState.PLAYER_AIM)
        self.assertEqual(world.encounter.spawn_history,[s.entity_id for s in STAGE_TWO.waves[0].spawns])
        for spell in (SpellId.ESUNA,SpellId.LEVITATION):self.assertTrue(world.select_spell(spell))
        self.assertFalse(world.select_spell(SpellId.METEOR));self.assertEqual(world.spell_feedback,'Spell locked')

    def test_stage_two_hp_defeat_is_reachable_by_normal_missed_shots(self):
        world=playing()
        while world.state is GameState.PLAYER_AIM:
            perform_action(world,'shot',0)
            self.assertLessEqual(world.turn_index,20)
        self.assertIs(world.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual((world.hp,world.turn_index,world.mp,world.bp),(0,12,100,1))
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertTrue(world.restart());self.assertEqual(world.stage,1)

    def test_canonical_defense_failure_retains_hp_after_real_chichu_escape(self):
        world=playing()
        for kind,row in STAGE_TWO_CLEAR[:-1]:perform_action(world,kind,row)
        for row,target in DEFENSE_AIMS:perform_aimed_shot(world,row,target)
        self.assertIs(world.state,GameState.GAME_OVER)
        self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertEqual((world.hp,world.turn_index,world.mp,world.bp),(27,24,60,5))
        self.assertTrue(world.enemies[300].escaped);self.assertEqual(world.enemies[300].hp,20)
        self.assertEqual(len(world.combat.death_events),29)
        self.assertEqual(world.combat.targets(),())
        self.assertTrue(world.restart());self.assertEqual(world.stage,1)

    def test_posted_esuna_and_levitation_resolve_actual_canonical_abilities(self):
        game=Game();game.running=True;world=game.world
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        enter_stage_two(world,game=game)
        for row in (3,0,0):perform_action(world,'shot',row,game=game)
        for row,target in ((0,(480,456)),(2,(480,72)),(6,(96,384))):
            perform_aimed_shot(world,row,target,game=game)
        self.assertIsNotNone(world.statuses.get(StatusKind.BIND))
        self.assertIsNotNone(world.statuses.get(StatusKind.POISON))
        self.assertTrue(world.hazards.snapshot())
        self.assertFalse(world.move_player(1));hp=world.hp
        perform_action(world,'esuna',6,game=game)
        self.assertEqual(world.mp,80);self.assertIsNone(world.statuses.get(StatusKind.BIND))
        self.assertIsNone(world.statuses.get(StatusKind.POISON))
        self.assertEqual(world.hp,hp-5)
        perform_action(world,'levitation',6,game=game)
        self.assertEqual(world.mp,60);self.assertEqual(world.hp,hp-10) # Needles, not tile damage.
        self.assertTrue(any(e.kind.value=='hazard_blocked_by_levitation' for e in world.status_events))

    def test_stage_two_clear_is_deterministic_across_update_schedules(self):
        reference=None
        for schedule in ((1/30,),(1/60,),(1/144,),(.004,.041,.009,.024,.005,.017)):
            world=playing();history=[]
            for kind,row in STAGE_TWO_CLEAR:
                perform_action(world,kind,row,schedule)
                history.append((world.snapshot(),tuple(world.combat.death_events),
                                tuple(world.encounter.spawn_history),tuple(world.spells.cooldowns.items()),
                                tuple((key,asdict(e)) for key,e in sorted(world.enemies.items()))))
            if reference is None:reference=history
            self.assertEqual(history,reference,schedule)
            self.assertIs(world.state,GameState.STAGE_CLEAR)

    def test_stage_two_hp_defeat_is_deterministic_across_update_schedules(self):
        reference=None
        for schedule in ((1/30,),(1/60,),(1/144,),(.004,.041,.009,.024,.005,.017)):
            world=playing();history=[]
            while world.state is GameState.PLAYER_AIM:
                perform_action(world,'shot',0,schedule)
                history.append((world.snapshot(),tuple(world.combat.death_events),
                                tuple(world.encounter.spawn_history)))
            if reference is None:reference=history
            self.assertEqual(history,reference,schedule)
            self.assertIs(world.game_over_reason,GameOverReason.HP_DEPLETED)

    def test_stage_two_defense_failure_is_deterministic_across_update_schedules(self):
        reference=None
        for schedule in ((1/30,),(1/60,),(1/144,),(.004,.041,.009,.024,.005,.017)):
            world=playing();history=[]
            for kind,row in STAGE_TWO_CLEAR[:-1]:
                perform_action(world,kind,row,schedule)
            for row,target in DEFENSE_AIMS:
                perform_aimed_shot(world,row,target,schedule)
                history.append((world.snapshot(),tuple(world.combat.death_events),
                                tuple(world.encounter.spawn_history),
                                tuple((key,asdict(e)) for key,e in sorted(world.enemies.items()))))
            if reference is None:reference=history
            self.assertEqual(history,reference,schedule)
            self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
            self.assertEqual(world.hp,27)

    def test_real_status_abilities_are_deterministic_across_update_schedules(self):
        reference=None
        stage=definition((1,'morbol',0,6),(2,'bulb',0,7),(3,'alligator',1,6))
        for schedule in ((1/30,),(1/60,),(1/144,),(.005,.039,.008,.014)):
            world=playing(stage);history=[]
            for _ in range(7):
                perform_action(world,'shot',0,schedule)
                history.append((world.snapshot(),tuple(world.status_events)))
            if reference is None:reference=history
            self.assertEqual(history,reference,schedule)

    def test_stage_two_renderer_labels_tiles_and_terminal_scenes_are_read_only(self):
        world=playing(definition((1,'cactuar',0,0),(2,'alligator',0,1),(3,'bulb',0,2),
                                 (4,'morbol',0,3),(5,'landtrap',0,4)))
        # Presentation fixture adds Chichu and a tile; no gameplay is driven by drawing.
        world.combat.add_enemy(Enemy(100,EnemyType.CHICHU,0,5));world.place_poison_tile(3)
        renderer=Renderer();screen=pygame.display.get_surface();texts=[]
        class RecordingFont:
            def __init__(self,font):self.font=font
            def render(self,text,*args):texts.append(text);return self.font.render(text,*args)
        renderer.body_font=RecordingFont(renderer.body_font)
        before=deepcopy(vars(world));snapshot=world.snapshot()
        for _ in range(3):renderer.draw(screen,snapshot)
        self.assertEqual(vars(world),before);self.assertEqual(world.snapshot(),snapshot)
        for label in ('C10','A12','Bu8','M18','L8','Ch30'):self.assertIn(label,texts)
        for state in (GameState.STAGE_INTRO,GameState.PAUSED,GameState.STAGE_CLEAR,GameState.GAME_OVER):
            renderer.draw(screen,replace(snapshot,state=state))
        self.assertEqual(vars(world),before)

    def test_restart_after_repeated_stage_two_runs_returns_to_fresh_stage_one(self):
        world=playing()
        for _ in range(2):
            for kind,row in STAGE_TWO_CLEAR:perform_action(world,kind,row)
            world.apply_status(StatusKind.DOOM);world.place_poison_tile(3)
            self.assertTrue(world.restart())
            self.assertEqual((world.stage,world.turn_index,world.hp,world.mp,world.bp),(1,1,100,100,1))
            self.assertEqual(world.status_events,());self.assertEqual(world.hazards.snapshot(),())
            self.assertEqual(world.encounter.spawn_history,[]);self.assertIsNone(world._pending_action)
            world.transition_to(GameState.PLAYER_AIM)
            # This registry's Stage 1 is the deliberately small fixture.
            perform_action(world,'shot',3);self.assertTrue(world.advance_stage())
            world.transition_to(GameState.PLAYER_AIM)


if __name__=='__main__':unittest.main()
