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
                                  METEOR_CLEAR,EXECUTE_CLEAR,DEFENSE_ENDING)


class StageThreeConfigurationTests(unittest.TestCase):
    def test_canonical_seven_wave_configuration_and_odin(self):
        stage=load_stage('stage_03.json');self.assertEqual(stage,STAGE_THREE)
        self.assertEqual((stage.stage,stage.final,stage.capacity),(3,True,25))
        self.assertEqual([w.turn for w in stage.waves],[1,4,7,10,13,16,19])
        self.assertEqual([sum(s.kind!='crystal' for s in w.spawns)for w in stage.waves],[5,5,5,6,6,6,6])
        self.assertEqual(sum(s.kind=='crystal' for w in stage.waves for s in w.spawns),7)
        self.assertEqual(len(stage.mandatory_ids),40)
        self.assertEqual([(s.entity_id,s.kind,s.col,s.row)for s in stage.boss_wave.spawns],[(500,'odin',5,3)])
        self.assertTrue(stage.playable)
        self.assertEqual(dict(World().stage_definitions),{1:STAGE_ONE,2:STAGE_TWO,3:STAGE_THREE})

    def test_stage_three_enemy_availability_and_strict_boss_restrictions(self):
        base=json.loads((STAGE_DIRECTORY/'stage_03.json').read_text())
        for kind in ('mandragora','diremite','tonberry','gorgon'):
            for stage in (1,2):
                data=deepcopy(base);data['stage']=stage;data.pop('boss_wave')
                data['completion']['mandatory_enemy_ids'].remove(500);data['completion']['final']=False
                data['waves'][0]['spawns'][0]['kind']=kind
                with self.assertRaisesRegex(StageConfigurationError,'unavailable'):parse_stage(data)
        for kind in ('ultros','typhon','chichu','unknown'):
            data=deepcopy(base);data['boss_wave']['spawns'][0]['kind']=kind
            with self.assertRaises(StageConfigurationError):parse_stage(data)
        data=deepcopy(base);data['waves'][0]['spawns'][0]['kind']='odin'
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
        stage=definition((1,'tonberry',0,3),(2,'diremite',1,3),(3,'crystal',1,3),capacity=1)
        combat=Combat();encounter=Encounter(stage)
        self.assertEqual(encounter.spawn_due(1,combat),(1,3));self.assertFalse(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(2,combat),())
        combat.apply_damage(1,100)
        combat.add_enemy(Enemy(8,EnemyType.GORGON,1,3))
        self.assertEqual(encounter.spawn_due(3,combat),())
        combat.apply_damage(8,100)
        self.assertEqual(encounter.spawn_due(4,combat),(2,));self.assertTrue(encounter.all_spawned)
        self.assertEqual(encounter.spawn_due(5,combat),());self.assertEqual(encounter.spawn_history,[1,3,2])

    def test_odin_requires_scripted_clear_safe_boundary_and_no_escape(self):
        w=playing(definition((1,'mandragora',7,3),boss=(100,5,3)))
        w.set_aim_target((96,240));w.fire();w.advance_time(.25)
        self.assertFalse(w.spawn_waves());self.assertFalse(w.encounter.boss_wave_spawned)
        w.pause();self.assertFalse(w.spawn_waves());w.resume()
        while w.state is GameState.SHOT_ANIMATION:w.advance_time(.25)
        self.assertFalse(w.encounter.boss_wave_spawned);w.resolve_turn()
        self.assertTrue(w.encounter.boss_wave_spawned)
        self.assertEqual(w.enemies[100].turns_alive,0)
        self.assertEqual(w.enemies[100].odin_phase,0)
        self.assertEqual(w.encounter.spawn_history,[1,100])
        self.assertFalse(w.spawn_waves());self.assertEqual(w.encounter.spawn_history,[1,100])
        escaped=playing(definition((1,'mandragora',13,6),boss=(100,5,3)))
        perform_action(escaped,'shot',0)
        self.assertIs(escaped.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertNotIn(100,escaped.enemies);self.assertFalse(escaped.encounter.boss_wave_spawned)

    def test_odin_group_respects_capacity_and_conflicting_archived_ids(self):
        stage=definition((1,'mandragora',0,3),boss=(100,5,3),capacity=1)
        combat=Combat();encounter=Encounter(stage);encounter.spawn_due(1,combat)
        self.assertIsNone(encounter.outcome(combat));combat.apply_damage(1,100)
        conflict=Enemy(100,EnemyType.GORGON,5,3);conflict.take_damage(100);combat.add_enemy(conflict)
        self.assertEqual(encounter.spawn_due(2,combat),())
        self.assertFalse(encounter.boss_wave_spawned)
        self.assertNotIn(100,encounter.spawn_history)


class StageThreeCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init();pygame.font.init();pygame.display.set_mode((960,576))

    @classmethod
    def tearDownClass(cls):pygame.quit()

    def test_full_three_stage_campaign_meteor_victory_results_through_posted_controls(self):
        game=Game();game.running=True
        for _ in range(2):pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        for event in pygame.event.get():game.handle_event(event)
        enter_stage_three(game.world,game=game)
        w=game.world;self.assertEqual((w.stage,w.hp,w.mp,w.bp,w.turn_index),(3,100,100,1,1))
        self.assertTrue(w.select_spell('meteor'));before=deepcopy(vars(w))
        self.assertFalse(w.advance_stage());self.assertEqual(vars(w),before)
        for k,row in METEOR_CLEAR[:-1]:perform_action(w,k,row,game=game)
        self.assertEqual((w.hp,w.mp,w.enemies[500].hp,w.enemies[500].odin_phase),(5,100,5,2))
        for key in (pygame.K_3,pygame.K_SPACE,pygame.K_SPACE):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=key))
        for event in pygame.event.get():game.handle_event(event)
        self.assertIs(w.state,GameState.SPELL_ANIMATION)
        self.assertEqual((w.mp,w.enemies[500].hp),(20,0));self.assertFalse(w._pending_action.completed)
        self.assertFalse(w.resolve_turn());self.assertEqual(w.last_resolved_turn,21)
        w.pause();frozen=deepcopy(vars(w))
        for _ in range(4):w.advance_time(100);self.assertFalse(w.resolve_turn())
        self.assertEqual(vars(w),frozen);w.resume()
        while w.state is GameState.SPELL_ANIMATION:w.advance_time(.05)
        self.assertIs(w.state,GameState.TURN_RESOLVE);self.assertTrue(w.resolve_turn())
        self.assertIs(w.state,GameState.VICTORY)
        self.assertEqual((w.stage,w.turn_index,w.hp,w.mp,w.bp),(3,22,5,20,5))
        self.assertEqual(len(w.combat.death_events),40)
        self.assertEqual(w.enemies[500].turns_alive,2) # No final EXECUTE.
        before=deepcopy(vars(w));self.assertFalse(w.resolve_turn())
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,repeat=True))
        self.assertEqual(vars(w),before)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertIs(w.state,GameState.RESULTS)
        self.assertEqual((w.hp,w.mp,w.bp,w.stage,w.turn_index),(5,20,5,3,22))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_r))
        self.assertEqual((w.stage,w.state,w.hp,w.mp,w.bp),(1,GameState.STAGE_INTRO,100,100,1))
        self.assertEqual(w.encounter.definition,STAGE_ONE)
        self.assertEqual(w.status_events,());self.assertEqual(w.spells.cooldowns,{})
        game.handle_event(pygame.event.Event(pygame.QUIT));self.assertFalse(game.running)

    def test_canonical_ward_reraise_execute_survival_then_victory_without_hp_edits(self):
        w=playing()
        for k,row in EXECUTE_CLEAR:perform_action(w,k,row)
        self.assertIs(w.state,GameState.VICTORY)
        self.assertEqual((w.turn_index,w.hp,w.mp,w.bp),(24,10,10,5))
        self.assertEqual(sum(e.kind is StatusEventKind.RERAISE_ACTIVATED for e in w.status_events),1)
        self.assertEqual(sum(e.kind is StatusEventKind.WARD_BLOCKED for e in w.status_events),1)
        forced=[e for e in w.status_events if e.kind is StatusEventKind.FORCED_KNOCKOUT]
        self.assertEqual([(e.turn,e.source_id)for e in forced],[(22,'odin_execute')])

    def test_shooting_only_stage_three_clear_retains_original_spell_values(self):
        w=playing()
        for row in ORDINARY_ROWS+(4,3,3):perform_action(w,'shot',row)
        self.assertIs(w.state,GameState.VICTORY)
        self.assertEqual((w.hp,w.mp,w.bp,w.turn_index),(5,100,5,22))
        self.assertEqual(w.spells.cooldowns,{})

    def test_final_meteor_clear_precedes_due_poison_doom_hazards_and_odin(self):
        w=playing()
        for k,row in METEOR_CLEAR[:-1]:perform_action(w,k,row)
        w.apply_status(StatusKind.POISON,1);w.apply_status(StatusKind.DOOM,1);w.place_poison_tile(3)
        for e in w.statuses.snapshot():w.statuses.put(replace(e,applied_turn=w.turn_index-1))
        tile=w.hazards.snapshot()[0];w.hazards.put(replace(tile,applied_turn=w.turn_index-1))
        before=w.snapshot();perform_action(w,'meteor',3)
        self.assertIs(w.state,GameState.VICTORY);self.assertEqual(w.hp,before.hp)
        self.assertEqual(w.status_events,before.status_events);self.assertEqual(w.hazards.snapshot(),before.hazards)
        self.assertEqual(w.enemies[500].odin_phase,2)

    def test_meteor_cost_cooldown_global_targeting_and_duplicate_main_action_guards(self):
        w=playing(definition((1,'tonberry',7,3),(2,'diremite',0,7),(3,'gorgon',0,6)))
        self.assertTrue(w.select_spell('meteor'));result=w.cast_selected_spell()
        self.assertTrue(result.valid);self.assertEqual(w.mp,20)
        self.assertEqual([w.enemies[i].hp for i in (1,2,3)],[3,0,0])
        self.assertEqual([e.enemy_id for e in w.combat.death_events],[2,3])
        self.assertEqual(w.spells.next_ready_turn('meteor'),12)
        self.assertFalse(w.fire());self.assertFalse(w.cast_selected_spell().valid)
        while w.state is GameState.SPELL_ANIMATION:w.advance_time(.25)
        w.resolve_turn();before=deepcopy(vars(w));self.assertFalse(w.cast_selected_spell().valid)
        self.assertEqual(w.mp,20);self.assertEqual(w.turn_index,2)
        # Feedback is the only permitted difference after the rejected cast.
        after=deepcopy(vars(w));after['spell_feedback']=before['spell_feedback'];self.assertEqual(after,before)

    def test_stage_three_hp_defeat_through_ordinary_misses(self):
        w=playing()
        for _ in range(12):perform_action(w,'shot',0)
        self.assertIs(w.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual((w.hp,w.turn_index,w.mp,w.bp),(0,12,100,1))
        self.assertFalse(w.encounter.boss_wave_spawned)
        self.assertTrue(any(e.kind is StatusEventKind.POISON_DAMAGE for e in w.status_events))
        self.assertTrue(any(e.kind is StatusEventKind.DOOM_ADVANCED for e in w.status_events))
        self.assertTrue(w.restart());self.assertEqual(w.stage,1)

    def test_stage_three_defense_failure_keeps_hp_and_never_spawns_odin(self):
        w=playing()
        for row in ORDINARY_ROWS[:-1]:perform_action(w,'shot',row)
        for kind,row,target in DEFENSE_ENDING:
            if kind=='shot':perform_aimed_shot(w,row,target)
            else:perform_action(w,kind,row)
        self.assertIs(w.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertEqual((w.hp,w.mp,w.bp,w.turn_index),(95,0,5,28))
        self.assertTrue(w.enemies[445].escaped);self.assertEqual(w.enemies[445].hp,15)
        self.assertEqual(len(w.combat.death_events),38)
        self.assertFalse(w.encounter.boss_wave_spawned);self.assertNotIn(500,w.enemies)
        self.assertTrue(w.restart());self.assertEqual(w.stage,1)

    def test_canonical_doom_knockout_is_reachable_without_fixture_status_or_hp_edits(self):
        w=playing()
        for row in (0,0,3,0,0,0):perform_action(w,'shot',row)
        self.assertEqual(w.statuses.get(StatusKind.DOOM).remaining_turns,1)
        self.assertEqual(w.hp,85)
        perform_action(w,'shot',0)
        self.assertIs(w.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual((w.hp,w.turn_index),(0,7))
        self.assertTrue(any(e.kind is StatusEventKind.FORCED_KNOCKOUT and e.source_id=='doom'
                            for e in w.status_events))

    def test_canonical_doom_reraise_uses_actual_enemy_effects_and_one_cast_allowance(self):
        w=playing()
        for row in (0,0,3,0,0,0):perform_action(w,'shot',row)
        perform_action(w,'reraise',0)
        self.assertEqual((w.hp,w.mp,w.turn_index),(50,50,8))
        self.assertIs(w.state,GameState.PLAYER_AIM)
        self.assertIsNone(w.statuses.get(StatusKind.DOOM))
        self.assertIsNone(w.statuses.get(StatusKind.RERAISE));self.assertTrue(w.reraise_used)
        perform_action(w,'shot',0)
        before=w.mp
        self.assertFalse(w.execute_support_spell('again','reraise').valid)
        self.assertEqual(w.mp,before)

    def test_stage_transition_resets_enrage_cycle_actions_statuses_and_spell_unlocks(self):
        w=World();w.start_new_run();w.transition_to(GameState.PLAYER_AIM)
        enter_stage_three(w)
        self.assertEqual((w.hp,w.mp,w.bp,w.turn_index,w.player_row),(100,100,1,1,3))
        self.assertIsNone(w.aim_target);self.assertIsNone(w.selected_spell)
        self.assertEqual(w.spells.cooldowns,{});self.assertEqual(w.status_events,())
        self.assertFalse(w.reraise_used);self.assertEqual(w.hazards.snapshot(),())
        self.assertEqual(w._next_action_id,1);self.assertEqual(w._next_projectile_id,1)
        self.assertEqual(w._physics.accumulator,0);self.assertIsNone(w._pending_action)
        self.assertEqual(w.combat.death_events,[])
        self.assertTrue(all(not e.enraged and e.turns_alive==0 for e in w.enemies.values()))
        self.assertTrue(w.select_spell('meteor'))
        self.assertTrue(w.select_spell('esuna'));self.assertTrue(w.select_spell('levitation'))

    def test_restart_from_victory_and_results_clears_all_stage_three_state(self):
        for terminal in (GameState.VICTORY,GameState.RESULTS):
            w=playing()
            for k,row in EXECUTE_CLEAR:perform_action(w,k,row)
            if terminal is GameState.RESULTS:w.transition_to(GameState.RESULTS)
            self.assertTrue(w.restart())
            self.assertEqual((w.stage,w.state,w.turn_index,w.hp,w.mp,w.bp),(1,GameState.STAGE_INTRO,1,100,100,1))
            self.assertEqual(w.enemies,{});self.assertEqual(w.crystals,{})
            self.assertEqual(w.projectiles,[]);self.assertEqual(w.status_events,())
            self.assertEqual(w.statuses.snapshot(),());self.assertEqual(w.hazards.snapshot(),())
            self.assertEqual(w.spells.cooldowns,{});self.assertEqual(w.spells._committed_actions,{})
            self.assertFalse(w.reraise_used);self.assertEqual(w.encounter.spawn_history,[])
            self.assertIsNone(w._pending_action);self.assertEqual(w._spell_remaining,0)
            self.assertEqual(w._next_action_id,1);self.assertEqual(w._next_projectile_id,1)

    def test_enter_repeat_cannot_skip_intro_or_results_and_manual_scenes_cannot_claim_turns(self):
        game=Game();game.running=True
        before=deepcopy(vars(game.world))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,repeat=True))
        self.assertEqual(vars(game.world),before)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN))
        self.assertIs(game.world.state,GameState.STAGE_INTRO)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_RETURN,repeat=True))
        self.assertIs(game.world.state,GameState.STAGE_INTRO)
        w=playing(definition((1,'tonberry',0,6)))
        w.transition_to(GameState.SPELL_ANIMATION);w.transition_to(GameState.TURN_RESOLVE)
        before=deepcopy(vars(w));self.assertFalse(w.resolve_turn());self.assertEqual(vars(w),before)

    def test_all_terminal_outcomes_and_execute_survival_are_frame_schedule_invariant(self):
        for mode in ('meteor','execute','HP','defense'):
            reference=None
            for schedule in ((1/30,),(1/60,),(1/144,),(.004,.041,.009,.024,.005,.017)):
                w=playing();history=[]
                if mode in ('meteor','execute'):
                    for k,row in METEOR_CLEAR if mode=='meteor' else EXECUTE_CLEAR:
                        perform_action(w,k,row,schedule)
                        history.append((w.snapshot(),tuple(w.combat.death_events),
                                        tuple(w.encounter.spawn_history),
                                        tuple((key,asdict(e)) for key,e in sorted(w.enemies.items()))))
                elif mode=='HP':
                    for _ in range(12):perform_action(w,'shot',0,schedule)
                else:
                    for row in ORDINARY_ROWS[:-1]:perform_action(w,'shot',row,schedule)
                    for kind,row,target in DEFENSE_ENDING:
                        if kind=='shot':perform_aimed_shot(w,row,target,schedule)
                        else:perform_action(w,kind,row,schedule)
                        history.append((w.snapshot(),tuple(w.combat.death_events)))
                outcome=(w.snapshot(),tuple(w.combat.death_events),tuple(w.encounter.spawn_history),history)
                if reference is None:reference=outcome
                self.assertEqual(outcome,reference,(mode,schedule))

    def test_stage_three_rendering_enrage_odin_and_end_screens_is_read_only(self):
        w=playing(definition((1,'mandragora',0,0),(2,'diremite',0,1),(3,'tonberry',0,2),(4,'gorgon',0,3)))
        w.combat.apply_damage(3,1,'fixture');w.combat.add_enemy(Enemy(100,EnemyType.ODIN,0,4))
        w.apply_status(StatusKind.DOOM)
        renderer=Renderer();screen=pygame.display.get_surface();texts=[]
        class Font:
            def __init__(self,font):self.font=font
            def render(self,text,*args):texts.append(text);return self.font.render(text,*args)
        renderer.body_font=Font(renderer.body_font);renderer.hud_font=Font(renderer.hud_font)
        before=deepcopy(vars(w));snap=w.snapshot()
        with patch.object(renderer.hud, '_text', wraps=renderer.hud._text) as hud_text, \
             patch.object(renderer.screens, '_text', wraps=renderer.screens._text) as screen_text:
            for state in (GameState.PLAYER_AIM,GameState.PAUSED,GameState.VICTORY,GameState.RESULTS):
                renderer.draw(screen,replace(snap,state=state))
        texts.extend(call.args[1] for call in hud_text.call_args_list)
        texts.extend(call.args[1] for call in screen_text.call_args_list)
        self.assertEqual(vars(w),before);self.assertEqual(w.snapshot(),snap)
        for text in ('Mn10','D12','T!17','G15','O50','! DOOM 5t','Stage 3 | Turn 1',
                     'HP 100/100','MP 100/100','BP 1/5','Enter: Results','R: Restart Run'):
            self.assertIn(text,texts)
        self.assertIn('Score: —',texts)
        self.assertFalse(hasattr(snap,'score'))

    def test_no_scoring_or_save_files_are_created_by_campaign_actions(self):
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory);w=playing()
                for k,row in METEOR_CLEAR:perform_action(w,k,row)
                w.transition_to(GameState.RESULTS)
                self.assertEqual(list(Path(directory).iterdir()),[])
            finally:os.chdir(previous)


if __name__=='__main__':unittest.main()
