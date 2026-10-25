"""Exact Stage 2 enemy rules and their real World defensive/status integration."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from src.combat import Combat
from src.entities import Enemy, EnemyType, EnemyTurnContext, Crystal
from src.projectile import Projectile
from src.states import GameState, GameOverReason
from src.statuses import StatusKind, StatusEventKind
from src.turns import resolve_enemy_phase
from stage_one_fixtures import perform_action
from stage_two_fixtures import definition, playing


class StageTwoEnemyTests(unittest.TestCase):
    def test_exact_statistics_and_standard_contact(self):
        for kind, hp, attack in (('cactuar',10,5),('alligator',12,4),('bulb',8,0),
                                  ('morbol',18,0),('landtrap',8,0),('chichu',30,15)):
            enemy = Enemy(1, EnemyType(kind), 4, 3)
            self.assertEqual((enemy.hp,enemy.max_hp,enemy.attack_damage,enemy.contact_damage),
                             (hp,hp,attack,5))
            self.assertEqual(enemy.is_boss, kind == 'chichu')

    def test_geometry_and_snapshots_are_immutable(self):
        enemy = Enemy(1, EnemyType.CHICHU, 4, 3); snapshot = enemy.snapshot()
        self.assertEqual(snapshot.bounds.right-snapshot.bounds.left,48)
        self.assertEqual(snapshot.bounds.bottom-snapshot.bounds.top,48)
        enemy.advance_one_cell()
        self.assertEqual(snapshot.grid_col,4)
        with self.assertRaises(FrozenInstanceError):snapshot.hp=0

    def test_cactuar_steps_toward_player_then_fires_only_when_aligned(self):
        world=playing(definition((1,'cactuar',0,5)))
        perform_action(world,'shot',0)
        self.assertEqual((world.enemies[1].grid_col,world.enemies[1].grid_row,world.hp),(1,4,100))
        perform_action(world,'shot',0)
        self.assertEqual((world.enemies[1].grid_col,world.enemies[1].grid_row,world.hp),(2,3,100))
        # The selected row is zero, so approaching it cannot yet deal needles.
        perform_action(world,'shot',0);perform_action(world,'shot',0);perform_action(world,'shot',0)
        self.assertEqual(world.enemies[1].grid_row,0)
        self.assertEqual(world.hp,95)

    def test_cactuar_blocked_vertical_cell_waits_without_overlap(self):
        foes=[Enemy(1,EnemyType.CACTUAR,0,4),Enemy(2,EnemyType.LANDTRAP,0,3)]
        hits=[]
        resolve_enemy_phase(foes,EnemyTurnContext(1,hits.append,lambda:False,player_row=3))
        self.assertEqual([(e.grid_col,e.grid_row) for e in foes],[(1,4),(1,3)])
        self.assertEqual(hits,[])

    def test_cactuar_uses_vacated_cell_in_stable_id_order(self):
        foes=[Enemy(2,EnemyType.CACTUAR,0,4),Enemy(1,EnemyType.LANDTRAP,0,3)]
        hits=[]
        resolve_enemy_phase(foes,EnemyTurnContext(1,hits.append,lambda:False,player_row=3))
        self.assertEqual((foes[0].grid_col,foes[0].grid_row),(0,3))
        self.assertEqual(hits,[5])

    def test_alligator_uses_own_surviving_phase_cadence(self):
        enemy=Enemy(1,EnemyType.ALLIGATOR,0,1);hits=[]
        for turn in (7,8,9,10,11,12):
            enemy.on_turn(EnemyTurnContext(turn,hits.append,lambda:False))
            self.assertEqual(len(hits),enemy.turns_alive//3)
        self.assertEqual(hits,[4,4])

    def test_duplicate_phase_dead_and_escaped_enemies_do_not_act(self):
        hits=[];enemy=Enemy(1,EnemyType.CACTUAR,13,3)
        context=EnemyTurnContext(1,hits.append,lambda:False,player_row=3)
        resolve_enemy_phase([enemy],context);resolve_enemy_phase([enemy],context)
        self.assertEqual(hits,[5,5]);self.assertEqual(enemy.turns_alive,1)
        dead=Enemy(2,EnemyType.CHICHU,11,3);dead.take_damage(100)
        resolve_enemy_phase([dead,enemy],EnemyTurnContext(2,hits.append,lambda:False))
        self.assertEqual(hits,[5,5]);self.assertEqual(dead.turns_alive,0)

    def test_landtrap_only_advances_and_never_attacks(self):
        world=playing(definition((1,'landtrap',0,6)))
        for _ in range(4):perform_action(world,'shot',0)
        self.assertEqual((world.hp,world.enemies[1].grid_col,world.enemies[1].grid_row),(100,4,6))
        self.assertEqual(world.statuses.snapshot(),());self.assertEqual(world.hazards.snapshot(),())

    def test_morbol_applies_bind_and_poison_on_third_phase_with_grace(self):
        world=playing(definition((1,'morbol',0,6)))
        for _ in range(2):perform_action(world,'shot',0)
        self.assertEqual(world.statuses.snapshot(),())
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,100)
        effects={e.kind:e for e in world.statuses.snapshot()}
        self.assertEqual((effects[StatusKind.BIND].remaining_turns,effects[StatusKind.POISON].remaining_turns),(1,3))
        self.assertTrue(all(e.applied_turn==3 and e.source_id==1 for e in effects.values()))
        before=world.snapshot();self.assertFalse(world.move_player(1));self.assertEqual(world.snapshot(),before)
        self.assertTrue(world.set_aim_target((96,96)))
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,97);self.assertIsNone(world.statuses.get(StatusKind.BIND))
        self.assertEqual(world.statuses.get(StatusKind.POISON).remaining_turns,2)
        self.assertTrue(world.move_player(1))

    def test_esuna_cleanses_real_morbol_statuses_before_next_tick(self):
        world=playing(definition((1,'morbol',0,6)))
        for _ in range(3):perform_action(world,'shot',0)
        perform_action(world,'esuna',0)
        self.assertEqual((world.hp,world.mp),(100,80))
        self.assertEqual(world.statuses.snapshot(),());self.assertTrue(world.move_player(1))

    def test_bulb_places_tile_on_player_row_every_third_phase(self):
        world=playing(definition((1,'bulb',0,6)))
        for _ in range(3):perform_action(world,'shot',0)
        self.assertEqual(world.hp,100)
        tile=world.hazards.snapshot()[0]
        self.assertEqual((tile.row,tile.remaining_turns,tile.applied_turn,tile.source_id),(0,2,3,1))
        perform_action(world,'shot',0);self.assertEqual(world.hp,95)
        self.assertEqual(world.hazards.snapshot()[0].remaining_turns,1)
        perform_action(world,'shot',0);self.assertEqual(world.hp,90)
        self.assertEqual(world.hazards.snapshot(),())

    def test_multiple_bulbs_refresh_one_tile_without_stacking(self):
        world=playing(definition((1,'bulb',0,6),(2,'bulb',0,7)))
        for _ in range(4):perform_action(world,'shot',0)
        self.assertEqual(world.hp,95);self.assertEqual(len(world.hazards.snapshot()),1)

    def test_tile_refresh_during_ability_preserves_earned_damage_and_new_duration(self):
        world=playing(definition((1,'bulb',0,6)))
        perform_action(world,'shot',0)
        world.place_poison_tile(0)
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,100)  # Application Turn 2 is grace.
        # The earned Turn 3 hit survives Bulb's same-phase refresh.
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,95)
        self.assertEqual(world.hazards.snapshot()[0].remaining_turns,2)
        perform_action(world,'shot',0);self.assertEqual(world.hp,90)

    def test_levitation_blocks_real_bulb_tile_before_ward(self):
        world=playing(definition((1,'bulb',0,6)))
        for _ in range(3):perform_action(world,'shot',0)
        world.apply_status(StatusKind.WARD)
        perform_action(world,'levitation',0)
        self.assertEqual((world.hp,world.mp),(100,80))
        self.assertTrue(any(e.kind is StatusEventKind.LEVITATION_BLOCKED for e in world.status_events))
        self.assertFalse(any(e.kind is StatusEventKind.WARD_BLOCKED for e in world.status_events))
        self.assertEqual(world.hazards.snapshot()[0].remaining_turns,1)

    def test_ward_blocks_cactuar_needles_but_levitation_does_not(self):
        for spell,expected in (('ward',100),('levitation',95)):
            world=playing(definition((1,'cactuar',0,3)))
            perform_action(world,spell,3)
            self.assertEqual(world.hp,expected)

    def test_chichu_far_poison_grace_refresh_ticks_and_close_attack_boundary(self):
        world=playing(definition(boss=(100,7,6)))
        for turn in range(1,5):
            perform_action(world,'shot',0)
            self.assertEqual(world.hp,100-3*(turn-1))
            poison=world.statuses.get(StatusKind.POISON)
            self.assertEqual((poison.remaining_turns,poison.applied_turn),(3,turn))
        self.assertEqual(world.enemies[100].grid_col,11)
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,73) # 91 - 15 sound - 3 poison
        self.assertEqual(world.statuses.get(StatusKind.POISON).remaining_turns,2)

    def test_chichu_close_attack_ward_and_reraise_use_unified_damage(self):
        world=playing(definition(boss=(100,11,6)))
        perform_action(world,'ward',0)
        self.assertEqual(world.hp,100)
        perform_action(world,'reraise',0)
        self.assertEqual((world.hp,world.mp),(85,20))
        # A lethal attack fixture verifies revival before terminal transition.
        world.hp=10
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,45) # sound revives to 50, then escape contact costs five
        self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertIsNone(world.statuses.get(StatusKind.RERAISE));self.assertTrue(world.reraise_used)

    def test_poison_from_chichu_can_revive_before_game_over(self):
        world=playing(definition(boss=(100,0,6)))
        perform_action(world,'reraise',0);world.hp=3
        perform_action(world,'shot',0)
        self.assertEqual(world.hp,50);self.assertIs(world.state,GameState.PLAYER_AIM)
        self.assertIsNone(world.statuses.get(StatusKind.RERAISE))

    def test_chichu_lethal_sound_stops_remaining_enemy_processing(self):
        world=playing(definition(boss=(100,11,6)))
        world.hp=15
        perform_action(world,'shot',0)
        self.assertIs(world.game_over_reason,GameOverReason.HP_DEPLETED)
        self.assertEqual((world.hp,world.enemies[100].grid_col),(0,11))

    def test_enemy_application_event_order_is_stable_across_insertion_order(self):
        def outcome(reverse):
            world=playing(definition((1,'morbol',0,6),(2,'bulb',0,7)))
            if reverse:world.combat.enemies=dict(reversed(tuple(world.enemies.items())))
            for _ in range(4):perform_action(world,'shot',0)
            return world.snapshot(),tuple(world.status_events)
        self.assertEqual(outcome(False),outcome(True))

    def test_stage_two_enemies_never_apply_doom(self):
        world=playing(definition((1,'morbol',0,6),(2,'bulb',0,7),(3,'alligator',1,5)))
        for _ in range(6):perform_action(world,'shot',0)
        self.assertFalse(any(e.status is StatusKind.DOOM for e in world.status_events))

    def test_every_new_kind_takes_exact_projectile_damage_and_disables_on_death(self):
        from src.projectile import FixedStepPhysics
        for kind in ('cactuar','alligator','bulb','morbol','landtrap','chichu'):
            enemy=Enemy(1,EnemyType(kind),4,3);combat=Combat({1:enemy})
            orb=Projectile.launch(1,(enemy.bounds.right+12,enemy.position[1]),(-1,0))
            physics=FixedStepPhysics()
            # The production physics callback synchronizes collision and Combat immediately.
            physics.advance(.05,[orb],target_provider=combat.targets,on_hit=combat.handle_hit)
            self.assertEqual(enemy.hp,enemy.max_hp-5,kind)
            combat.apply_damage(1,100,'fixture')
            self.assertEqual(enemy.hp,0);self.assertEqual(combat.targets(),())
            self.assertFalse(combat.apply_damage(1,100))
            self.assertEqual(len(combat.death_events),1)

    def test_fire_and_starstorm_damage_real_stage_two_targets(self):
        for spell,loss in (('fire',20),('starstorm',10)):
            world=playing(definition((1,'morbol',7,3),(2,'alligator',5,3)))
            result=world.execute_offensive_spell('cast',spell)
            self.assertTrue(result.valid)
            self.assertEqual(world.enemies[1].hp,max(0,18-loss))
            self.assertEqual(world.enemies[2].hp,12 if spell=='fire' else 2)
            self.assertEqual(world.turn_index,1)

    def test_bomb_damage_chichu_and_all_new_ordinary_kinds(self):
        for kind in ('cactuar','alligator','bulb','morbol','landtrap','chichu'):
            target=Enemy(2,EnemyType(kind),5,3)
            combat=Combat({1:Enemy(1,EnemyType.BOMB,4,3),2:target})
            combat.add_crystal(Crystal(3,5,3));combat.apply_damage(1,5)
            self.assertEqual(target.hp,max(0,target.max_hp-10))
            self.assertFalse(combat.crystals[3].collected);self.assertEqual(combat.pending_bp,0)

    def test_defense_failure_never_uses_reraise(self):
        world=playing(definition((1,'landtrap',13,6)))
        perform_action(world,'reraise',0)
        self.assertIs(world.game_over_reason,GameOverReason.DEFENSE_FAILED)
        self.assertEqual(world.hp,95)
        self.assertIsNotNone(world.statuses.get(StatusKind.RERAISE))

    def test_pause_and_render_frames_never_tick_real_enemy_effects(self):
        world=playing(definition((1,'morbol',0,6),(2,'bulb',0,7)))
        for _ in range(3):perform_action(world,'shot',0)
        world.pause();before=deepcopy(vars(world))
        for _ in range(10):world.advance_time(100);self.assertFalse(world.resolve_turn());world.snapshot()
        self.assertEqual(vars(world),before)
        world.resume();perform_action(world,'shot',0)
        self.assertEqual(world.hp,92)
        before=deepcopy(vars(world));self.assertFalse(world.resolve_turn());self.assertEqual(vars(world),before)


if __name__=='__main__':unittest.main()
