"""Stage 3 configuration, full campaign input, lifecycle, and deterministic outcomes."""

from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT','1')
import pygame
from src.combat import Combat
from src.encounter import Encounter, EncounterOutcome
from src.entities import Enemy,EnemyType
from src.game import Game
from src.renderer import Renderer
from src.stage_config import load_stage, parse_stage, StageConfigurationError, STAGE_DIRECTORY
from src.states import GameState,GameOverReason
from src.statuses import StatusKind,StatusEventKind
from src.world import World,STAGE_ONE,STAGE_TWO,STAGE_THREE
from stage_one_fixtures import perform_action
from stage_two_fixtures import perform_aimed_shot
from stage_three_fixtures import (playing,definition,enter_stage_three,ORDINARY_ROWS,
                                  DEFENDED_CLEAR)


class StageThreeConfigurationTests(unittest.TestCase):
    def test_canonical_seven_wave_configuration_and_iron_regent(self):
        stage=load_stage('stage_03.json');self.assertEqual(stage,STAGE_THREE)
        self.assertEqual((stage.stage,stage.final,stage.capacity),(3,True,25))
        self.assertEqual([w.turn for w in stage.waves],[1,4,7,10,13,16,19])
        self.assertEqual([sum(s.kind!='crystal' for s in w.spawns)for w in stage.waves],[5,5,5,6,6,6,6])
        self.assertEqual(sum(s.kind=='crystal' for w in stage.waves for s in w.spawns),7)
        self.assertEqual(len(stage.mandatory_ids),40)
        self.assertEqual([(s.entity_id,s.kind,s.col,s.row)for s in stage.boss_wave.spawns],[(500,'iron_regent',5,3)])
        self.assertTrue(stage.playable)
        self.assertEqual(dict(World().stage_definitions),{1:STAGE_ONE,2:STAGE_TWO,3:STAGE_THREE})

    def test_stage_three_enemy_availability_and_strict_boss_restrictions(self):
        base=json.loads((STAGE_DIRECTORY/'stage_03.json').read_text())
        for kind in ('rootling','venomcrawler','hooded_stalker','thorn_sentinel'):
            for stage in (1,2):
                data=deepcopy(base);data['stage']=stage;data.pop('boss_wave')
                data['completion']['mandatory_enemy_ids'].remove(500);data['completion']['final']=False
                data['waves'][0]['spawns'][0]['kind']=kind
                with self.assertRaisesRegex(StageConfigurationError,'unavailable'):parse_stage(data)
        for kind in ('inkmaw','galejaw','briarheart','unknown'):
            data=deepcopy(base);data['boss_wave']['spawns'][0]['kind']=kind
            with self.assertRaises(StageConfigurationError):parse_stage(data)
        data=deepcopy(base);data['waves'][0]['spawns'][0]['kind']='iron_regent'
        with self.assertRaises(StageConfigurationError):parse_stage(data)

    def test_invalid_stage_three_ids_cells_order_final_flags_and_fields(self):
        base=json.loads((STAGE_DIRECTORY/'stage_03.json').read_text());variants=[]
        for field,value in (('id',True),('id',0),('col',14),('row',8),('ability',3)):
            data=deepcopy(base);data['waves'][0]['spawns'][0][field]=value;variants.append(data)
        data=deepcopy(base);data['waves'][1]['turn']=1;variants.append(data)
        data=deepcopy(base);data['waves'][1]['spawns'][0]['id']=401;variants.append(data)
        data=deepcopy(base);data['completion']['final']=False;variants.append(data)
        data=deepcopy(base);data['completion']['mandatory_enemy_ids'].remove(500);variants.append(data)
        data=deepcopy(base);data['boss_wave']['spawns'][0]['row']=True;variants.append(data)
        for data in variants:
            with self.assertRaises(StageConfigurationError):parse_stage(data)

    def test_loading_stage_three_is_independent_of_pygame_and_working_directory(self):
        root=STAGE_DIRECTORY.parent.parent
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,PYTHONPATH=str(root))
            result=subprocess.run([sys.executable,'-B','-c',
                "import sys;from src.stage_config import load_stage;"
                "assert load_stage('stage_03.json').stage==3;assert 'pygame' not in sys.modules"],
                cwd=directory,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_stage_three_capacity_and_occupied_cell_deferral_retries_once(self):
        stage=definition((1,'hooded_stalker',0,3),(2,'venomcrawler',1,3),(3,'crystal',1,3),capacity=1)
        combat=Combat();encounter=Encounter(stage)
        self.assertEqual(encounter.spawn_due(1,combat),(1,3));self.assertFalse(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(2,combat),())
        combat.apply_damage(1,100)
        combat.add_enemy(Enemy(8,EnemyType.THORN_SENTINEL,1,3))
        self.assertEqual(encounter.spawn_due(3,combat),())
        combat.apply_damage(8,100)
        self.assertEqual(encounter.spawn_due(4,combat),(2,));self.assertTrue(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(5,combat),());self.assertEqual(encounter.spawn_history,[1,3,2])

    def test_iron_regent_requires_scripted_clear_safe_boundary_and_no_escape(self):
        w=playing(definition((1,'rootling',7,3),boss=(100,5,3)))
        w.set_aim_target((96,240));w.fire();w.advance_time(.25)
        self.assertFalse(w.spawn_waves());self.assertFalse(w.encounter.boss_wave_spawned)
        w.pause();self.assertFalse(w.spawn_waves());w.resume()
        while w.state is GameState.SHOT_ANIMATION:w.advance_time(.25)
        self.assertFalse(w.encounter.boss_wave_spawned);w.resolve_turn()
        self.assertTrue(w.encounter.boss_wave_spawned)
        self.assertEqual(w.enemies[100].turns_alive,0)
        self.assertEqual(w.enemies[100].boss_phase,0)
        self.assertEqual(w.encounter.spawn_history,[1,100])
        self.assertFalse(w.spawn_waves());self.assertEqual(w.encounter.spawn_history,[1,100])
        escaped=playing(definition((1,'rootling',13,6),boss=(100,5,3)))
        perform_action(escaped,'shot',0)
        self.assertIs(escaped.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertNotIn(100,escaped.enemies);self.assertFalse(escaped.encounter.boss_wave_spawned)

    def test_iron_regent_group_respects_capacity_and_conflicting_archived_ids(self):
        stage=definition((1,'rootling',0,3),boss=(100,5,3),capacity=1)
        combat=Combat();encounter=Encounter(stage);encounter.spawn_due(1,combat)
        self.assertIsNone(encounter.outcome(combat));combat.apply_damage(1,100)
        conflict=Enemy(100,EnemyType.THORN_SENTINEL,5,3);conflict.take_damage(100);combat.add_enemy(conflict)
        self.assertEqual(encounter.spawn_due(2,combat),())
        self.assertFalse(encounter.boss_wave_spawned)
        self.assertNotIn(100,encounter.spawn_history)


class StageThreeCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init();pygame.font.init();pygame.display.set_mode((960,576))

    @classmethod
    def tearDownClass(cls):pygame.quit()

    def test_full_three_stage_campaign_victory_results_through_posted_controls(self):
        game=Game();game.running=True
        for _ in range(2):pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        for event in pygame.event.get():game.handle_event(event)
        enter_stage_three(game.world,game=game)
        w=game.world;self.assertEqual((w.stage,w.hp,w.mp,w.bp,w.turn_index),(3,100,100,1,1))
        self.assertTrue(w.select_spell('skyfall'));before=deepcopy(vars(w))
        self.assertFalse(w.advance_stage());self.assertEqual(vars(w),before)
        for k,row in DEFENDED_CLEAR[:-1]:perform_action(w,k,row,game=game)
        self.assertEqual((w.hp,w.mp,w.enemies[500].hp,w.enemies[500].boss_phase),(27,70,30,2))
        target=(96,96+48*3)
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION,pos=target))
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=target))
        for event in pygame.event.get():game.handle_event(event)
        self.assertIs(w.state,GameState.SHOT_ANIMATION)
        self.assertEqual((w.mp,w.enemies[500].hp),(70,30));self.assertFalse(w._pending_action.completed)
        self.assertFalse(w.resolve_turn());self.assertEqual(w.last_resolved_turn,19)
        w.pause();frozen=deepcopy(vars(w))
        for _ in range(4):w.advance_time(100);self.assertFalse(w.resolve_turn())
        self.assertEqual(vars(w),frozen);w.resume()
        while w.state is GameState.SHOT_ANIMATION:w.advance_time(.05)
        self.assertEqual(w.enemies[500].hp,0)
        self.assertIs(w.state,GameState.TURN_RESOLVE);self.assertTrue(w.resolve_turn())
        self.assertIs(w.state,GameState.VICTORY)
        self.assertEqual((w.stage,w.turn_index,w.hp,w.mp,w.bp),(3,20,27,70,5))
        self.assertEqual(len(w.combat.death_events),40)
        self.assertEqual(w.enemies[500].turns_alive,2) # No extra action after the authorized final shot.
        before=deepcopy(vars(w));self.assertFalse(w.resolve_turn())
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,repeat=True))
        self.assertEqual(vars(w),before)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertIs(w.state,GameState.RESULTS)
        self.assertEqual((w.hp,w.mp,w.bp,w.stage,w.turn_index),(27,70,5,3,20))
        self.assertEqual(w.snapshot().score.total,30750)
        self.assertEqual(sum(event.points for event in w.snapshot().score.events),30750)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_r))
        self.assertEqual((w.stage,w.state,w.hp,w.mp,w.bp),(1,GameState.STAGE_INTRO,100,100,1))
        self.assertEqual(w.snapshot().score.total,0)
        self.assertEqual(w.encounter.definition,STAGE_ONE)
        self.assertEqual(w.status_events,());self.assertEqual(w.spells.cooldowns,{})
        game.handle_event(pygame.event.Event(pygame.QUIT));self.assertFalse(game.running)




    def test_skyfall_cost_cooldown_global_targeting_and_duplicate_main_action_guards(self):
        w=playing(definition((1,'hooded_stalker',7,3),(2,'venomcrawler',0,7),(3,'thorn_sentinel',0,6)))
        self.assertTrue(w.select_spell('skyfall'));result=w.cast_selected_spell()
        self.assertTrue(result.valid);self.assertEqual(w.mp,20)
        self.assertEqual([w.enemies[i].hp for i in (1,2,3)],[3,0,0])
        self.assertEqual([e.enemy_id for e in w.combat.death_events],[2,3])
        self.assertEqual(w.spells.next_ready_turn('skyfall'),12)
        self.assertFalse(w.fire());self.assertFalse(w.cast_selected_spell().valid)
        while w.state is GameState.SPELL_ANIMATION:w.advance_time(.25)
        w.resolve_turn();before=deepcopy(vars(w));self.assertFalse(w.cast_selected_spell().valid)
        self.assertEqual(w.mp,20);self.assertEqual(w.turn_index,2)
        # Feedback is the only permitted difference after the rejected cast.
        after=deepcopy(vars(w));after['spell_feedback']=before['spell_feedback'];self.assertEqual(after,before)


    def test_stage_three_fixture_defense_failure_keeps_hp_and_never_spawns_boss_early(self):
        w=playing(definition((445,'basic',13,3)))
        perform_action(w,'shot',0)
        self.assertIs(w.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertEqual((w.hp,w.mp,w.bp,w.turn_index),(95,100,1,1))
        self.assertTrue(w.enemies[445].escaped);self.assertEqual(w.enemies[445].hp,5)
        self.assertEqual(len(w.combat.death_events),0)
        self.assertFalse(w.encounter.boss_wave_spawned);self.assertNotIn(500,w.enemies)
        self.assertTrue(w.restart());self.assertEqual(w.stage,1)





    def test_enter_repeat_cannot_skip_intro_or_results_and_manual_scenes_cannot_claim_turns(self):
        game=Game();game.running=True
        before=deepcopy(vars(game.world))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,repeat=True))
        self.assertEqual(vars(game.world),before)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertIs(game.world.state,GameState.STAGE_INTRO)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,repeat=True))
        self.assertIs(game.world.state,GameState.STAGE_INTRO)
        w=playing(definition((1,'hooded_stalker',0,6)))
        w.transition_to(GameState.SPELL_ANIMATION);w.transition_to(GameState.TURN_RESOLVE)
        before=deepcopy(vars(w));self.assertFalse(w.resolve_turn());self.assertEqual(vars(w),before)

    def test_terminal_outcomes_and_heavy_blow_survival_are_frame_schedule_invariant(self):
        for mode in ('clear','HP','defense'):
            reference=None
            for schedule in ((1/30,),(1/60,),(1/144,),(.004,.041,.009,.024,.005,.017)):
                w=(playing(definition((445,'basic',13,3)))
                   if mode=='defense' else playing())
                history=[]
                if mode == 'clear':
                    for k,row in DEFENDED_CLEAR:
                        perform_action(w,k,row,schedule)
                        history.append((w.snapshot(),tuple(w.combat.death_events),
                                        tuple(w.encounter.spawn_history),
                                        tuple((key,asdict(e)) for key,e in sorted(w.enemies.items()))))
                elif mode=='HP':
                    for _ in range(12):perform_action(w,'shot',0,schedule)
                else:
                    perform_action(w,'shot',0,schedule)
                    history.append((w.snapshot(),tuple(w.combat.death_events)))
                outcome=(w.snapshot(),tuple(w.combat.death_events),tuple(w.encounter.spawn_history),history)
                if reference is None:reference=outcome
                self.assertEqual(outcome,reference,(mode,schedule))


    def test_scoring_creates_no_save_files(self):
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory);w=playing()
                for k,row in DEFENDED_CLEAR:perform_action(w,k,row)
                w.transition_to(GameState.RESULTS)
                self.assertEqual(list(Path(directory).iterdir()),[])
            finally:os.chdir(previous)


if __name__=='__main__':unittest.main()
