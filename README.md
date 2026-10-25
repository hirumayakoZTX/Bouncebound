# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a main menu, stage introduction,
three complete playable stages with vertical movement, mouse aiming, ricocheting
orbs, Bomb chain reactions, BP crystals, enemy abilities, statuses, floor hazards,
Ultros, Typhon, Chichu, Odin, final Victory and Results, stage progression, defeat, restart, pause/resume, and spells.

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
- **Enter** after Stage 1/2 Clear opens the next stage introduction; Enter again
  starts that stage. Enter after final **Victory** opens **Results**.
- **R** at Stage Clear, Game Over, Victory, or Results restarts the entire run at
  Stage 1 Intro. Restart is disabled during active gameplay. Held Enter repeats
  do not skip introductions or acknowledge terminal screens.

New runs begin at Stage 1, Turn 1, with HP 100/100, MP 100/100, and BP 1.
HP tracks player health; MP pays spell costs and does not regenerate passively.
BP controls the number of orbs per shot. All three stages are playable.
Fire, Starstorm, Cure, Ward, and Reraise unlock in Stage 1. Stage 2 additionally
unlocks Esuna and Levitation. Stage 3 additionally unlocks Meteor.

| Key | Spell | MP | Cooldown | Effect |
|---|---|---:|---:|---|
| 1 | Pom Fire | 30 | 3 | 20 damage to the nearest enemy in the player's row |
| 2 | Pom Starstorm | 40 | 4 | 10 damage in a radius-96 area centered eight cells left |
| 3 | Pom Meteor (Stage 3) | 80 | 10 | 15 direct damage to every active enemy |
| 4 | Pom Cure | 10 | 1 | Restore up to 50 HP; requires missing HP |
| 5 | Pom Esuna (Stage 2) | 20 | 3 | Remove Poison and Bind; preserve Doom and beneficial effects |
| 6 | Pom Levitation (Stage 2) | 20 | 3 | Ignore floor damage during the cast's enemy phase |
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
documents validation and scheduling. Stage 2 loads `config/stages/stage_02.json`.
Stage 3 loads `config/stages/stage_03.json`. All three encounters are registered. The historical
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
during active turns. Enter after Stage 1 Clear opens Stage 2 Intro, then Enter
starts its first wave. Enter after Stage 2 Clear opens Stage 3 Intro, then Enter
starts Stage 3. Its final clear enters Victory; Enter continues to Results.

Each stage starts a fresh encounter: HP/MP/BP reset to 100/100/1, Turn returns to
1, and the player returns to row 3 with no aim. Cooldowns, spell selection and
committed action IDs, Reraise allowance, statuses, hazards, projectiles, animations,
enemy/crystal archives, pending actions, and wave/boss histories all reset.
Restart from either stage's end screen always returns to a fresh Stage 1.

### Stage 2

Six waves arrive on Turns **1, 4, 7, 10, 13, 16**, containing **4, 4, 5, 5, 5, 6**
ordinary enemies and one crystal each. All 29 ordinary enemies and Chichu are
mandatory. Bombs support chains against the tougher enemies; there are no
substitute Slimes in this encounter. Capacity remains 25 active enemies.

| Enemy / label | HP | Ability before forward movement |
|---|---:|---|
| Cactuar / C | 10 | Step one free row toward the player; deal 5 if then aligned |
| Alligator / A | 12 | Deal 4 on every third surviving enemy phase |
| Bulb / Bu | 8 | Every third surviving phase, place a two-phase PoisonTile on the player's row |
| Morbol / M | 18 | Every third surviving phase, apply Bind 1 and Poison 3 |
| Landtrap / L | 8 | Advance without an active attack |
| Chichu / Ch | 30 | Each phase: Poison 3 beyond three columns; otherwise 15 direct damage |

Each enemy advances at most one column after its ability, respecting occupied
cells. Vertical Cactuar moves obey the same occupancy rule and wait when blocked.
Ability cadence starts on each enemy's first surviving phase, not the global
stage turn. Chichu measures distance to the player lane at column 14: columns
0–10 use Poison; columns 11–13 use sound damage. All types retain 5 contact damage
on escape. Bosses and ordinary enemies use the same collision, spell, Bomb,
Ward, and Reraise systems.

Poison and newly placed tiles first damage on the phase after application.
Poison deals 3 per eligible phase.

PoisonTiles remain active for two eligible enemy phases after their application
phase. Their duration decreases during each eligible phase regardless of whether
the player occupies the affected row or is protected by Levitation. A tile deals
5 damage only when the player occupies that row and is not protected by
Levitation. Ward can block one otherwise eligible damage event. Refreshing a tile
does not stack additional tiles.

Reapplication refreshes one record instead of stacking. Refresh during an enemy ability
preserves an already-earned tick and retains the refreshed duration. Bind blocks
movement through the next player action, but permits aiming and shooting.
Esuna removes Poison and Bind; it does not remove a tile. Levitation blocks tile
damage before Ward can be consumed. Purple outlines beside the player identify
poisoned rows and remaining phases. Chichu does not apply Doom.

Chichu appears once at column 7, row 3 only after all scripted entries have
spawned, every required ordinary enemy has died, and a safe boundary is reached.
It does not attack on arrival. Stage 2 clears after Chichu and every mandatory
enemy are defeated and the final action finishes, before any further enemy or
status processing. Mandatory escapes prevent success and lead to defense failure
once scheduled spawning and active enemies finish. HP depletion is a separate
knockout outcome. Enter after this Stage Clear can proceed to Stage 3.

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
read-only HUD rendering, and restart cleanup. Stage 2 tests cover all five new
ordinary enemies, Chichu, real status/hazard applications, two-stage posted-event
campaigns, both defeat outcomes, and frame-rate determinism. Stage 3 checks cover
Tonberry Enrage, Gorgon countdowns, Odin cycles and defensive interactions, Meteor,
a complete three-stage campaign through posted inputs, Victory/Results, and reset.
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

### Stage 2 smoke tests

Complete Stage 1 with the shooting sequence above. At Stage Clear, press Enter,
confirm Stage 2 Intro and HP/MP/BP 100/100/1, then Enter. Esuna (5) and Levitation
(6) are now selectable; Meteor (3) remains locked.

For a reproducible Stage 2 clear, use the following actions. All shots aim at
**(96, 96 + 48 × row)**, horizontally leftward. Move before each action; wait
for aiming to resume before the next one.

| Turn(s) | Action | Player row |
|---|---|---:|
| 1 | Shoot | 3 |
| 2–3 | Shoot each turn | 0 |
| 4 | Select 2, Space: Starstorm | 1 |
| 5–6 | Shoot each turn | 0 |
| 7 | Shoot | 7 |
| 8–9 | Shoot each turn | 0 |
| 10 | Shoot | 1 |
| 11–12 | Shoot each turn | 0 |
| 13 | Shoot | 5 |
| 14–15 | Shoot each turn | 0 |
| 16 | Shoot | 3 |
| 17 | Shoot | 0 |
| 18 | Shoot Chichu | 3 |

Chichu arrives on Turn 18 with 30 HP. The last volley clears Stage 2 at
**HP 95, MP 60, BP 5**. Enter opens Stage 3 Intro; Enter again starts it.
R instead returns to a fresh Stage 1 Intro. The fast clear deliberately uses Bomb clusters to prevent
most abilities; the following separate check lets the new effects operate.

For real status and floor feedback, enter Stage 2 fresh, shoot from rows
**3, 0, 0** on Turns 1–3, then use these precise mouse targets:

- Turn 4: row 0, click **(480, 456)**.
- Turn 5: row 2, click **(480, 72)**.
- Turn 6: row 6, click **(96, 384)**.
- Turn 7: movement is bound; select **5**, Space for Esuna from row 6. Poison
  and Bind disappear; the tile still causes 5 damage (HP 95, MP 80).
- Turn 8: select **6**, Space for Levitation from row 6. The tile is blocked;
  Cactuar needles still cause 5 damage (HP 90, MP 60).

Pause/resume either spell animation and confirm no duplicate payment, damage,
status tick, or enemy phase. Continue playing or finish the run before restarting.

For Stage 2 HP defeat, shoot horizontally from row 0 each turn in a fresh Stage 2;
Game Over occurs on Turn 12 with HP 0. For defense failure with HP remaining,
follow the Stage 2 clear recipe through Turn 17, then deliberately miss Chichu:

| Turn | Player row | Click target |
|---:|---:|---|
| 18 | 0 | (240, 72) |
| 19–20 | 5 | (650, 360) each turn |
| 21 | 0 | (740, 72) |
| 22 | 1 | (740, 96) |
| 23 | 1 | (480, 72) |
| 24 | 0 | (96, 360) |

Chichu escapes on Turn 24 and the run ends with **Defense failed, HP 27**,
MP 60, BP 5. These paths use ordinary movement, aiming, shots, and spell controls;
no resource or enemy-HP edits are required. Restart after success and both defeats,
check the Stage 1 first wave, and verify clean window exit.

### Stage 3

Seven waves on Turns **1/4/7/10/13/16/19** contain **5/5/5/6/6/6/6** ordinary
enemies and one crystal each: **39 ordinary enemies, seven crystals**, then Odin.
Capacity remains 25. This is a deterministic encounter designed for this game,
not a claimed original-game wave table. Prior-stage configurations are unchanged.

| Enemy / label | HP | Ability before movement |
|---|---:|---|
| Mandragora / Mn | 10 | Place a two-phase PoisonTile on the player's row every third surviving phase |
| Diremite / D | 12 | Apply two-turn Poison every second surviving phase |
| Tonberry / To | 18 | After actual positive damage, stay Enraged and attack for 3 each surviving phase |
| Gorgon / G | 15 | Apply or refresh a five-turn Doom countdown every second surviving phase |
| Odin / O | 50 | Repeat SLASH (40), SLASH (40), EXECUTE (forced knockout) |

Tonberry shows **T!** after damage. Zero damage and false contact do not enrage it.
Damage from projectiles, spells, and explosions shares this same Enrage trigger.
An injured living Tonberry first retaliates in the next enemy phase it survives;
a lethal hit cannot produce retaliation. The state persists for that encounter.

New Poison, Doom, and tiles retain their application-phase grace. Existing Poison
and tile refreshes preserve already-earned damage without stacking. Doom refresh
replaces the one countdown with five and skips the refresh phase; it does not
create a parallel countdown. After its last application, five eligible phases
count **4, 3, 2, 1, 0**, even if Gorgon has died. Esuna cannot remove Doom. Continued
Gorgon refreshes postpone its deadline; killing a Gorgon does not cleanse it.

Odin appears at **column 5, row 3** only after all required scripted enemies have
been defeated, all entries have spawned, and a safe boundary is reached. It does
not attack on arrival. Each surviving phase advances exactly one cycle action,
then follows standard one-column movement and 5-HP escape contact. The cycle is
independent of whether Ward blocks a SLASH. **EXECUTE is a forced knockout**:
this game's explicit policy bypasses Ward and uses the same central knockout
resolver as Doom. Reraise revives to exactly 50 HP and is then consumed. A second
knockout without revival ends the run. The cycle repeats after EXECUTE.

All 40 enemies, including Odin, are mandatory. The final authorized action must
finish before Victory. Victory takes priority over another Odin attack, hazard,
Poison, or Doom phase. Escaping never counts as defeat. Final HP, MP, BP, stage,
and turn remain visible through Victory and Results. No score is calculated.

### Full-game victory smoke test

1. Start from the menu with Enter twice. Clear Stage 1 with horizontal shots from
   rows **3,3,2,2,4,4,1,1,5,2,5**. Enter twice advances to Stage 2.
2. Follow the Stage 2 clear table above. It ends on Turn 18 with HP 95, MP 60,
   BP 5. Enter twice advances to Stage 3 with **HP/MP/BP 100/100/1**, Turn 1.
3. On Stage 3 Turns 1–19, shoot horizontally from these rows:

   **3,4,3, 2,3,2, 4,5,4, 1,2,1, 5,6,5, 2,3,2, 3**

   Aim each shot at **(96, 96 + 48 × row)**. Move before shooting and wait for the
   next aiming phase. Tonberry retaliation and Poison leave **85 HP, MP 100,
   BP 5** when Odin arrives on Turn 20 with 50 HP.
4. Turn 20: shoot horizontally from row **4**. Odin falls to 35 HP, then SLASH
   leaves the player at 45 HP.
5. Turn 21: shoot horizontally from row **3**. Odin falls to 5 HP; the second
   SLASH leaves the player at 5 HP.
6. Turn 22: select **3**, press Space for Meteor. Confirm MP 20 and Odin's death.
   The animation must finish before **Victory**; EXECUTE must not occur. Enter
   opens Results showing **Stage 3, Turn 22, HP 5, MP 20, BP 5**. R restarts at
   Stage 1 Intro with all encounter state reset.

The same route works by shooting from row 3 instead of the final Meteor; MP
then remains 100. To demonstrate Odin's defenses, follow Turns 1–19 above, then:

| Turn | Action from row 3 | Expected outcome |
|---:|---|---|
| 20 | Ward (7, Space) | First SLASH blocked; HP 85, MP 70 |
| 21 | Reraise (8, Space) | Second SLASH; HP 45, MP 20 |
| 22 | Cure (4, Space) | Heal to 95, EXECUTE, revive to 50; MP 10 |
| 23 | Shoot | Odin 5 HP; next SLASH leaves HP 10 |
| 24 | Shoot | Victory at HP 10, MP 10, BP 5 |

Pause/resume a shot and Meteor animation. Extra clicks/Space must not create
another action; paused time must not advance abilities, cooldowns, or statuses.
Restart from both Victory and Results, and verify clean window exit.

For Stage 3 **HP defeat**, shoot horizontally from row 0 each turn: Game Over
occurs on Turn 12 with HP 0. For a genuine **Doom knockout**, shoot from row 0 on
Turns 1–2, row 3 on Turn 3, then row 0 on Turns 4–7. Doom reaches zero on Turn 7.
Casting Reraise from row 0 instead of the Turn-7 shot revives to 50 HP; it does not
restore the encounter's Reraise casting allowance.

For **defense failure**, follow the Stage 3 opening through Turn 18, then:

| Turn | Player row | Action / click target |
|---:|---:|---|
| 19 | 0 | Shoot (740, 456) |
| 20 | 0 | Shoot (768, 456) |
| 21 | 0 | Esuna |
| 22 | 0 | Levitation |
| 23 | 0 | Ward |
| 24 | 0 | Cure |
| 25 | 0 | Esuna |
| 26 | 1 | Shoot (740, 96) |
| 27 | 1 | Shoot (480, 72) |
| 28 | 0 | Shoot (96, 360) |

Gorgon escapes with 15 HP; **Defense failed** preserves **95 player HP**, MP 0,
BP 5. Odin must not spawn. These clear and defeat paths use ordinary controls,
without editing resources or enemy HP. Restart always returns to Stage 1.

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
  entities.py           Grid enemies, statistics, crystals, and snapshots
  enemy_abilities.py    Deterministic enemy attacks, statuses, hazards, and Odin cycle
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
    stage_02.json       Complete Stage 2 (six waves and Chichu)
    stage_03.json       Final Stage 3 (seven waves and Odin)
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
  test_stage_one.py     Canonical Stage 1 gameplay and regression paths
  test_stage_two.py     Stage 2 config, two-stage campaign, outcomes, and determinism
  test_stage_two_enemies.py  Abilities, statuses, hazards, combat, and defenses
  test_stage_three.py   Three-stage campaign, final outcomes, config, and determinism
  test_stage_three_enemies.py  Enrage, Doom, Odin cycles, damage, and defenses
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

Scoring, persistence, final artwork, and audio are not available.
