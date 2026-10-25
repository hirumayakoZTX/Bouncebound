# Stage configuration format

`stage_01.json` is the playable Stage 1: five waves on Turns 1/3/5/7/9 with
4/5/6/6/7 ordinary enemies, five crystals, then Ultros and Typhon. It is one
of two application-registered encounters. `stage_02.json` provides six waves on
Turns 1/4/7/10/13/16, 29 ordinary enemies, six crystals, then Chichu. Stage 3 remains
unavailable.
`prototype_01.json` preserves the original four-wave, 24-enemy/four-crystal fixture
unchanged; select it explicitly for historical regressions.

Load the canonical definition with `src.stage_config.load_stage("stage_01.json")`.
Relative names resolve under this directory using the module location, independent
of the terminal's working directory. Absolute paths support local fixture files.
Loading and validation do not import Pygame or initialize a display.
`config.prototype.PROTOTYPE` remains the compatible immutable historical export.
World starts with canonical `stage_01.json` and explicitly registers `stage_02.json` next.

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
  `col`, and `row`. Stage 1 live ordinary kinds are `basic`, `bomb`, and `crystal`.
  Stage 2 additionally accepts `cactuar`, `alligator`, `bulb`, `morbol`, and
  `landtrap`. These five kinds are rejected in Stage 1; bosses cannot be ordinary entries.
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
ordinary spawns. Stage 1 `ultros`/`typhon` and Stage 2 `chichu` are live boss kinds.
Each is restricted to its own stage. Stage 3 `odin` remains a structurally valid
reservation rejected by live registration.
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
ID conflicts before any objects or history are published. Configured bosses spawn together,
exactly once, in configuration order. No boss attacks on arrival.

`boss_wave_spawned` records activation separately from scripted `spawned_waves`.
Completion requires actual activation and every mandatory boss defeated. An empty
ordinary battlefield never skips the boss group. Stage 1 bosses have 15 HP and attack for 5 each surviving phase. Chichu has
30 HP and acts once each phase: apply three-turn Poison beyond three columns
from the player lane (column 14), otherwise deal 15 sound damage. All bosses take
normal combat damage and then follow standard movement/contact. Odin remains
unimplemented and unavailable for live registration.

## Stage lifecycle

World accepts an explicit `stages` mapping of stage numbers to validated, playable
`EncounterDefinition` records. The mapping must include Stage 1, keys must match
definitions, and World copies it. No later-stage files are discovered or installed
automatically. The application explicitly registers Stages 1 and 2; additional
small configurations remain isolated test fixtures.

An authorized clear is issued by the shared turn resolver after a completed shot
or spell and before the enemy phase. `World.advance_stage()` requires that clear
and a registered configuration for exactly the next stage. Missing configurations
leave Stage Clear intact; they never create an empty battlefield. Enter can
acknowledge a next stage when one is registered. The default Stage 1 clear allows
Enter to Stage 2 Intro, then Enter starts its first wave. Stage 2 Clear waits for
R because Stage 3 is not registered. The historical prototype, selected as a
single encounter, retains its original Stage Clear and restart behavior.

Each stage starts a fresh encounter: HP/MP/BP become 100/100/1, the stage turn
returns to 1, and player position/aim, cooldowns, commit IDs, selection/feedback,
statuses, hazards, Reraise allowance, physics, projectiles, combat histories, and
wave scheduling reset. This fresh-clock and effect-reset policy is a project
choice alongside the fixed resource reset. IDs are scoped to each encounter.
The next stage's first wave appears when its introduction is acknowledged.

Final Stage 3 completion enters Victory; Enter can continue to Results. These
minimal states are exercised by fixtures only. R from Stage Clear, Game Over,
Victory, or Results resets the complete run to its configured Stage 1.

## Stage 2 encounter decisions

Six waves use 4/4/5/5/5/6 enemies and one crystal each. Scripted IDs are 201–235,
with crystals at 205/210/216/222/228/235; Chichu uses 300 at column 7, row 3.
All 30 enemies are mandatory; capacity is 25. The trigger, atomic group spawn,
occupied-cell deferral, escape failure, and completion guards are shared with
Stage 1. Neither the historical prototype nor canonical Stage 1 was changed.

The layout, trigger spacing, and six crystals are encounter choices. Ability
cadence counts each enemy's surviving phases; Cactuar takes one free row toward
the player, Bulb targets the current player row, and Chichu acts each surviving
phase with three-turn Poison at long range. Enemy-phase refresh preserves an
already-earned Poison/tile tick without stacking or shortening the new duration.
First application retains its grace phase. No Stage 2 enemy applies Doom.
