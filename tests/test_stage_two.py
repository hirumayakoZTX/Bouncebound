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
    def test_canonical_configuration_has_six_ordered_waves_and_briarheart(self):
        stage=load_stage('stage_02.json')
        self.assertEqual(stage,STAGE_TWO)
        self.assertEqual((stage.stage,stage.final,stage.capacity),(2,False,25))
        self.assertEqual([w.turn for w in stage.waves],[1,4,7,10,13,16])
        self.assertEqual([sum(s.kind!='crystal' for s in w.spawns) for w in stage.waves],[4,4,5,5,5,6])
        self.assertEqual(sum(s.kind=='crystal' for w in stage.waves for s in w.spawns),6)
        self.assertEqual(len(stage.mandatory_ids),30)
        self.assertEqual([(s.entity_id,s.kind,s.col,s.row) for s in stage.boss_wave.spawns],[(300,'briarheart',7,3)])
        self.assertTrue(stage.playable)
        with self.assertRaises(FrozenInstanceError):stage.stage=1

    def test_new_ordinary_kinds_are_stage_locked_and_bosses_cannot_be_ordinary(self):
        data=json.loads((STAGE_DIRECTORY/'stage_02.json').read_text())
        for kind in ('needleling','marshmaw','sporebud','mawroot','snaproot'):
            modified=deepcopy(data);modified['stage']=1;modified.pop('boss_wave')
            modified['completion']['mandatory_enemy_ids'].remove(300)
            modified['waves'][0]['spawns'][0]['kind']=kind
            with self.assertRaisesRegex(StageConfigurationError,'unavailable'):parse_stage(modified)
        for kind in ('briarheart','iron_regent','unknown'):
            modified=deepcopy(data);modified['waves'][0]['spawns'][0]['kind']=kind
            with self.assertRaises(StageConfigurationError):parse_stage(modified)

    def test_strict_validation_still_rejects_invalid_stage_two_data(self):
        base=json.loads((STAGE_DIRECTORY/'stage_02.json').read_text())
        variants=[]
        for field,value in (('id',True),('kind','thorn_sentinel'),('col',14),('row',-1),('hp',8)):
            data=deepcopy(base);data['waves'][0]['spawns'][0][field]=value;variants.append(data)
        data=deepcopy(base);data['waves'][1]['turn']=1;variants.append(data)
        data=deepcopy(base);data['waves'][1]['spawns'][0]['id']=201;variants.append(data)
        data=deepcopy(base);data['completion']['mandatory_enemy_ids'].append(9999);variants.append(data)
        data=deepcopy(base);data['boss_wave']['spawns'][0]['kind']='inkmaw';variants.append(data)
        for data in variants:
            with self.assertRaises(StageConfigurationError):parse_stage(data)

    def test_briarheart_and_iron_regent_registration_remain_atomic(self):
        world=World();self.assertEqual(dict(world.stage_definitions),{1:STAGE_ONE,2:STAGE_TWO,3:STAGE_THREE})
        data=json.loads((STAGE_DIRECTORY/'stage_02.json').read_text())
        data['stage']=3;data['completion']['final']=True;data['boss_wave']['spawns'][0]['kind']='iron_regent'
        implemented=parse_stage(data);self.assertTrue(implemented.playable)
        before=deepcopy(vars(world))
        self.assertIsNotNone(World(stages={1:STAGE_ONE,2:STAGE_TWO,3:implemented}))
        with self.assertRaises(ValueError):
            World(stages={1:STAGE_ONE,2:STAGE_TWO,4:implemented})
        self.assertEqual(vars(world),before)

    def test_capacity_occupied_cells_partial_wave_and_retry_preserve_ids(self):
        stage=definition((1,'mawroot',0,3),(2,'sporebud',1,3),(3,'crystal',1,3),capacity=1)
        combat=Combat();encounter=Encounter(stage)
        self.assertEqual(encounter.spawn_due(1,combat),(1,3))
        self.assertFalse(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(2,combat),())
        combat.apply_damage(1,100)
        blocker=Enemy(10,EnemyType.SNAPROOT,1,3);combat.add_enemy(blocker)
        self.assertEqual(encounter.spawn_due(3,combat),())
        combat.apply_damage(10,100)
        self.assertEqual(encounter.spawn_due(4,combat),(2,))
        self.assertTrue(encounter.all_spawned);self.assertEqual(encounter.spawn_due(5,combat),())
        self.assertEqual(encounter.spawn_history,[1,3,2])

    def test_boss_spawn_requires_all_scripted_defeats_and_safe_boundary(self):
        world=playing(definition((1,'snaproot',7,3),boss=(100,7,5)))
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

    def test_mandatory_escape_never_spawns_or_defeats_briarheart(self):
        world=playing(definition((1,'snaproot',13,6),boss=(100,7,3)))
        perform_action(world,'shot',0)
        self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertNotIn(100,world.enemies);self.assertEqual(world.combat.death_events,[])



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
        self.assertEqual((world.stage,world.turn_index,world.hp,world.mp,world.bp),(2,13,90,100,5))
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


    def test_stage_two_hp_defeat_is_reachable_by_normal_missed_shots(self):
        world=playing()
        while world.state is GameState.PLAYER_AIM:
            perform_action(world,'shot',0)
            self.assertLessEqual(world.turn_index,20)
        self.assertIs(world.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual((world.hp,world.turn_index,world.mp,world.bp),(0,14,100,1))
        self.assertFalse(world.encounter.boss_wave_spawned)
        self.assertTrue(world.restart());self.assertEqual(world.stage,1)

    def test_canonical_defense_failure_retains_hp_after_real_briarheart_escape(self):
        world=playing()
        for kind,row in STAGE_TWO_CLEAR[:-1]:perform_action(world,kind,row)
        for row,target in DEFENSE_AIMS:perform_aimed_shot(world,row,target)
        self.assertIs(world.state,GameState.GAME_OVER)
        self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertEqual((world.hp,world.turn_index,world.mp,world.bp),(22,19,100,5))
        self.assertTrue(world.enemies[300].escaped);self.assertEqual(world.enemies[300].hp,22)
        self.assertEqual(len(world.combat.death_events),29)
        self.assertEqual(world.combat.targets(),())
        self.assertTrue(world.restart());self.assertEqual(world.stage,1)


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
            self.assertEqual(world.hp,22)

    def test_real_status_abilities_are_deterministic_across_update_schedules(self):
        reference=None
        stage=definition((1,'mawroot',0,6),(2,'sporebud',0,7),(3,'marshmaw',1,6))
        for schedule in ((1/30,),(1/60,),(1/144,),(.005,.039,.008,.014)):
            world=playing(stage);history=[]
            for _ in range(7):
                perform_action(world,'shot',0,schedule)
                history.append((world.snapshot(),tuple(world.status_events)))
            if reference is None:reference=history
            self.assertEqual(history,reference,schedule)




if __name__=='__main__':unittest.main()
