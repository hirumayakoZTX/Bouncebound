"""Original spell catalog, targeting, payment, cooldown, and unlock rules."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import subprocess
import sys
import unittest

from src.entities import Enemy, EnemyType
from src.spells import SPELLS, SpellFailure, SpellId, TargetKind, get_spell
from src.states import GameState
from src.world import World


EXPECTED = {
    "ember_lance": ("Fire", 30, 3, 1),
    "mend": ("Cure", 10, 1, 1),
    "barrier": ("Ward", 30, 3, 1),
    "cleanse": ("Cleanse", 20, 3, 2),
    "skyfall": ("Meteor", 80, 10, 3),
}


def caster():
    world = World(demo=False)
    world.start_new_run()
    world.transition_to(GameState.PLAYER_AIM)
    world.hp = 75
    world.combat.add_enemy(Enemy(9, EnemyType.BASIC, 6, 3))
    return world


class SpellCatalogTests(unittest.TestCase):
    def test_catalog_contains_only_the_five_original_spell_names(self):
        self.assertEqual(len(SPELLS), 5)
        self.assertEqual({spell.value for spell in SpellId}, set(EXPECTED))
        for spell_id, expected in EXPECTED.items():
            definition = get_spell(spell_id)
            self.assertEqual((definition.name, definition.mp_cost,
                              definition.cooldown, definition.unlock_stage), expected)
        for removed in ("starstorm", "levitation", "reraise"):
            self.assertIsNone(get_spell(removed))

    def test_definitions_are_immutable_and_lookup_is_strict(self):
        with self.assertRaises(TypeError):
            SPELLS[SpellId.EMBER_LANCE] = get_spell("barrier")
        with self.assertRaises(FrozenInstanceError):
            get_spell("mend").mp_cost = 0
        for value in ("Fire", " ember_lance", "", None, True, 1, [], {}):
            self.assertIsNone(get_spell(value))

    def test_model_import_and_validation_do_not_initialize_pygame(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from src.world import World; World().validate_spell('barrier'); "
             "import sys; assert 'pygame' not in sys.modules"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class SpellValidationTests(unittest.TestCase):
    def test_stage_unlocks_and_locked_selection_preserves_previous_spell(self):
        world = caster()
        self.assertTrue(world.select_spell("ember_lance"))
        self.assertFalse(world.select_spell("cleanse"))
        self.assertIs(world.selected_spell, SpellId.EMBER_LANCE)
        self.assertIs(world.validate_spell("cleanse").failure, SpellFailure.STAGE_LOCKED)
        world.stage = 2
        self.assertTrue(world.select_spell("cleanse"))
        self.assertIs(world.selected_spell, SpellId.CLEANSE)
        self.assertIs(world.validate_spell("skyfall").failure, SpellFailure.STAGE_LOCKED)
        world.stage = 3
        self.assertTrue(world.validate_spell("skyfall").valid)

    def test_fire_selects_nearest_enemy_in_current_row(self):
        world = caster()
        world.combat.add_enemy(Enemy(3, EnemyType.BOMB, 10, 3))
        world.combat.add_enemy(Enemy(1, EnemyType.BASIC, 13, 2))
        result = world.validate_spell("ember_lance")
        self.assertEqual(result.cast.targets.enemy_ids, (3,))
        self.assertIs(result.cast.targets.kind, TargetKind.NEAREST_IN_ROW)
        self.assertEqual(world.enemies[3].hp, 10)

    def test_skyfall_targets_all_live_enemies_once_in_stable_id_order(self):
        world = caster()
        world.stage = 3
        world.combat.add_enemy(Enemy(2, EnemyType.BASIC, 3, 1))
        world.combat.add_enemy(Enemy(1, EnemyType.BOMB, 2, 2))
        world.enemies[1].take_damage(10)
        result = world.validate_spell("skyfall")
        self.assertEqual(result.cast.targets.enemy_ids, (2, 9))
        self.assertIs(result.cast.targets.kind, TargetKind.ALL_ENEMIES)

    def test_mend_requires_missing_hp_and_unknown_spell_is_free(self):
        world = caster()
        world.hp = 100
        before = deepcopy(vars(world))
        self.assertIs(world.validate_spell("mend").failure, SpellFailure.FULL_HP)
        self.assertEqual(vars(world), before)
        self.assertIs(world.validate_spell("removed").failure, SpellFailure.INVALID_SPELL)


class SpellPaymentTests(unittest.TestCase):
    def test_successful_commit_pays_once_and_uses_absolute_cooldown(self):
        world = caster()
        result = world.commit_spell("shot-1", "ember_lance")
        self.assertTrue(result.valid)
        self.assertEqual((world.mp, result.cast.next_ready_turn), (70, 5))
        before = deepcopy(vars(world))
        self.assertIs(world.commit_spell("shot-1", "ember_lance").failure,
                      SpellFailure.ALREADY_COMMITTED)
        self.assertEqual(vars(world), before)

    def test_failed_cast_does_not_pay_or_consume_action_id(self):
        world = caster()
        world.mp = 29
        self.assertIs(world.commit_spell("retry", "ember_lance").failure,
                      SpellFailure.INSUFFICIENT_MP)
        self.assertEqual(world.mp, 29)
        world.mp = 30
        self.assertTrue(world.commit_spell("retry", "ember_lance").valid)
        self.assertEqual(world.mp, 0)

    def test_cooldown_and_render_time_are_turn_based(self):
        world = caster()
        self.assertTrue(world.commit_spell("first", "ember_lance").valid)
        self.assertEqual(world.spells.next_ready_turn("ember_lance"), 5)
        for elapsed in (1 / 144, 1 / 60, 1 / 30, 100):
            world.advance_time(elapsed)
            self.assertEqual(world.spells.next_ready_turn("ember_lance"), 5)
        for turn in (1, 2, 3, 4):
            world.turn_index = turn
            self.assertIs(world.validate_spell("ember_lance").failure, SpellFailure.COOLDOWN)
        world.turn_index = 5
        self.assertTrue(world.validate_spell("ember_lance").valid)


if __name__ == "__main__":
    unittest.main()
