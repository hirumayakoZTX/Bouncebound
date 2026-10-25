# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a main menu, stage introduction,
a complete five-wave Stage 1 with vertical movement, mouse aiming, ricocheting
orbs, Basic Slimes, Bomb chain reactions, BP crystals, enemy turns, player damage,
Ultros and Typhon, stage clear, defeat, restart, pause/resume, and turn-based spells.

## Requirements

- Python 3.11 or later.
- Pygame 2.6.1 (the only third-party dependency).
- A desktop display on macOS or Windows.

The application uses a 960 × 576 window with a 60 FPS cap, Pygame's bundled
default font, procedural colors, and silence.
No external images, sounds, asset folders, or online services are needed to run.

## Install and run

Run commands from the repository root. Dependency installation needs package
access; the application itself runs offline. Verify that the selected Python
version is at least 3.11 before creating the virtual environment.

macOS:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Windows PowerShell:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` directly in
place of `python` for installation, execution, and tests.

A window titled **Bouncebound: Familiar Defense** opens at the main menu.
Audio hardware is not initialized or required.

## Controls and current functionality

- **Enter** at the menu starts a fresh run and shows the stage introduction.
- **Enter** at the introduction opens the placeholder battlefield.
- **W / Up Arrow** and **S / Down Arrow** move one row up and down while aiming.
- **Move the mouse inside the arena** to preview the initial firing direction.
- **Left-click inside the arena** to fire the current BP number of orbs as one volley.
- **1–8** while aiming select an unlocked spell: **1 Fire**, **2 Starstorm**,
  **3 Meteor**, **4 Cure**, **5 Esuna**, **6 Levitation**, **7 Ward**, **8 Reraise**.
- **Space** attempts to cast the selected spell. Selection is free; a valid spell
  or shot consumes one player turn. Invalid casts spend no MP and consume no turn.
  Locked selection preserves the previously selected spell.
- **Escape** at the battlefield pauses; press it again to resume.
- **Escape** at the menu exits. The window close button exits from any screen.
- **R** at Stage Clear or Game Over restarts the entire run at the introduction.
  Restart is disabled during active gameplay. Enter does not leave Stage Clear.

New runs begin at Stage 1, Turn 1, with HP 100/100, MP 100/100, and BP 1.
HP tracks player health; MP pays spell costs and does not regenerate passively.
BP controls the number of orbs per shot. Only Stage 1 is currently playable.
Fire, Starstorm, Cure, Ward, and Reraise are unlocked. Esuna and Levitation require
Stage 2; Meteor requires Stage 3, which are not playable yet.

| Key | Stage 1 spell | MP | Cooldown | Effect |
|---|---|---:|---:|---|
| 1 | Pom Fire | 30 | 3 | 20 damage to the nearest enemy in the player's row |
| 2 | Pom Starstorm | 40 | 4 | 10 damage in a radius-96 area centered eight cells left |
| 4 | Pom Cure | 10 | 1 | Restore up to 50 HP; requires missing HP |
| 7 | Pom Ward | 30 | 3 | Negate one ordinary damage event during the cast's enemy phase |
| 8 | Pom Reraise | 50 | 99 | Next knockout restores 50 HP; cast once per encounter |

Cooldowns use player turns: Fire cast on Turn 1 is ready again on Turn 5.
Offensive spell deaths use the same Bomb chains as orbs; spells do not collect
crystals. The HUD shows the selection, MP cost, next ready turn, availability,
feedback, and active statuses. Spells resolve their effects once, show a short
procedural effect, then use the same enemy phase as shooting.
The player starts on row 3 of eight rows at a fixed horizontal position. Movement
stays within the grid; aiming is restricted to the arena to the player's left.
The preview is a straight line and disappears when the cursor moves outside the
arena. Movement, aiming, and spell selection do not advance turns or spend resources.
Pausing ignores gameplay input and freezes active orbs or spell animation time;
resuming preserves the previous state. Shots lock their direction. Once a shot
or spell succeeds, additional shooting and casting are ignored until the next
turn. BP is not spent. Invalid casts leave movement, shooting, and selection
available.

Orbs travel at 520 pixels/second, bounce within the arena with a 7-pixel radius,
and expire after 5 simulated seconds or 12 damaging target hits. Each shot uses a
symmetric fan, normally spaced 5 degrees apart. Near-vertical aims compress the
fan symmetrically so every orb continues to launch leftward.

Green Slimes and red Bombs each have 5 HP. An orb hit deals 5 damage. A defeated
Bomb deals 10 damage to enemies in the eight neighboring grid cells and can
trigger another Bomb. Explosions do not damage the player or collect crystals.
Dead enemies disappear and immediately stop blocking orbs.

Blue crystals are non-reflecting: orbs pass through them without damage or a hit
count cost. Each crystal queues +1 BP once, applied only after the entire shot
finishes, up to BP 5. New BP affects the next shot, never the orbs already flying.

Stage 1 loads `config/stages/stage_01.json`. The [stage configuration format](config/stages/README.md)
documents validation and scheduling. Only Stage 1 is installed. The historical
`prototype_01.json` remains available for regression fixtures and is not the
application's default encounter.

Five scripted waves gradually expand the Bomb clusters and introduce different
rows. Each wave includes one blue crystal:

| Spawn turn | Enemies | Primary firing row (0–7) |
|---:|---:|---:|
| 1 | 4 | 3 |
| 3 | 5 | 2 |
| 5 | 6 | 4 |
| 7 | 6 | 1 |
| 9 | 7 | 5 |

There are 28 ordinary enemies and five crystals. The first wave appears when
entering the battlefield. Later entries spawn after the enemy phase and turn
increment. Occupied cells and the 25-active-enemy capacity defer individual
entries safely; crystals do not count toward capacity. A partially deferred wave
is not counted as complete, and retries never overwrite actors or duplicate IDs.

After every orb or spell animation and combat effect finishes, surviving enemies
take one phase, then the turn increases once and aiming resumes. Movement,
aiming, selection, and invalid shots or casts never trigger an enemy phase.
Empty turns still need a valid shot or spell. An empty ordinary battlefield does
not clear the stage while future entries or the boss group remain pending.

Ultros (purple, **U**) and Typhon (gold, **T**) each have **15 HP**. They appear
together at column 7, rows 2 and 5, after every scripted entry has spawned and all
required ordinary enemies have been defeated. The atomic boss group spawns at a
safe turn boundary, respecting cells and capacity. Neither attacks on arrival;
survivors act after the next completed player action. Boss HP is shown in each
cell; the HUD indicates pending or surviving bosses.

Each surviving boss deals **5 direct damage every enemy phase**, then attempts
one column forward. This simple attack cadence is this game's rule. Boss damage
uses the same Ward and Reraise resolution as other ordinary damage. Bosses can
receive orb damage, Fire, Starstorm, and adjacent Bomb explosions. A 20-damage
Fire can defeat a full-HP boss; Starstorm deals 10, leaving 5 HP. Spells and
explosions do not collect crystals. No resource or cooldown reset occurs at the
boss group's arrival: it is part of the same Stage 1 encounter.

Enemies act in ascending ID order, then attempt one column forward in their
current row. A cell occupied by another active enemy blocks movement; a cell
vacated by an earlier ID is available immediately. Crystals do not block enemies.
When they share a cell, the crystal appears as a small blue corner marker.

An enemy attempting to leave column 13 deals 5 contact damage and escapes. A
boss also follows this contact/removal rule, in addition to its scheduled attack
that phase. Escaped enemies do not explode or count as defeated. Ward negates
one eligible ordinary damage event; Reraise consumes its active revival and
restores exactly 50 HP on a real knockout. Otherwise HP zero ends the run with
"Player HP depleted".

Defeat all 28 required ordinary enemies and **both bosses** to reach Stage Clear
after the final action, before another enemy phase or harmful status processing.
Crystals do not have to be collected. If a mandatory enemy escaped, successful
clear is impossible and the bosses do not activate from a failed ordinary wave.
Once scheduled spawning finishes and no active enemies remain, the run ends with
"Defense failed" while preserving remaining HP. An escaped boss also prevents a
successful clear.

The end screen shows stage, turn, HP, MP, and BP. Press R to reset resources,
position, aiming, projectiles, spell history, statuses, hazards, enemies, crystals,
boss activation, IDs, and all wave history, then Enter to play again. R is disabled
during active turns. Stage Clear does not advance into an unfinished Stage 2.
There are no playable Stage 2 or Stage 3 encounters.

The orb travels naturally across the launch gap. Top and bottom bounce planes
extend across that gap; the right wall activates once the whole orb fits inside
the arena. Simultaneous wall-corner contacts reverse both velocity components.
Physics uses 1/120-second steps, capped at 30 steps per frame. Frame time above
0.25 seconds is discarded to bound work during stalls, so simulation slows under
severe stalls instead of accumulating a catch-up backlog.

## Verify

With the virtual environment active:

```bash
python -m unittest discover -s tests -v
git diff --check
```

The tests select SDL's dummy video driver and need no visible display. They cover
imports, display initialization, resolution/title, event handling, the frame cap,
shutdown, startup without project assets, scene transitions, reset, pause/resume,
player movement boundaries, aim validation, swept target/wall collisions,
projectile lifetime, frame-rate independence, enemy damage, deterministic Bomb
chains, immediate target removal, crystal collection, deferred BP, multi-orb
direction/speed, and rendering without changing run data.
They also cover complete turn cycles, occupied cells, defense-line escape,
contact damage, defeat, pause/resume of pending phases, and duplicate resolution.
Prototype checks cover configuration validation, spawn deferral, all three end
outcomes, normal-play success and defeat, and repeated restarts.
Spell tests also cover all eight definitions, targeting, payment idempotency,
turn-based cooldowns, offensive/support effects, statuses, hazards, revival,
posted numeric/Space input, shared action ownership, animation pause timing,
read-only HUD rendering, and restart cleanup. Higher-stage tests use isolated
model fixtures; they do not make later stages playable.
The automated suite does not verify physical desktop input or platform compatibility.

Manual smoke test: run `python main.py`, confirm the 960 × 576 menu, then press
Enter twice. Confirm Stage 1, Turn 1, HP/MP 100, BP 1, and five scripted waves.
Test W/S, arrow keys, mouse aiming, and Escape pause/resume. Full-HP Cure must be
rejected without MP or turn loss. Keys 3, 5, and 6 must show "Spell locked".

A reproducible **shooting-only clear** from a fresh run uses horizontal leftward
shots from these rows on Turns 1 through 11 (rows are numbered 0–7):

**3, 3, 2, 2, 4, 4, 1, 1, 5, 2, 5**

Aim at the arena's left edge on the player's row and left-click each turn. The
first nine volleys clear the ordinary waves and earn BP 5. On Turn 10, Ultros and
Typhon should both appear with 15 HP. The row-2 volley defeats Ultros; Typhon
attacks once. The row-5 volley defeats Typhon and reaches Stage Clear on Turn 11
at **HP 95, MP 100, BP 5**. Final enemy attacks must not occur after the clear.
Press R and Enter to verify fresh canonical waves, resources, and no old bosses.

For a **spell-and-shot clear**, use the same first nine shots, then:

1. Turn 10: move to row 2, press **1**, then **Space** for Fire. Ultros dies;
   Typhon attacks, leaving HP 95 and MP 70. Pause/resume the spell animation.
2. Turn 11: move to row 5, press **2**, then **Space** for Starstorm. Typhon falls
   to 5 HP, then attacks, leaving HP 90 and MP 30.
3. Turn 12: shoot horizontally from row 5. The orb hit finishes Typhon and clears
   Stage 1 at **HP 90, MP 30, BP 5**. Pause/resume during the volley as another check.

Additional clicks or Space presses during either animation must not add actions.
Fire's next ready turn after its Turn-10 cast is Turn 14; cooldowns do not tick
while paused. On Turn 12, before the final volley, selecting Reraise with only 30 MP must show
"Not enough MP" and leave shooting available. Cure heals missing HP, Ward blocks one damage event,
and Reraise provides one revival per encounter; each valid cast consumes one main
action. To repeat with full MP, finish the encounter and press R at its terminal
screen, or close and relaunch. Pressing R during active play does not restart.

For **HP-based defeat**, shoot horizontally from row 0 every turn. This reaches
Game Over on Turn 19 with HP 0. For **defense failure with HP remaining**, shoot
from row 0 for Turns 1–12, then rows **1, 4, 1** on Turns 13–15. This ends on Turn
15 with "Defense failed", **HP 85**, and no boss activation. These use ordinary
controls without changing model resources. Restart after both outcomes and check
that the first wave returns. Close the window, and separately test Escape from
the menu, confirming clean exit without a traceback.

## Repository layout

```text
main.py                 Application entry point
README.md               Setup and verification
LICENSE                 Project license
requirements.txt        Pinned runtime dependency
.gitignore              Local/generated file exclusions
src/
  __init__.py           Application package
  constants.py          Display and battlefield geometry
  collision.py          Swept circle/rectangle geometry and target bounds
  combat.py             Enemy damage, queued Bomb chains, and deferred BP
  demo.py               Static combat regression fixture
  encounter.py          Validated waves, spawn deferral, and encounter outcomes
  stage_config.py       Strict JSON loader and explicit stage registry validation
  entities.py           Grid enemies, Stage 1 boss attacks, crystals, and snapshots
  game.py               Window, loop, events, and shutdown
  renderer.py           Asset-free scene display
  states.py             Shared scene and turn-phase names
  turns.py              Stable enemy action, movement, and contact resolution
  world.py              Authoritative run, input, projectile, and scene controller
  projectile.py         Orb simulation, fixed steps, snapshots, and hit events
  player_actions.py     Immutable action authorization and spell HUD records
  spells.py             Spell definitions, targeting, validation, MP, and cooldowns
  offensive_spells.py   Offensive effects through shared combat
  support_spells.py     Healing, cleansing, and defensive grants
  statuses.py           Immutable statuses, timing, and processing events
  status_runtime.py     Ordered hazard, periodic damage, and countdown resolution
  hazards.py            Validated row-based PoisonTiles and refresh/expiry
assets/                 Asset directory (.gitkeep only; no assets required)
config/
  prototype.py          Compatible export of the provisional JSON encounter
  stages/
    stage_01.json       Complete Stage 1 (five waves, Ultros, and Typhon)
    prototype_01.json   Preserved historical four-wave regression fixture
    README.md           Public JSON schema and stage lifecycle contract
tests/
  test_bootstrap.py     Headless application checks
  test_encounter.py     Configuration, spawning, outcomes, and reset checks
  test_encounter_integration.py  End screens, input, and repeatable application runs
  test_world.py         Deterministic controller and transition tests
  test_scenes.py        Scene input and rendering checks
  test_player_input.py  Movement and aiming rules
  test_projectile.py    Geometry, ricochets, contact events, and timing
  test_collision_eligibility.py  Surface-contact and penetration regressions
  test_shooting.py      Shot lifecycle, pause, and application integration
  test_combat.py        Models, damage, death queues, explosions, and crystals
  test_combat_integration.py  Live target synchronization, BP fans, and demo
  test_turns.py         Enemy phases, contact damage, and defeat rules
  test_turn_integration.py  Consecutive turns, pause, defeat, and rendering
  test_bosses.py        Boss combat, defenses, and atomic group scheduling
  test_stage_one.py     Canonical gameplay, outcomes, rendering, and determinism
  test_stage_config.py  Strict stage schema and prototype compatibility
  test_stage_progression.py  Fixture stage transitions and scheduler boundaries
  test_spell_actions.py  Shared main-action economy and spell turn resolution
  test_spell_ui.py       Posted input, spell animation, HUD, and restart
  test_spell*.py         Spell definitions, validation, payment, and integration
  test_offensive*.py     Offensive damage and deterministic area/Bomb effects
  test_support*.py       Healing, cleansing, grants, and shared commit history
  test_status*.py        Status data, runtime timing, and application integration
  test_hazards.py        Floor placement, duration, and defensive precedence
```

Stage 2 and Stage 3 content, scoring, persistence, final artwork, and audio are not available.
