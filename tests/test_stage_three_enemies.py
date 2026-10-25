"""Stage 3 enemy damage, cadence, status timing, and Odin defense contracts."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from src.combat import Combat
from src.entities import Enemy, EnemyType, EnemyTurnContext, Crystal
from src.projectile import Projectile, FixedStepPhysics
from src.states import GameState, GameOverReason
from src.statuses import StatusKind, StatusEventKind
from src.turns import resolve_enemy_phase
from stage_one_fixtures import perform_action
from stage_three_fixtures import definition, playing


class StageThreeEnemyTests(unittest.TestCase):
    def test_exact_hp_attacks_and_common_contact_values(self):
        for kind,hp,attack in (('mandragora',10,0),('diremite',12,0),('tonberry',18,3),
                               ('gorgon',15,0),('odin',50,40)):
            e=Enemy(1,EnemyType(kind),0,3)
            self.assertEqual((e.hp,e.max_hp,e.attack_damage,e.contact_damage),(hp,hp,attack,5))
            self.assertFalse(e.enraged);self.assertEqual(e.is_boss,kind=='odin')

    def test_all_new_enemies_take_exact_projectile_hits_and_have_cell_bounds(self):
        for kind in ('mandragora','diremite','tonberry','gorgon','odin'):
            e=Enemy(1,EnemyType(kind),4,3);combat=Combat({1:e})
            self.assertEqual(e.bounds.right-e.bounds.left,48)
            orb=Projectile.launch(1,(e.bounds.right+12,e.position[1]),(-1,0))
            FixedStepPhysics().advance(.05,[orb],target_provider=combat.targets,on_hit=combat.handle_hit)
            self.assertEqual(e.hp,e.max_hp-5)
            self.assertEqual(e.enraged,kind=='tonberry')

    def test_mandragora_cadence_and_tile_grace_match_bulb(self):
        w=playing(definition((1,'mandragora',0,6)))
        for _ in range(3):perform_action(w,'shot',0)
        self.assertEqual(w.hp,100)
        self.assertEqual([(t.row,t.applied_turn,t.remaining_turns)for t in w.hazards.snapshot()],[(0,3,2)])
        perform_action(w,'shot',0);self.assertEqual(w.hp,95)
        perform_action(w,'shot',0);self.assertEqual((w.hp,w.hazards.snapshot()),(90,()))

    def test_mandragora_refresh_keeps_earned_tile_tick_and_full_new_duration(self):
        w=playing(definition((1,'mandragora',0,6)))
        perform_action(w,'shot',0);w.place_poison_tile(0)
        perform_action(w,'shot',0);perform_action(w,'shot',0)
        self.assertEqual(w.hp,95);self.assertEqual(w.hazards.snapshot()[0].remaining_turns,2)
        self.assertEqual(len(w.hazards.snapshot()),1)

    def test_diremite_poison_two_turn_cadence_grace_refresh_and_single_tick(self):
        w=playing(definition((1,'diremite',0,6)))
        for turn,expected_hp,remaining in ((1,100,None),(2,100,2),(3,97,1),(4,94,2),(5,91,1),(6,88,2)):
            perform_action(w,'shot',0)
            self.assertEqual(w.hp,expected_hp)
            effect=w.statuses.get(StatusKind.POISON)
            self.assertEqual(effect.remaining_turns if effect else None,remaining)
            self.assertLessEqual(sum(e.kind is StatusEventKind.POISON_DAMAGE and e.turn==turn
                                     for e in w.status_events),1)

    def test_two_diremites_do_not_stack_poison_or_duplicate_ticks(self):
        w=playing(definition((1,'diremite',0,6),(2,'diremite',0,7)))
        for _ in range(4):perform_action(w,'shot',0)
        self.assertEqual(w.hp,94)
        self.assertEqual(len(w.statuses.snapshot()),1)
        self.assertEqual(w.statuses.get(StatusKind.POISON).source_id,2)

    def test_poison_expires_after_source_dies(self):
        w=playing(definition((1,'diremite',0,6),(2,'landtrap',0,7)))
        for _ in range(2):perform_action(w,'shot',0)
        w.combat.apply_damage(1,100,'fixture')
        for _ in range(2):perform_action(w,'shot',0)
        self.assertEqual(w.hp,94);self.assertIsNone(w.statuses.get(StatusKind.POISON))

    def test_tonberry_uninjured_does_not_attack(self):
        w=playing(definition((1,'tonberry',0,6)))
        for _ in range(3):perform_action(w,'shot',0)
        self.assertEqual(w.hp,100);self.assertFalse(w.enemies[1].enraged)
        self.assertEqual(w.enemies[1].grid_col,3)

    def test_tonberry_zero_damage_does_not_enrage(self):
        e=Enemy(1,EnemyType.TONBERRY,4,3);combat=Combat({1:e})
        combat.apply_damage(1,0)
        self.assertFalse(e.enraged);self.assertEqual(e.hp,18)
        e.take_damage(1);self.assertTrue(e.enraged)

    def test_tonberry_spell_and_bomb_damage_enrage_through_shared_damage_method(self):
        for spell in ('starstorm','meteor'):
            w=playing(definition((1,'tonberry',7,3)))
            self.assertTrue(w.execute_offensive_spell('damage',spell).valid)
            self.assertTrue(w.enemies[1].enraged)
            self.assertEqual(w.enemies[1].hp,8 if spell=='starstorm' else 3)
        target=Enemy(2,EnemyType.TONBERRY,5,3)
        combat=Combat({1:Enemy(1,EnemyType.BOMB,4,3),2:target})
        combat.apply_damage(1,5)
        self.assertEqual(target.hp,8);self.assertTrue(target.enraged)

    def test_tonberry_retaliates_once_in_next_surviving_phase_and_stays_enraged(self):
        w=playing(definition((1,'tonberry',7,3)))
        perform_action(w,'starstorm',3)
        self.assertEqual(w.hp,97);self.assertTrue(w.enemies[1].enraged)
        perform_action(w,'shot',0)
        self.assertEqual(w.hp,94)
        self.assertFalse(w.resolve_turn());self.assertEqual(w.hp,94)

    def test_tonberry_lethal_damage_and_escape_never_authorize_retaliation(self):
        e=Enemy(1,EnemyType.TONBERRY,13,6);e.take_damage(1);e.escape(1)
        dead=Enemy(2,EnemyType.TONBERRY,4,3);dead.take_damage(100)
        hits=[]
        resolve_enemy_phase([e,dead],EnemyTurnContext(2,hits.append,lambda:False))
        self.assertEqual(hits,[])
        self.assertTrue(dead.enraged);self.assertEqual(dead.turns_alive,0)

    def test_tonberry_enrage_snapshot_is_frozen_and_detached(self):
        e=Enemy(1,EnemyType.TONBERRY,4,3);before=e.snapshot();e.take_damage(1)
        after=e.snapshot();self.assertFalse(before.enraged);self.assertTrue(after.enraged)
        with self.assertRaises(FrozenInstanceError):after.enraged=False

    def test_gorgon_applies_five_turn_doom_every_second_phase_with_refresh_grace(self):
        w=playing(definition((1,'gorgon',0,6)))
        for turn,remaining in ((1,None),(2,5),(3,4),(4,5),(5,4),(6,5)):
            perform_action(w,'shot',0)
            effect=w.statuses.get(StatusKind.DOOM)
            self.assertEqual(effect.remaining_turns if effect else None,remaining)
            self.assertEqual(w.hp,100)
            self.assertLessEqual(sum(e.kind is StatusEventKind.DOOM_ADVANCED and e.turn==turn
                                     for e in w.status_events),1)

    def test_gorgon_doom_continues_after_death_and_ignores_esuna(self):
        w=playing(definition((1,'gorgon',0,6),(2,'landtrap',0,7)))
        for _ in range(2):perform_action(w,'shot',0)
        perform_action(w,'esuna',0)
        self.assertEqual(w.statuses.get(StatusKind.DOOM).remaining_turns,4)
        w.combat.apply_damage(1,100,'fixture')
        for remaining in (3,2,1):
            perform_action(w,'shot',0)
            self.assertEqual(w.statuses.get(StatusKind.DOOM).remaining_turns,remaining)
        perform_action(w,'ward',0)
        self.assertIs(w.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual(w.hp,0)
        self.assertFalse(any(e.kind is StatusEventKind.WARD_BLOCKED for e in w.status_events))
        self.assertIsNone(w.statuses.get(StatusKind.DOOM))

    def test_gorgon_forced_knockout_reraise_and_once_per_encounter(self):
        w=playing(definition((1,'gorgon',0,6),(2,'landtrap',0,7)))
        for _ in range(2):perform_action(w,'shot',0)
        w.combat.apply_damage(1,100,'fixture')
        for _ in range(4):perform_action(w,'shot',0)
        perform_action(w,'reraise',0)
        self.assertEqual(w.hp,50);self.assertTrue(w.reraise_used)
        self.assertIsNone(w.statuses.get(StatusKind.RERAISE));self.assertIsNone(w.statuses.get(StatusKind.DOOM))
        self.assertFalse(w.execute_support_spell('second','reraise').valid)

    def test_multiple_status_sources_remain_ordered_and_defenses_are_shared(self):
        stage=definition((1,'mandragora',0,6),(2,'diremite',0,7),(3,'gorgon',1,6))
        records=[]
        for reverse in (False,True):
            w=playing(stage)
            if reverse:w.combat.enemies=dict(reversed(tuple(w.enemies.items())))
            for _ in range(3):perform_action(w,'shot',0)
            perform_action(w,'levitation',0)
            records.append((w.snapshot(),w.status_events))
            # Floor is ignored first; existing Poison still deals ordinary damage.
            self.assertEqual(w.hp,94)
            self.assertTrue(any(e.kind is StatusEventKind.LEVITATION_BLOCKED for e in w.status_events))
        self.assertEqual(records[0],records[1])

    def test_ward_blocks_tonberry_or_poison_one_event_not_both(self):
        w=playing(definition((1,'tonberry',0,6),(2,'diremite',0,7)))
        w.combat.apply_damage(1,1,'fixture')
        for _ in range(2):perform_action(w,'shot',0)
        hp=w.hp;perform_action(w,'ward',0)
        self.assertEqual(w.hp,hp-3)
        events=[e.kind for e in w.status_events if e.turn==3]
        self.assertLess(events.index(StatusEventKind.WARD_BLOCKED),events.index(StatusEventKind.POISON_DAMAGE))

    def test_all_new_types_take_fire_starstorm_meteor_and_bomb_damage_once(self):
        for kind in ('mandragora','diremite','tonberry','gorgon','odin'):
            for spell,damage in (('fire',20),('starstorm',10),('meteor',15)):
                # Odin uses its real boss factory; other kinds use ordinary spawns.
                stage=definition(boss=(1,7,3)) if kind=='odin' else definition((1,kind,7,3))
                w=playing(stage);before=w.enemies[1].hp
                result=w.execute_offensive_spell('one',spell)
                self.assertTrue(result.valid);self.assertEqual(w.enemies[1].hp,max(0,before-damage))
                after=deepcopy(vars(w));self.assertFalse(w.execute_offensive_spell('one',spell).valid)
                self.assertEqual(vars(w),after)
            target=Enemy(2,EnemyType(kind),5,3)
            combat=Combat({1:Enemy(1,EnemyType.BOMB,4,3),2:target})
            combat.add_crystal(Crystal(3,5,3));combat.apply_damage(1,5)
            self.assertEqual(target.hp,max(0,target.max_hp-10))
            self.assertFalse(combat.crystals[3].collected)


class OdinTests(unittest.TestCase):
    def test_complete_cycle_repeats_and_duplicate_callbacks_cannot_advance_it(self):
        e=Enemy(1,EnemyType.ODIN,0,6);attacks=[]
        for turn in range(1,10):
            context=EnemyTurnContext(turn,attacks.append,lambda:False,
                                    force_knockout=lambda:attacks.append('EXECUTE'))
            self.assertTrue(e.on_turn(context));phase=e.odin_phase
            self.assertFalse(e.on_turn(context));self.assertEqual(e.odin_phase,phase)
        self.assertEqual(attacks,[40,40,'EXECUTE']*3)
        self.assertEqual((e.turns_alive,e.odin_phase),(9,0))

    def test_slashes_deal_exact_forty_and_execute_is_forced(self):
        w=playing(definition(boss=(100,0,6)))
        perform_action(w,'shot',0);self.assertEqual(w.hp,60)
        perform_action(w,'shot',0);self.assertEqual(w.hp,20)
        perform_action(w,'shot',0)
        self.assertEqual(w.hp,0);self.assertIs(w.state,GameState.GAME_OVER)
        self.assertEqual(w.enemies[100].odin_phase,0)
        self.assertEqual(w.status_events[-1].kind,StatusEventKind.FORCED_KNOCKOUT)
        self.assertEqual(w.status_events[-1].source_id,'odin_execute')

    def test_ward_blocks_slash_without_stalling_cycle(self):
        w=playing(definition(boss=(100,0,6)))
        perform_action(w,'ward',0)
        self.assertEqual(w.hp,100);self.assertEqual(w.enemies[100].odin_phase,1)
        self.assertIsNone(w.statuses.get(StatusKind.WARD))
        perform_action(w,'shot',0);self.assertEqual(w.hp,60)

    def test_execute_bypasses_ward_and_reraise_resolves_before_terminal_state(self):
        w=playing(definition(boss=(100,0,6)))
        perform_action(w,'shot',0);perform_action(w,'reraise',0)
        perform_action(w,'ward',0)
        self.assertEqual(w.hp,50);self.assertIs(w.state,GameState.PLAYER_AIM)
        self.assertTrue(w.reraise_used);self.assertIsNone(w.statuses.get(StatusKind.RERAISE))
        self.assertFalse(any(e.kind is StatusEventKind.WARD_BLOCKED for e in w.status_events))
        self.assertEqual(w.enemies[100].odin_phase,0)

    def test_real_world_survives_one_cycle_then_second_execute_defeats(self):
        w=playing(definition(boss=(100,0,6)))
        for spell in ('ward','reraise','cure','shot','cure','shot'):
            perform_action(w,spell,0)
        self.assertIs(w.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual((w.hp,w.mp,w.turn_index),(0,0,6))
        self.assertEqual(w.enemies[100].odin_phase,0)
        self.assertEqual(sum(e.kind is StatusEventKind.RERAISE_ACTIVATED for e in w.status_events),1)
        self.assertEqual(sum(e.kind is StatusEventKind.FORCED_KNOCKOUT for e in w.status_events),2)

    def test_reraise_can_also_revive_lethal_slash(self):
        w=playing(definition(boss=(100,0,6)));w.hp=30
        perform_action(w,'reraise',0)
        self.assertEqual(w.hp,50);self.assertEqual(w.enemies[100].odin_phase,1)
        self.assertIs(w.state,GameState.PLAYER_AIM)

    def test_odin_death_archives_once_and_prevents_any_more_attacks(self):
        w=playing(definition(boss=(100,7,3)))
        w.combat.apply_damage(100,100,'fixture')
        self.assertFalse(w.combat.apply_damage(100,100))
        self.assertNotIn(100,[t.target_id for t in w.combat.targets()]);self.assertEqual(len(w.combat.death_events),1)
        perform_action(w,'shot',0)
        self.assertIs(w.state,GameState.VICTORY);self.assertEqual(w.hp,100)
        self.assertEqual(w.enemies[100].turns_alive,0)

    def test_odin_escape_is_contact_failure_without_death_or_revival(self):
        w=playing(definition(boss=(100,13,6)))
        perform_action(w,'reraise',0)
        self.assertEqual(w.hp,55) # slash 40 plus normal escape contact five
        self.assertIs(w.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertTrue(w.enemies[100].escaped);self.assertEqual(w.combat.death_events,[])
        self.assertIsNotNone(w.statuses.get(StatusKind.RERAISE))
        self.assertNotIn(100,[t.target_id for t in w.combat.targets()])

    def test_pause_and_snapshot_do_not_advance_attack_cycle(self):
        w=playing(definition(boss=(100,0,6)))
        perform_action(w,'shot',0);w.pause();before=deepcopy(vars(w))
        for _ in range(5):w.advance_time(100);w.resolve_turn();w.snapshot()
        self.assertEqual(vars(w),before)
        w.resume();perform_action(w,'shot',0)
        self.assertEqual((w.hp,w.enemies[100].odin_phase),(20,2))
        snap=w.enemies[100].snapshot()
        with self.assertRaises(FrozenInstanceError):snap.odin_phase=0


if __name__=='__main__':unittest.main()
