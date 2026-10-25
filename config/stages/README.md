# Stage configuration format

`stage_01.json` is the playable Stage 1: five waves on Turns 1/3/5/7/9 with
4/5/6/6/7 ordinary enemies, five crystals, then Ultros and Typhon. It is the only
application-registered encounter. Later-stage content remains unavailable.
`prototype_01.json` preserves the original four-wave, 24-enemy/four-crystal fixture
unchanged; select it explicitly for historical regressions.

Load the canonical definition with `src.stage_config.load_stage("stage_01.json")`.
Relative names resolve under this directory using the module location, independent
of the terminal's working directory. Absolute paths support local fixture files.
Loading and validation do not import Pygame or initialize a display.
`config.prototype.PROTOTYPE` remains the compatible immutable historical export.
World uses the canonical `stage_01.json` by default.

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

## Boss-wave contract

An optional `boss_wave` requires `when` and `spawns`, with optional `escape_policy`.
Its trigger is `after_scripted_waves_cleared`. Entries use the same four fields as
ordinary spawns. Stage 1 `ultros`/`typhon` are live boss kinds; Stage 2 `chichu` and
Stage 3 `odin` remain structurally valid reservations rejected by live registration.
Boss IDs share the encounter namespace and must all be mandatory. Boss cells must
be distinct and the complete group must fit capacity. `escape_policy` accepts only
`contact_and_fail`, also the compatibility default when omitted. Canonical Stage 1
sets it explicitly: a departing boss deals normal 5-HP contact damage, is archived
as escaped rather than killed, and prevents a successful clear. Its separate
5-damage scheduled attack occurs before movement/contact.

The canonical Stage 1 boss metadata is:

```json
{
  "when": "after_scripted_waves_cleared",
  "escape_policy": "contact_and_fail",
  "spawns": [
    {"id": 100, "kind": "ultros", "col": 7, "row": 2},
    {"id": 101, "kind": "typhon", "col": 7, "row": 5}
  ]
}
```

`Encounter.boss_wave_ready(combat)` reports readiness only after every scripted
entry spawned, every mandatory scripted enemy was defeated, and no ordinary enemy
remains active. Mandatory escapes never satisfy readiness. World invokes the same
scheduler at safe boundaries, after action/combat resolution and turn advancement.
The boss group is preflighted for capacity, cell occupancy, pending combat/BP, and
ID conflicts before any objects or history are published. Both spawn together,
exactly once, in configuration order. No boss attacks on arrival.

`boss_wave_spawned` records activation separately from scripted `spawned_waves`.
Completion requires actual activation and every mandatory boss defeated. An empty
ordinary battlefield never skips the boss group. Bosses have 15 HP, take the same
combat damage as other enemies, and attack for 5 before standard movement each
surviving enemy phase. Only real supported bosses can be registered; no fake
Chichu/Odin factories or later-stage configurations are installed.

## Stage lifecycle

World accepts an explicit `stages` mapping of stage numbers to validated, playable
`EncounterDefinition` records. The mapping must include Stage 1, keys must match
definitions, and World copies it. No later-stage files are discovered or installed
automatically. Small multi-stage configurations are used only by automated tests.

An authorized clear is issued by the shared turn resolver after a completed shot
or spell and before the enemy phase. `World.advance_stage()` requires that clear
and a registered configuration for exactly the next stage. Missing configurations
leave Stage Clear intact; they never create an empty battlefield. Enter can
acknowledge a next stage when one is registered. The default Stage 1 stays at
Stage Clear after both bosses are defeated, with R available to restart. The historical prototype also retains its Stage Clear.

Each stage starts a fresh encounter: HP/MP/BP become 100/100/1, the stage turn
returns to 1, and player position/aim, cooldowns, commit IDs, selection/feedback,
statuses, hazards, Reraise allowance, physics, projectiles, combat histories, and
wave scheduling reset. This fresh-clock and effect-reset policy is a project
choice alongside the fixed resource reset. IDs are scoped to each encounter.
The next stage's first wave appears when its introduction is acknowledged.

Final Stage 3 completion enters Victory; Enter can continue to Results. These
minimal states are exercised by fixtures only. R from Stage Clear, Game Over,
Victory, or Results resets the complete run to its configured Stage 1.
