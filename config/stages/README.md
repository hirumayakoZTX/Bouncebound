# Stage configuration format

The application registers three canonical JSON encounters:

| File | Stage | Scripted waves | Ordinary enemies | Crystals | Final encounter |
|---|---:|---:|---:|---:|---|
| `stage_01.json` | 1 | 5, Turns 1/3/5/7/9 | 28 | 5 | Octopus and Hurricane |
| `stage_02.json` | 2 | 6, Turns 1/4/7/10/13/16 | 29 | 6 | Seedling |
| `stage_03.json` | 3 | 7, Turns 1/4/7/10/13/16/19 | 39 | 7 | Iron Knight |

`prototype_01.json` is retained as a historical four-wave fixture. It is not
the application's default encounter. The default game starts from
`stage_01.json` and does not load later files dynamically.

Load a canonical definition with `src.stage_config.load_stage("stage_01.json")`.
Relative names resolve against this directory, independent of the current
working directory. Loading does not initialize Pygame. Parsed definitions and
their nested records are immutable.

## Version 1 schema

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

- Required root fields are `schema_version`, `stage`, `waves`, and `completion`.
  `capacity` and `boss_wave` are optional. Unknown or duplicate fields are
  rejected at every level.
- Schema version is exactly integer `1`; stage is integer 1–3. Boolean and
  fractional substitutes are rejected.
- Waves are a nonempty ordered list. The first trigger is Turn 1; later trigger
  turns must strictly increase. Each wave contains exactly `turn` and `spawns`.
- Each spawn contains exactly a positive unique integer `id`, supported `kind`,
  and integer `col` / `row`. Columns range 0–13 and rows 0–7.
- Stage 1 ordinary kinds are `basic`, `bomb`, and `crystal`. Stage 2 adds
  `needleling`, `marshmaw`, `sporebud`, `mawroot`, and `snaproot`; Stage 3 adds
  `rootling`, `venomcrawler`, `hooded_stalker`, and `thorn_sentinel`. Bosses are
  configured only in their stage-specific boss waves and cannot appear as
  ordinary wave entries.
- Enemy cells cannot repeat within a wave; crystals may share an enemy cell.
  Occupied cells and full capacity defer eligible entries without overwriting
  active enemies. Capacity, when provided, is an integer from 1 through 112.
- Completion contains exactly `mandatory_enemy_ids` and boolean `final`.
  Mandatory IDs must reference enemies, not crystals. Mandatory escapes cause
  defense failure and never count as defeats. Stage 3 is final; Stages 1 and 2
  are not.

Malformed JSON, duplicate JSON keys, nonstandard constants, missing files,
invalid positions, impossible capacities, invalid IDs, unknown kinds, and
incompatible boss definitions raise `StageConfigurationError`.

## Boss-wave contract

An optional boss wave has `when: "after_scripted_waves_cleared"`, ordered
`spawns`, and optional `escape_policy: "contact_and_fail"`. Boss IDs share the
encounter's unique ID namespace and must be mandatory. Boss cells must be
distinct and the complete group must fit the configured capacity.

World activates a boss group only after every scripted entry has spawned, every
mandatory scripted enemy is defeated, no ordinary enemy remains active, no
required escape has failed the encounter, and the action boundary is safe.
Capacity, occupancy, pending combat, and ID conflicts are checked before any
boss object or spawn history is published. Bosses spawn together exactly once
and take no action on their arrival boundary. Rendering, pause, and active
projectile/spell animations cannot spawn them.

Stage 1 bosses each have 15 HP and deal 5 damage per surviving phase. Seedling
has 30 HP; it applies three-turn Poison while distant, otherwise deals 15 direct
damage. Iron Knight has 50 HP and repeats two 40-damage Slashes followed by a
50-damage Heavy Blow. All three attacks use ordinary damage resolution, so
Ward can block one event. Heavy Blow is not an instant knockout.

## Stage and wave lifecycle

Scheduled waves retain their configured order and turns while enemies remain.
When an authorized action and the complete enemy phase leave no active enemy,
World may advance the next ordinary wave at that safe boundary. At most one
future wave is accelerated per boundary, and a wave already spawned early is
not repeated at its scheduled turn. This does not skip the final ordinary wave
or boss eligibility.

An authorized clear is issued by the shared turn resolver after the action's
effects settle and before another enemy phase. A nonfinal clear advances only
to a registered next stage. Stage 3 enters Victory and then Results. Each stage
attempt starts at Turn 1 with 100 HP, 100 MP, and 1 BP and fresh local combat,
wave, status, and cooldown state. Stage retry restarts the failed stage from
Wave 1; campaign restart returns to Stage 1.

## Enemy effects in the current ruleset

Poison is the only harmful status. It deals 3 HP per eligible phase, has an
application grace phase, refreshes without stacking, and can be removed by
Cleanse. Ward blocks one ordinary positive damage event. There are no floor
hazards or revival effects.

The Cactus adjusts its row toward the player and attacks when aligned. The Alligator
attacks every third surviving phase. The Bigmouth Flower applies Poison every third phase.
The Seedling applies Poison at long range and deals direct damage nearby.
The Mite applies Poison every second surviving phase. The Greenberry becomes
enraged after actual positive HP loss and retaliates for 3 damage on each later
surviving phase. The Bulb, Snap Plant, Root Plant, and Thorn Snake use standard
movement. All abilities use the normal enemy phase and stop after death or
escape.
