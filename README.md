# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game inspired by Kupo Kupo
Adventure. The current version provides a placeholder title screen and clean
exit. Gameplay is not implemented yet.

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

A window titled **Bouncebound: Familiar Defense** displays the game title on a
plain background. Press **Escape** or use the window close button to exit.
Audio hardware is not initialized or required.

## Verify

With the virtual environment active:

```bash
python -m unittest discover -s tests -v
git diff --check
```

The tests select SDL's dummy video driver and need no visible display. They cover
imports, display initialization, resolution/title, event handling, the frame cap,
shutdown, and startup without project assets. They do not verify a real desktop
window or platform compatibility.

Manual smoke test: run `python main.py`, confirm the title and placeholder are
visible in a 960 × 576 window, press Escape, and confirm a clean exit. Relaunch
and close using the window close button; confirm no traceback appears.

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
  renderer.py           Asset-free placeholder display
assets/                 Asset directory (.gitkeep only; no assets required)
config/                 Configuration directory (.gitkeep only; currently unused)
tests/
  test_bootstrap.py     Headless application checks
```

No gameplay, scene transitions, combat, or persistence exists yet.
