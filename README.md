# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a main menu, stage introduction,
placeholder battlefield, and pause/resume. Combat is not implemented yet.

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
- **Escape** at the battlefield pauses; press it again to resume.
- **Escape** at the menu exits. The window close button exits from any screen.

New runs begin at Stage 1, Turn 1, with HP 100/100, MP 100/100, and BP 1.
These resources are displayed only; no resource or combat mechanics are active.
The battlefield waits for input without advancing turns. Pausing and resuming
preserve the run. Other keys and mouse input currently have no gameplay effect.

## Verify

With the virtual environment active:

```bash
python -m unittest discover -s tests -v
git diff --check
```

The tests select SDL's dummy video driver and need no visible display. They cover
imports, display initialization, resolution/title, event handling, the frame cap,
shutdown, startup without project assets, scene transitions, reset, pause/resume,
and rendering without changing run data. They do not verify a real desktop window
or platform compatibility.

Manual smoke test: run `python main.py`, confirm the 960 × 576 menu, then press
Enter twice to reach the battlefield. Confirm Stage 1, Turn 1, HP/MP 100, and BP 1.
Press Escape twice to pause/resume; values should remain unchanged. Enter, Space,
movement keys, and mouse clicks must not advance combat. Close the window and
confirm no traceback. Relaunch and press Escape at the menu to confirm clean exit.

## Repository layout

```text
main.py                 Application entry point
README.md               Setup and verification
LICENSE                 Project license
requirements.txt        Pinned runtime dependency
.gitignore              Local/generated file exclusions
src/
  __init__.py           Application package
  constants.py          Display configuration
  game.py               Window, loop, events, and shutdown
  renderer.py           Asset-free scene display
  states.py             Shared scene and turn-phase names
  world.py              Run data, transitions, pause, and reset
assets/                 Asset directory (.gitkeep only; no assets required)
config/                 Configuration directory (.gitkeep only; currently unused)
tests/
  test_bootstrap.py     Headless application checks
  test_world.py         Deterministic controller and transition tests
  test_scenes.py        Scene input and rendering checks
```

No player movement, projectiles, enemies, combat, stage progression, or
persistence exists yet.
