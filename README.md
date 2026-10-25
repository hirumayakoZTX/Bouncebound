# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a main menu, stage introduction,
scripted four-wave prototype with vertical movement, mouse aiming, ricocheting
orbs, Basic Slimes, Bomb chain reactions, BP crystals, enemy turns, player damage,
stage clear, defeat, restart, pause/resume, and turn-based offensive/support spells.

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
BP controls the number of orbs per shot. Only the Stage 1 prototype is playable.
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

The prototype contains 24 enemies in four waves of six, scheduled for Turns 1,
3, 5, and 7, with one blue crystal per wave. Adjacent Bombs can clear nearby
Slimes through chain reactions. The initial wave appears when entering the
battlefield; later waves spawn after the enemy phase and turn increment.
Occupied enemy cells defer spawns until a later turn boundary. Deferred entries
retain their IDs and retry in configuration order without overwriting enemies.
The HUD counts fully spawned waves; a partially deferred wave is not counted yet.

After every orb or spell animation and combat effect finishes, surviving enemies take one phase,
then the turn increases once and aiming resumes. Movement, aiming, and invalid
shots or casts never trigger an enemy phase. An empty arena remains playable while future
waves or deferred enemies are pending.

Enemies act in ascending ID order, then attempt one column forward in their
current row. A cell occupied by another active enemy blocks movement; a cell
vacated by an earlier ID is available immediately. Crystals do not block enemies.
When they share a cell, the crystal appears as a small blue corner marker.

An enemy attempting to leave column 13 deals 5 contact damage and escapes. An
escaped Bomb does not explode. Ward can negate one ordinary damage event. A
knockout consumes an active Reraise and restores exactly 50 HP; otherwise the
run ends with "Player HP depleted". If every wave has spawned and no required enemy remains
active, any escaped enemy ends the run with "Defense failed" and preserves the
remaining HP. Escapes never count as defeated enemies.

Defeat all 24 enemies to reach Stage Clear after the final action, before another
enemy phase. Crystals do not have to be collected to clear. The end screen shows
stage, turn, HP, and BP. Press R to reset resources, movement, aiming, projectiles,
events, enemies, crystals, IDs, the wave schedule, spell selection, cooldowns,
MP payment history, statuses, and hazards, then Enter to play again.
This prototype ends at Stage Clear; it has no bosses or later stages.

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
Enter twice to reach the battlefield. Confirm Stage 1, Turn 1, HP/MP 100, and BP 1.
Move with W/S and the arrow keys; confirm movement stops at the top and bottom
rows. Move the mouse inside the arena and confirm the aiming line follows the
player when moving; move outside and confirm the line disappears. Pause, try
moving/aiming, and resume; position and aim should be preserved. Turn and resources
must remain unchanged. Aim horizontally left from the initial row and left-click.
Confirm the crystal disappears and the first six enemies die in a Bomb chain.
Pause/resume during flight; orbs must freeze and continue from the same positions.
After expiry, confirm BP 2, unchanged HP/MP, and Turn 2 with aiming enabled again.

A reproducible clear uses horizontal shots from these rows on Turns 1 through 7:
**3, 3, 2, 2, 4, 4, 3** (rows are numbered 0 through 7). This should clear all
four waves with HP 100 and BP 5. Empty turns still require a normal shot. Confirm
Stage Clear, press R, and verify the fresh introduction and initial battlefield.

To check spells, restart and press 1 then Space on the initial row. Confirm the first Bomb chain, MP 70, a brief Pom Fire effect, and exactly one enemy phase. Press Space again on Turn 2: the cooldown message must consume no MP or turn.
Select 7 and cast Ward, pausing/resuming its animation with Escape. On the next turn, selecting 8 and casting Reraise should show "Not enough MP". Shooting must remain available. Keys 3, 5, and 6 should show "Spell locked".
To repeat the spell smoke test with full MP, finish the encounter and press R on the Stage Clear or Game Over screen. Alternatively, close and relaunch the application. Pressing R during an active turn does not restart the run.
For a clear ending with a spell, follow the seven-row shooting recipe above but cast Fire instead of shooting on Turn 7; the last crystal need not be collected.

For HP-based defeat, shoot horizontally from row 0 every turn. Enemies should
advance and escape; this reaches Game Over with HP 0. For defense failure with HP
remaining, miss from row 0 until the first escapes, then aim horizontally at the
remaining Bombs and Slimes until the board is empty. The reason must say defense
failed rather than HP depleted. Restart after defeat and confirm the first wave
and resources are restored. Close the window and confirm no traceback. Relaunch
and press Escape at the menu to confirm clean exit.

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
  encounter.py          Validated prototype waves, spawn scheduling, and outcomes
  entities.py           Plain grid enemy/crystal models and snapshots
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
  prototype.py          Four-wave prototype definition (24 enemies, four crystals)
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
  test_spell_actions.py  Shared main-action economy and spell turn resolution
  test_spell_ui.py       Posted input, spell animation, HUD, and restart
  test_spell*.py         Spell definitions, validation, payment, and integration
  test_offensive*.py     Offensive damage and deterministic area/Bomb effects
  test_support*.py       Healing, cleansing, grants, and shared commit history
  test_status*.py        Status data, runtime timing, and application integration
  test_hazards.py        Floor placement, duration, and defensive precedence
```

No bosses, later-stage progression, scoring, or persistence exists yet.
