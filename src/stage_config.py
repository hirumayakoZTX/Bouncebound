"""Strict version-1 JSON encounter loading, independent of Pygame and the shell CWD."""

from collections.abc import Mapping
import json
from pathlib import Path

from src.encounter import BossSpawn, BossWave, EncounterDefinition, Spawn, Wave


STAGE_DIRECTORY = Path(__file__).resolve().parent.parent / "config" / "stages"


class StageConfigurationError(ValueError):
    """A missing, malformed, unsupported, or inconsistent stage definition."""


def _object(value: object, required: set[str], optional: set[str], location: str) -> dict:
    if type(value) is not dict:
        raise StageConfigurationError(f"{location}: expected an object")
    if any(type(key) is not str for key in value):
        raise StageConfigurationError(f"{location}: field names must be strings")
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise StageConfigurationError(f"{location}: missing fields {sorted(missing)}")
    if unknown:
        raise StageConfigurationError(f"{location}: unknown fields {sorted(unknown)}")
    return value


def _array(value: object, location: str) -> list:
    if type(value) is not list or not value:
        raise StageConfigurationError(f"{location}: expected a nonempty array")
    return value


def _spawn(value: object, location: str, *, boss: bool = False) -> Spawn | BossSpawn:
    data = _object(value, {"id", "kind", "col", "row"}, set(), location)
    try:
        model = BossSpawn if boss else Spawn
        return model(data["id"], data["kind"], data["col"], data["row"])
    except ValueError as error:
        raise StageConfigurationError(f"{location}: {error}") from error


def parse_stage(data: object) -> EncounterDefinition:
    """Validate decoded JSON, including live Stage 1 and reserved future boss metadata."""
    root = _object(data, {"schema_version", "stage", "waves", "completion"},
                   {"capacity", "boss_wave"}, "stage")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise StageConfigurationError("schema_version: only integer version 1 is supported")
    waves = []
    for index, value in enumerate(_array(root["waves"], "waves")):
        location = f"waves[{index}]"
        wave = _object(value, {"turn", "spawns"}, set(), location)
        spawns = tuple(_spawn(entry, f"{location}.spawns[{spawn_index}]")
                       for spawn_index, entry in enumerate(_array(wave["spawns"], location + ".spawns")))
        try:
            waves.append(Wave(wave["turn"], spawns))
        except ValueError as error:
            raise StageConfigurationError(f"{location}: {error}") from error
    completion = _object(root["completion"], {"mandatory_enemy_ids", "final"}, set(), "completion")
    mandatory = tuple(_array(completion["mandatory_enemy_ids"], "completion.mandatory_enemy_ids"))
    capacity = root.get("capacity")
    if "capacity" in root and type(capacity) is not int:
        raise StageConfigurationError("capacity: expected an integer, not null or a boolean")
    boss_wave = None
    if "boss_wave" in root:
        boss = _object(root["boss_wave"], {"when", "spawns"}, {"escape_policy"}, "boss_wave")
        boss_spawns = tuple(_spawn(entry, f"boss_wave.spawns[{index}]", boss=True)
                            for index, entry in enumerate(_array(boss["spawns"], "boss_wave.spawns")))
        try:
            boss_wave = BossWave(boss["when"], boss_spawns,
                                 boss.get("escape_policy", "contact_and_fail"))
        except ValueError as error:
            raise StageConfigurationError(f"boss_wave: {error}") from error
    try:
        return EncounterDefinition(root["stage"], tuple(waves), mandatory, capacity,
                                   boss_wave, completion["final"])
    except ValueError as error:
        raise StageConfigurationError(f"stage: {error}") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise StageConfigurationError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise StageConfigurationError(f"Nonstandard JSON constant: {value}")


def load_stage(path: str | Path) -> EncounterDefinition:
    """Relative paths resolve under config/stages; absolute paths support local fixtures."""
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise StageConfigurationError("Stage path must be a nonempty string or Path")
    source = Path(path)
    if not source.is_absolute():
        source = (STAGE_DIRECTORY / source).resolve()
        if not source.is_relative_to(STAGE_DIRECTORY):
            raise StageConfigurationError("Relative stage paths must stay inside config/stages")
    try:
        data = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
        return parse_stage(data)
    except (OSError, UnicodeError, ValueError) as error:
        raise StageConfigurationError(f"{source}: {error}") from error


def validate_stage_registry(stages: Mapping[int, EncounterDefinition]) -> dict[int, EncounterDefinition]:
    """Copy an explicitly supplied catalog; unimplemented bosses cannot enter live play."""
    if not isinstance(stages, Mapping) or not stages or 1 not in stages:
        raise StageConfigurationError("Stage registry requires a Stage 1 definition")
    for stage, definition in stages.items():
        if (type(stage) is not int or not isinstance(definition, EncounterDefinition)
                or stage != definition.stage):
            raise StageConfigurationError("Stage registry keys must match validated stage numbers")
        if not definition.playable:
            raise StageConfigurationError("Unimplemented boss kinds cannot be registered for live play")
    return dict(stages)
