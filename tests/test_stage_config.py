"""Strict JSON schema, prototype compatibility, and future boss reservations."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from config.prototype import PROTOTYPE
from src.combat import Combat
from src.encounter import Encounter, EncounterOutcome
from src.stage_config import StageConfigurationError, load_stage, parse_stage
from src.world import World


ROOT = Path(__file__).resolve().parent.parent


def stage_data(stage=1):
    return {"schema_version": 1, "stage": stage,
            "waves": [{"turn": 1, "spawns": [
                {"id": 1, "kind": "basic", "col": 0, "row": 3},
                {"id": 2, "kind": "crystal", "col": 0, "row": 3}]}],
            "completion": {"mandatory_enemy_ids": [1], "final": stage == 3}}


class StageConfigTests(unittest.TestCase):
    def reject(self, data, text=None):
        with self.assertRaises(StageConfigurationError) as caught:
            parse_stage(data)
        if text:
            self.assertIn(text, str(caught.exception))

    def test_loads_each_valid_stage_number_with_immutable_records(self):
        for stage in (1, 2, 3):
            result = parse_stage(stage_data(stage))
            self.assertEqual(result.stage, stage)
            self.assertEqual(result.final, stage == 3)
            self.assertEqual(result.mandatory_ids, (1,))
            with self.assertRaises(FrozenInstanceError):
                result.waves[0].spawns[0].col = 2

    def test_relative_loader_uses_module_directory_from_another_cwd(self):
        old = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(load_stage('prototype_01.json'), PROTOTYPE)
            finally:
                os.chdir(old)

    def test_absolute_fixture_file_loads_without_pygame_in_a_fresh_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps(stage_data()))
            env = os.environ | {'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, '-B', '-c',
                'from src.stage_config import load_stage; import sys; '
                'assert load_stage(sys.argv[1]).stage == 1; assert "pygame" not in sys.modules',
                str(path)], cwd=directory, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_file_invalid_path_and_relative_escape_are_informative(self):
        for value in ('does_not_exist.json', '../prototype.py', '', 1, None):
            with self.subTest(path=value), self.assertRaises(StageConfigurationError):
                load_stage(value)

    def test_malformed_duplicate_key_nonstandard_constant_and_bad_encoding_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for payload in (b'{', b'{"stage":1,"stage":2}', b'{"x":NaN}', b'\xff'):
                path.write_bytes(payload)
                with self.subTest(payload=payload), self.assertRaises(StageConfigurationError) as caught:
                    load_stage(path)
                self.assertIn('bad.json', str(caught.exception))

    def test_missing_root_fields_are_rejected(self):
        for key in stage_data():
            data = stage_data()
            del data[key]
            self.reject(data, 'missing fields')

    def test_unknown_fields_at_every_schema_level_are_rejected(self):
        for location in ('root', 'wave', 'spawn', 'completion'):
            data = stage_data()
            target = {'root': data, 'wave': data['waves'][0],
                      'spawn': data['waves'][0]['spawns'][0], 'completion': data['completion']}[location]
            target['typo'] = 1
            self.reject(data, 'unknown fields')

    def test_nonobjects_and_nonstring_field_names_are_rejected(self):
        for value in (None, [], 1, True, 'stage', {1: 'bad'}):
            self.reject(value)

    def test_stage_schema_version_and_final_types_are_strict(self):
        for key, values in (('stage', (0, 4, True, 1.0, '1', None)),
                            ('schema_version', (0, 2, True, '1', None))):
            for value in values:
                data = stage_data(); data[key] = value
                self.reject(data)
        for value in (0, 1, 'false', None):
            data = stage_data(); data['completion']['final'] = value
            self.reject(data)

    def test_final_metadata_prevents_premature_victory_or_a_stage_four_dead_end(self):
        for stage, final in ((1, True), (2, True), (3, False)):
            data = stage_data(stage); data['completion']['final'] = final
            self.reject(data, 'Only Stage 3')

    def test_wave_collections_turns_and_entry_types_are_strict(self):
        for value in ([], {}, None, 1):
            data = stage_data(); data['waves'] = value
            self.reject(data)
        for value in (0, -1, True, 1.5, '1', None):
            data = stage_data(); data['waves'][0]['turn'] = value
            self.reject(data)
        for value in (None, [], 'wave'):
            data = stage_data(); data['waves'] = [value]
            self.reject(data)

    def test_wave_turn_order_requires_one_then_strict_increases(self):
        for turns in ((2,), (1, 1), (1, 5, 3)):
            data = stage_data()
            wave = data['waves'][0]
            data['waves'] = []
            for index, turn in enumerate(turns):
                copy = deepcopy(wave); copy['turn'] = turn
                for entry in copy['spawns']:
                    entry['id'] += index * 2
                data['waves'].append(copy)
            self.reject(data)

    def test_spawns_are_nonempty_and_require_every_field(self):
        for value in ([], None, {}, 'spawns'):
            data = stage_data(); data['waves'][0]['spawns'] = value
            self.reject(data)
        for key in ('id', 'kind', 'col', 'row'):
            data = stage_data(); del data['waves'][0]['spawns'][0][key]
            self.reject(data)

    def test_spawn_ids_coordinates_and_kinds_are_strict(self):
        bad = {'id': (0, -1, True, 1.0, [], '1'),
               'col': (-1, 14, True, .5, '0'), 'row': (-1, 8, True, .5, '3'),
               'kind': ('ultros', 'missing', [], None, 1)}
        for key, values in bad.items():
            for value in values:
                data = stage_data(); data['waves'][0]['spawns'][0][key] = value
                self.reject(data)

    def test_duplicate_ids_within_and_across_waves_are_rejected(self):
        data = stage_data(); data['waves'][0]['spawns'][1]['id'] = 1
        self.reject(data)
        data = stage_data(); extra = deepcopy(data['waves'][0]); extra['turn'] = 3
        data['waves'].append(extra)
        self.reject(data)

    def test_duplicate_enemy_cells_reject_but_enemy_crystal_sharing_is_valid(self):
        self.assertEqual(len(parse_stage(stage_data()).waves[0].spawns), 2)
        data = stage_data(); data['waves'][0]['spawns'][1]['kind'] = 'bomb'
        self.reject(data, 'distinct grid cells')

    def test_mandatory_ids_cannot_be_empty_duplicate_unknown_or_crystals(self):
        for value in ([], None, 'all', [True], [1, 1], [99], [2], [[]]):
            data = stage_data(); data['completion']['mandatory_enemy_ids'] = value
            self.reject(data)

    def test_crystal_only_configuration_has_no_valid_completion_path(self):
        data = stage_data(); data['waves'][0]['spawns'][0]['kind'] = 'crystal'
        self.reject(data)

    def test_capacity_is_optional_but_strict_when_present(self):
        self.assertIsNone(parse_stage(stage_data()).capacity)
        for value in (0, 113, True, None, 1.0, '25'):
            data = stage_data(); data['capacity'] = value
            self.reject(data)
        data = stage_data(); data['capacity'] = 25
        self.assertEqual(parse_stage(data).capacity, 25)

    def boss_data(self):
        data = stage_data()
        data['boss_wave'] = {'when': 'after_scripted_waves_cleared', 'spawns': [
            {'id': 3, 'kind': 'ultros', 'col': 0, 'row': 2},
            {'id': 4, 'kind': 'typhon', 'col': 0, 'row': 5}]}
        data['completion']['mandatory_enemy_ids'] += [3, 4]
        return data

    def test_future_boss_contract_validates_without_live_spawning(self):
        data = stage_data(3)
        data['boss_wave'] = {'when': 'after_scripted_waves_cleared', 'spawns': [
            {'id': 3, 'kind': 'odin', 'col': 0, 'row': 2}]}
        data['completion']['mandatory_enemy_ids'].append(3)
        definition = parse_stage(data)
        self.assertFalse(definition.playable)
        combat = Combat(); encounter = Encounter(definition)
        self.assertFalse(encounter.boss_wave_ready(combat))
        encounter.spawn_due(1, combat)
        self.assertFalse(encounter.boss_wave_ready(combat))
        combat.apply_damage(1, 5)
        self.assertTrue(encounter.boss_wave_ready(combat))
        self.assertIsNone(encounter.outcome(combat))
        self.assertEqual(encounter.spawn_due(2, combat), ())
        self.assertEqual(set(combat.enemies), {1})
        with self.assertRaisesRegex(ValueError, 'Unimplemented boss'):
            World(stages={1: PROTOTYPE, 3: definition})

    def test_boss_readiness_respects_mandatory_membership_without_treating_escapes_as_kills(self):
        for mandatory in (False, True):
            data = self.boss_data()
            data['waves'][0]['spawns'][0]['col'] = 13
            if not mandatory:
                data['completion']['mandatory_enemy_ids'] = [3, 4]
            encounter = Encounter(parse_stage(data)); combat = Combat()
            encounter.spawn_due(1, combat)
            combat.enemies[1].escape(1)
            self.assertEqual(encounter.boss_wave_ready(combat), not mandatory)
            self.assertEqual(combat.enemies[1].hp, 5)
            self.assertIs(encounter.outcome(combat), EncounterOutcome.FAILED if mandatory else None)

    def test_boss_metadata_types_fields_trigger_and_roster_stage_are_validated(self):
        for value in (None, {}, [], 'boss'):
            data = self.boss_data(); data['boss_wave'] = value
            self.reject(data)
        for field in ('when', 'spawns'):
            data = self.boss_data(); del data['boss_wave'][field]
            self.reject(data)
        data = self.boss_data(); data['boss_wave']['unknown'] = 1
        self.reject(data)
        for value in ('turn_5', 1, [], None):
            data = self.boss_data(); data['boss_wave']['when'] = value
            self.reject(data)
        for kind in ('basic', 'chichu', 'odin', 'unknown', []):
            data = self.boss_data(); data['boss_wave']['spawns'][0]['kind'] = kind
            self.reject(data)

    def test_boss_ids_cells_mandatory_membership_and_capacity_are_validated(self):
        for change in ('duplicate_id', 'duplicate_cell', 'optional_boss', 'capacity'):
            data = self.boss_data()
            if change == 'duplicate_id': data['boss_wave']['spawns'][0]['id'] = 1
            elif change == 'duplicate_cell': data['boss_wave']['spawns'][1]['row'] = 2
            elif change == 'optional_boss': data['completion']['mandatory_enemy_ids'] = [1]
            else: data['capacity'] = 1
            self.reject(data)

    def test_prototype_preserves_all_ids_positions_kinds_and_spawn_order(self):
        expected = (
            (1, ((1,'basic',2,3),(2,'bomb',3,3),(3,'bomb',4,3),(4,'basic',2,4),
                 (5,'basic',3,4),(6,'basic',4,4),(7,'crystal',10,3))),
            (3, ((8,'basic',2,2),(9,'bomb',3,2),(10,'bomb',4,2),(11,'basic',2,3),
                 (12,'basic',3,3),(13,'basic',4,3),(14,'crystal',9,2))),
            (5, ((15,'basic',2,4),(16,'bomb',3,4),(17,'bomb',4,4),(18,'basic',2,5),
                 (19,'basic',3,5),(20,'basic',4,5),(21,'crystal',8,4))),
            (7, ((22,'basic',2,3),(23,'bomb',3,3),(24,'bomb',4,3),(25,'basic',2,4),
                 (26,'basic',3,4),(27,'basic',4,4),(28,'crystal',11,3))),
        )
        actual = tuple((wave.turn, tuple((s.entity_id,s.kind,s.col,s.row) for s in wave.spawns))
                       for wave in PROTOTYPE.waves)
        self.assertEqual(actual, expected)
        self.assertEqual(PROTOTYPE, load_stage('prototype_01.json'))
        self.assertEqual(len(PROTOTYPE.mandatory_ids), 24)
        self.assertIsNone(PROTOTYPE.capacity)
        self.assertIsNone(PROTOTYPE.boss_wave)
        self.assertFalse(PROTOTYPE.final)


if __name__ == '__main__':
    unittest.main()
