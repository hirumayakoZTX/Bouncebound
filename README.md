# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a main menu, stage introduction,
temporary battlefield with vertical movement, mouse aiming, ricocheting orbs,
Basic Slimes, Bomb chain reactions, BP crystals, enemy turns, player damage,
and pause/resume.

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
- **Left-click inside the arena** to launch the current BP number of orbs.
- **Escape** at the battlefield pauses; press it again to resume.
- **Escape** at the menu exits. The window close button exits from any screen.

New runs begin at Stage 1, Turn 1, with HP 100/100, MP 100/100, and BP 1.
HP tracks player health; MP is currently displayed only. BP controls the number
of orbs per shot.
The player starts on row 3 of eight rows at a fixed horizontal position. Movement
stays within the grid; aiming is restricted to the arena to the player's left.
The preview is a straight line and disappears when the cursor moves outside the
arena. Movement and aiming do not advance turns or spend resources. Pausing
ignores movement and aiming input and freezes active orbs; resuming preserves the
previous position, aim, and projectile trajectory. Shots lock their direction;
additional clicks and movement are ignored during flight. BP is not spent.

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

The current demonstration has a Slime, two adjacent Bombs, and a crystal.
From the initial row, aim horizontally left to collect the crystal, trigger the
Bomb chain, and hit the Slime after a ricochet. This is a temporary demonstration,
not a complete stage. After every orb and combat effect finishes, surviving
enemies take one phase, then the turn increases once and aiming resumes.
Movement, aiming, and invalid shots never trigger an enemy phase.

Enemies act in ascending ID order, then attempt one column forward in their
current row. A cell occupied by another active enemy blocks movement; a cell
vacated by an earlier ID is available immediately. Crystals do not block enemies.
When they share a cell, the crystal appears as a small blue corner marker.

An enemy attempting to leave column 13 deals 5 contact damage and escapes. An
escaped Bomb does not explode. If HP reaches zero, Game Over stops combat and
turn advancement; close the window and relaunch to start a new run. There are no
waves or stage-clear conditions yet. Empty battlefields safely allow more turns.
Only three enemies exist in the demo, so letting all escape costs at most 15 HP.

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
The tests do not verify a real desktop window or platform compatibility.

Manual smoke test: run `python main.py`, confirm the 960 × 576 menu, then press
Enter twice to reach the battlefield. Confirm Stage 1, Turn 1, HP/MP 100, and BP 1.
Move with W/S and the arrow keys; confirm movement stops at the top and bottom
rows. Move the mouse inside the arena and confirm the aiming line follows the
player when moving; move outside and confirm the line disappears. Pause, try
moving/aiming, and resume; position and aim should be preserved. Turn and resources
must remain unchanged. Aim horizontally left from the initial row and left-click.
Confirm the crystal disappears, both Bombs explode, and the Slime disappears after
a ricochet. Pause/resume during flight; orbs must freeze and continue from the same
positions. After expiry, confirm BP 2, unchanged HP/MP, and Turn 2 with aiming
enabled again. Alternatively, move to the top row and shoot horizontally left to
miss the enemies. Repeat several turns and confirm surviving enemies advance
one cell each phase. Enemies crossing the right edge reduce HP by 5 and disappear;
Bomb escapes must not cause explosions. Close the window and confirm no traceback.
Relaunch and press Escape at the menu to confirm clean exit.

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
  demo.py               Replaceable static combat demonstration
  entities.py           Plain grid enemy/crystal models and snapshots
  game.py               Window, loop, events, and shutdown
  renderer.py           Asset-free scene display
  states.py             Shared scene and turn-phase names
  turns.py              Stable enemy action, movement, and contact resolution
  world.py              Authoritative run, input, projectile, and scene controller
  projectile.py         Orb simulation, fixed steps, snapshots, and hit events
assets/                 Asset directory (.gitkeep only; no assets required)
config/                 Configuration directory (.gitkeep only; currently unused)
tests/
  test_bootstrap.py     Headless application checks
  test_world.py         Deterministic controller and transition tests
  test_scenes.py        Scene input and rendering checks
  test_player_input.py  Movement and aiming rules
  test_projectile.py    Geometry, ricochets, contact events, and timing
  test_shooting.py      Shot lifecycle, pause, and application integration
  test_combat.py        Models, damage, death queues, explosions, and crystals
  test_combat_integration.py  Live target synchronization, BP fans, and demo
  test_turns.py         Enemy phases, contact damage, and defeat rules
  test_turn_integration.py  Consecutive turns, pause, defeat, and rendering
```

No waves, bosses, spells, stage progression, scoring, or persistence exists yet.
