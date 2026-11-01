"""Stage 3 enemy damage, cadence, status timing, and Iron Knight defense contracts."""

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
        for kind,hp,attack in (('rootling',10,0),('venomcrawler',12,0),('hooded_stalker',18,3),
                               ('thorn_sentinel',15,0),('iron_regent',50,40)):
            e=Enemy(1,EnemyType(kind),0,3)
            self.assertEqual((e.hp,e.max_hp,e.attack_damage,e.contact_damage),(hp,hp,attack,5))
            self.assertFalse(e.enraged);self.assertEqual(e.is_boss,kind=='iron_regent')

    def test_all_new_enemies_take_exact_projectile_hits_and_have_cell_bounds(self):
        for kind in ('rootling','venomcrawler','hooded_stalker','thorn_sentinel','iron_regent'):
            e=Enemy(1,EnemyType(kind),4,3);combat=Combat({1:e})
            self.assertEqual(e.bounds.right-e.bounds.left,48)
            orb=Projectile.launch(1,(e.bounds.right+12,e.position[1]),(-1,0))
            FixedStepPhysics().advance(.05,[orb],target_provider=combat.targets,on_hit=combat.handle_hit)
            self.assertEqual(e.hp,e.max_hp-4)
            self.assertEqual(e.enraged,kind=='hooded_stalker')



    def test_venomcrawler_poison_two_turn_cadence_grace_refresh_and_single_tick(self):
        w=playing(definition((1,'venomcrawler',0,6)))
        for turn,expected_hp,remaining in ((1,100,None),(2,100,2),(3,97,1),(4,94,2),(5,91,1),(6,88,2)):
            perform_action(w,'shot',0)
            self.assertEqual(w.hp,expected_hp)
            effect=w.statuses.get(StatusKind.POISON)
            self.assertEqual(effect.remaining_turns if effect else None,remaining)
            self.assertLessEqual(sum(e.kind is StatusEventKind.POISON_DAMAGE and e.turn==turn
                                     for e in w.status_events),1)

    def test_two_venomcrawlers_do_not_stack_poison_or_duplicate_ticks(self):
        w=playing(definition((1,'venomcrawler',0,6),(2,'venomcrawler',0,7)))
        for _ in range(4):perform_action(w,'shot',0)
        self.assertEqual(w.hp,94)
        self.assertEqual(len(w.statuses.snapshot()),1)
        self.assertEqual(w.statuses.get(StatusKind.POISON).source_id,2)

    def test_poison_expires_after_source_dies(self):
        w=playing(definition((1,'venomcrawler',0,6),(2,'snaproot',0,7)))
        for _ in range(2):perform_action(w,'shot',0)
        w.combat.apply_damage(1,100,'fixture')
        for _ in range(2):perform_action(w,'shot',0)
        self.assertEqual(w.hp,94);self.assertIsNone(w.statuses.get(StatusKind.POISON))

    def test_hooded_stalker_uninjured_does_not_attack(self):
        w=playing(definition((1,'hooded_stalker',0,6)))
        for _ in range(3):perform_action(w,'shot',0)
        self.assertEqual(w.hp,100);self.assertFalse(w.enemies[1].enraged)
        self.assertEqual(w.enemies[1].grid_col,3)

    def test_hooded_stalker_zero_damage_does_not_enrage(self):
        e=Enemy(1,EnemyType.HOODED_STALKER,4,3);combat=Combat({1:e})
        combat.apply_damage(1,0)
        self.assertFalse(e.enraged);self.assertEqual(e.hp,18)
        e.take_damage(1);self.assertTrue(e.enraged)

    def test_hooded_stalker_spell_and_bomb_damage_enrage_through_shared_damage_method(self):
        for spell, expected_hp in (('ember_lance', 0), ('skyfall', 3)):
            w=playing(definition((1,'hooded_stalker',7,3)))
            self.assertTrue(w.execute_offensive_spell('damage',spell).valid)
            self.assertTrue(w.enemies[1].enraged)
            self.assertEqual(w.enemies[1].hp,expected_hp)
        target=Enemy(2,EnemyType.HOODED_STALKER,5,3)
        combat=Combat({1:Enemy(1,EnemyType.BOMB,4,3),2:target})
        combat.apply_damage(1,10)
        self.assertEqual(target.hp,8);self.assertTrue(target.enraged)

    def test_hooded_stalker_retaliates_once_in_next_surviving_phase_and_stays_enraged(self):
        w=playing(definition((1,'hooded_stalker',7,3)))
        perform_action(w,'skyfall',3)
        self.assertEqual(w.hp,97);self.assertTrue(w.enemies[1].enraged)
        perform_action(w,'shot',0)
        self.assertEqual(w.hp,94)
        self.assertFalse(w.resolve_turn());self.assertEqual(w.hp,94)

    def test_hooded_stalker_lethal_damage_and_escape_never_authorize_retaliation(self):
        e=Enemy(1,EnemyType.HOODED_STALKER,13,6);e.take_damage(1);e.escape(1)
        dead=Enemy(2,EnemyType.HOODED_STALKER,4,3);dead.take_damage(100)
        hits=[]
        resolve_enemy_phase([e,dead],EnemyTurnContext(2,hits.append,lambda:False))
        self.assertEqual(hits,[])
        self.assertTrue(dead.enraged);self.assertEqual(dead.turns_alive,0)

    def test_hooded_stalker_enrage_snapshot_is_frozen_and_detached(self):
        e=Enemy(1,EnemyType.HOODED_STALKER,4,3);before=e.snapshot();e.take_damage(1)
        after=e.snapshot();self.assertFalse(before.enraged);self.assertTrue(after.enraged)
        with self.assertRaises(FrozenInstanceError):after.enraged=False





    def test_ward_blocks_hooded_stalker_or_poison_one_event_not_both(self):
        w=playing(definition((1,'hooded_stalker',0,6),(2,'venomcrawler',0,7)))
        w.combat.apply_damage(1,1,'fixture')
        for _ in range(2):perform_action(w,'shot',0)
        hp=w.hp;perform_action(w,'barrier',0)
        self.assertEqual(w.hp,hp-3)
        events=[e.kind for e in w.status_events if e.turn==3]
        self.assertLess(events.index(StatusEventKind.WARD_BLOCKED),events.index(StatusEventKind.POISON_DAMAGE))

    def test_all_new_types_take_both_offensive_spells_and_bomb_damage_once(self):
        for kind in ('rootling','venomcrawler','hooded_stalker','thorn_sentinel','iron_regent'):
            for spell,damage in (('ember_lance',20),('skyfall',15)):
                # Iron Knight uses its real boss factory; other kinds use ordinary spawns.
                stage=definition(boss=(1,7,3)) if kind=='iron_regent' else definition((1,kind,7,3))
                w=playing(stage);before=w.enemies[1].hp
                result=w.execute_offensive_spell('one',spell)
                self.assertTrue(result.valid);self.assertEqual(w.enemies[1].hp,max(0,before-damage))
                after=deepcopy(vars(w));self.assertFalse(w.execute_offensive_spell('one',spell).valid)
                self.assertEqual(vars(w),after)
            target=Enemy(2,EnemyType(kind),5,3)
            combat=Combat({1:Enemy(1,EnemyType.BOMB,4,3),2:target})
            combat.add_crystal(Crystal(3,5,3));combat.apply_damage(1,10)
            self.assertEqual(target.hp,max(0,target.max_hp-10))
            self.assertFalse(combat.crystals[3].collected)


class IronRegentTests(unittest.TestCase):
    def test_heavy_blow_cycle_repeats_and_duplicate_callbacks_cannot_advance_it(self):
        e=Enemy(1,EnemyType.IRON_REGENT,0,6);attacks=[]
        for turn in range(1,10):
            context=EnemyTurnContext(turn,attacks.append,lambda:False,
                                    damage_from_enemy=lambda _id, amount, action:
                                    attacks.append((amount, action)) or amount)
            self.assertTrue(e.on_turn(context));phase=e.boss_phase
            self.assertFalse(e.on_turn(context));self.assertEqual(e.boss_phase,phase)
        self.assertEqual(attacks,[(40,'slash'),(40,'slash'),(50,'heavy_blow')]*3)
        self.assertEqual((e.turns_alive,e.boss_phase),(9,0))


    def test_ward_blocks_heavy_blow_without_stalling_cycle(self):
        from src.world import World
        w=World(demo=True);w.start_new_run();w.transition_to(GameState.PLAYER_AIM)
        w.enemies.clear()
        boss=Enemy(100,EnemyType.IRON_REGENT,0,6);boss.boss_phase=2
        w.combat.add_enemy(boss)
        perform_action(w,'barrier',0)
        self.assertEqual((w.hp,boss.boss_phase),(100,0))
        self.assertIsNone(w.statuses.get(StatusKind.WARD))




    def test_iron_regent_death_archives_once_and_prevents_any_more_attacks(self):
        w=playing(definition(boss=(100,7,3)))
        w.combat.apply_damage(100,100,'fixture')
        self.assertFalse(w.combat.apply_damage(100,100))
        self.assertNotIn(100,[t.target_id for t in w.combat.targets()]);self.assertEqual(len(w.combat.death_events),1)
        perform_action(w,'shot',0)
        self.assertIs(w.state,GameState.VICTORY);self.assertEqual(w.hp,100)
        self.assertEqual(w.enemies[100].turns_alive,0)


    def test_pause_and_snapshot_do_not_advance_attack_cycle(self):
        w=playing(definition(boss=(100,0,6)))
        perform_action(w,'shot',0);w.pause();before=deepcopy(vars(w))
        for _ in range(5):w.advance_time(100);w.resolve_turn();w.snapshot()
        self.assertEqual(vars(w),before)
        w.resume();perform_action(w,'shot',0)
        self.assertEqual((w.hp,w.enemies[100].boss_phase),(20,2))
        snap=w.enemies[100].snapshot()
        with self.assertRaises(FrozenInstanceError):snap.boss_phase=0


if __name__=='__main__':unittest.main()
