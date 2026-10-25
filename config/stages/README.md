# Stage configuration format

`prototype_01.json` is the provisional Stage 1 encounter: the original four waves,
24 enemies, four crystals, and unchanged spawn order. It is the only definition
registered by the application. Later stages and live bosses are not available.

Load definitions with `src.stage_config.load_stage("prototype_01.json")`.
Relative names resolve under this directory using the module location, independent
of the terminal's working directory. Absolute paths support local fixture files.
Loading and validation do not import Pygame or initialize a display.
`config.prototype.PROTOTYPE` remains the compatible immutable export.

Version 1 uses the following shape. This small example illustrates the format,
rather than replacing the shipped encounter:

```json
{
  "schema_version": 1,
  "stage": 1,
  "waves": [
    {
      "turn": 1,
      "spawns": [
        {"id": 1, "kind": "basic", "col": 0, "row": 3},
        {"id": 2, "kind": "crystal", "col": 0, "row": 3}
      ]
    }
  ],
  "completion": {"mandatory_enemy_ids": [1], "final": false},
  "capacity": 25
}
```

- Required root fields: `schema_version`, `stage`, `waves`, and `completion`.
  Optional root fields: `capacity` and `boss_wave`. Unknown fields at any level,
  duplicate JSON keys, and nonstandard numeric constants are errors.
- `schema_version` is integer 1. `stage` is an integer from 1 through 3.
  Boolean, string, and fractional substitutes for integer fields are rejected.
- `waves` is a nonempty array of objects containing exactly `turn` and `spawns`.
  The first turn is 1; subsequent trigger turns strictly increase.
- `spawns` is a nonempty ordered array. Each entry requires exactly `id`, `kind`,
  `col`, and `row`. Supported live kinds are `basic`, `bomb`, and `crystal`.
  IDs are positive integers, unique across all entries in the encounter.
  Columns range from 0 through 13; rows range from 0 through 7.
- Enemy cells cannot repeat within one wave. Crystals may share enemy cells.
  Occupied cells across waves defer individual enemy entries without overwriting.
- `capacity`, when present, is an integer from 1 through 112. It limits living,
  non-escaped enemies, not crystals or archived enemies. Omission preserves the
  previous behavior without an additional population limit. Full capacity defers
  enemies; crystals continue spawning. The shipped prototype omits this field.
- `completion` contains exactly `mandatory_enemy_ids` and `final`. Mandatory IDs
  form a nonempty, unique array referencing enemies, never crystals. Omitted or
  invalid completion metadata is rejected. All mandatory enemies must be defeated;
  a mandatory escape causes defense failure once spawning and active enemies finish.
  Optional ordinary enemies must also leave active play before a clear, but their
  escape does not count as a mandatory defeat or failure.
- `final` is a boolean. Only Stage 3 can be final, and Stage 3 must be final.
  Stages 1 and 2 end in Stage Clear rather than final Victory.

The scheduler retains configuration order, per-entry spawn history, and completed
wave tracking. A partially deferred wave is not complete. World permits spawning
only between resolved actions and never from rendering, pause, or animations.

## Future boss-wave contract

An optional `boss_wave` contains exactly `when` and `spawns`. Its trigger is
`after_scripted_waves_cleared`. Entries use the same four fields as ordinary
spawns, but reserve boss kinds: Stage 1 `ultros`/`typhon`, Stage 2 `chichu`, and
Stage 3 `odin`. Boss IDs share the encounter namespace and must all appear in
`mandatory_enemy_ids`. Boss cells must be distinct and the group must fit capacity.

For example, this metadata reserves the Stage 1 boss group; it is not a playable
boss configuration:

```json
{
  "when": "after_scripted_waves_cleared",
  "spawns": [
    {"id": 100, "kind": "ultros", "col": 0, "row": 2},
    {"id": 101, "kind": "typhon", "col": 0, "row": 5}
  ]
}
```

`Encounter.boss_wave_ready(combat)` reports readiness only after every scripted
entry spawned, every mandatory scripted enemy was defeated, and no ordinary enemy
remains active. Mandatory escapes never satisfy readiness. It does not
spawn bosses, claim reserved IDs, or allow premature completion. World rejects
registration of boss-bearing definitions until real spawning support exists.
There are no placeholder boss enemies or shipped boss encounters.

## Stage lifecycle

World accepts an explicit `stages` mapping of stage numbers to validated, playable
`EncounterDefinition` records. The mapping must include Stage 1, keys must match
definitions, and World copies it. No later-stage files are discovered or installed
automatically. Small multi-stage configurations are used only by automated tests.

An authorized clear is issued by the shared turn resolver after a completed shot
or spell and before the enemy phase. `World.advance_stage()` requires that clear
and a registered configuration for exactly the next stage. Missing configurations
leave Stage Clear intact; they never create an empty battlefield. Enter can
acknowledge a next stage when one is registered. The default prototype stays at
Stage Clear, with R available to restart.

Each stage starts a fresh encounter: HP/MP/BP become 100/100/1, the stage turn
returns to 1, and player position/aim, cooldowns, commit IDs, selection/feedback,
statuses, hazards, Reraise allowance, physics, projectiles, combat histories, and
wave scheduling reset. This fresh-clock and effect-reset policy is a project
choice alongside the fixed resource reset. IDs are scoped to each encounter.
The next stage's first wave appears when its introduction is acknowledged.

Final Stage 3 completion enters Victory; Enter can continue to Results. These
minimal states are exercised by fixtures only. R from Stage Clear, Game Over,
Victory, or Results resets the complete run to its configured Stage 1.
