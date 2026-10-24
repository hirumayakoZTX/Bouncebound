# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a main menu, stage introduction,
placeholder battlefield with vertical movement, mouse aiming, ricocheting orbs,
and pause/resume. Enemy combat is not implemented yet.

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
- **Left-click inside the arena** to launch one orb along the selected direction.
- **Escape** at the battlefield pauses; press it again to resume.
- **Escape** at the menu exits. The window close button exits from any screen.

New runs begin at Stage 1, Turn 1, with HP 100/100, MP 100/100, and BP 1.
These resources are displayed only; no resource or combat mechanics are active.
The player starts on row 3 of eight rows at a fixed horizontal position. Movement
stays within the grid; aiming is restricted to the arena to the player's left.
The preview is a straight line and disappears when the cursor moves outside the
arena. Movement and aiming do not advance turns or spend resources. Pausing
ignores movement and aiming input and freezes active orbs; resuming preserves the
previous position, aim, and projectile trajectory. Shots lock their direction;
additional clicks and movement are ignored during flight. BP is not spent.

Orbs travel at 520 pixels/second, bounce within the arena with a 7-pixel radius,
and expire after 5 seconds or 12 target hits. There are currently no enemies or
targets in the playable scene. After a shot, the prototype stops at a clearly
marked turn-resolution screen. No enemy phase or turn advancement runs yet;
close and relaunch the application to try another shot.

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
projectile lifetime, frame-rate independence, and rendering without changing run
data. Target contacts emit collision events only; no enemy HP is modified.
The tests do not verify a real desktop window or platform compatibility.

Manual smoke test: run `python main.py`, confirm the 960 × 576 menu, then press
Enter twice to reach the battlefield. Confirm Stage 1, Turn 1, HP/MP 100, and BP 1.
Move with W/S and the arrow keys; confirm movement stops at the top and bottom
rows. Move the mouse inside the arena and confirm the aiming line follows the
player when moving; move outside and confirm the line disappears. Pause, try
moving/aiming, and resume; position and aim should be preserved. Turn and resources
must remain unchanged. Left-click inside the arena and confirm the orb enters
naturally and ricochets. Pause/resume during flight; the orb must freeze and
continue from the same position. After expiry, confirm the turn-resolution
message and unchanged turn/resources. Close the window and confirm no traceback.
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
  game.py               Window, loop, events, and shutdown
  renderer.py           Asset-free scene display
  states.py             Shared scene and turn-phase names
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
```

No enemies, damage processing, spells, stage progression, or persistence exists yet.
