# Bouncebound: Familiar Defense

An original, offline, turn-driven ricochet defense game. Guide a volley of
orbs through enemy lines, collect blue crystals, and protect the defense edge
through three stages. The campaign ends with the Iron Knight and a Victory →
Results sequence.

## Requirements and launch

- Python 3.11 or later.
- Pygame 2.6.1 (the only third-party dependency).
- A desktop display on macOS or Windows.

The logical window is 960 × 576 and rendering is capped at 60 FPS. Artwork has
procedural fallbacks. Audio is optional and disabled unless explicitly enabled.

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Use `python main.py --audio` to opt into the supplied sound cues or
`python main.py --no-effects` to disable transient visual effects. The game
remains playable without optional art, audio hardware, or internet access.

## Controls and turn rules

- **Enter** starts a new run, continues an introduction, advances after Stage
  Clear, and opens Results after Victory.
- **I** opens the two-page field guide from the menu. **Left / Right** changes
  pages; **Escape / Backspace** returns to the menu.
- **W / Up Arrow** and **S / Down Arrow** move one row while aiming.
- **Mouse** aims inside the battlefield. **Left-click** fires the current volley.
- **1–5** select an unlocked spell; **Space** casts it.
- **Escape** pauses or resumes active gameplay. The window close button exits.
- **T** retries Stage 2 or 3 after Game Over, starting that stage from Wave 1.
- **R** restarts the campaign from Stage 1 after a supported terminal screen.

Movement, aiming, and spell selection are free. One successful shot or spell is
one main action; failed casts cost no MP and no turn. Enemy actions and effects
resolve after an action finishes. BP sets the number of orbs in a shot, is not
consumed, and is capped at five. Blue crystals reward BP after the volley ends.
There is no passive MP regeneration.

## Spells

| Key | Spell | MP | Cooldown | Availability and effect |
|---|---|---:|---:|---|
| 1 | Fire | 30 | 3 turns | Stage 1; 20 damage to the nearest enemy in the player's row |
| 2 | Cure | 10 | 1 turn | Stage 1; restore up to 50 HP, only when HP is missing |
| 3 | Ward | 30 | 3 turns | Stage 1; block one ordinary damage event |
| 4 | Cleanse | 20 | 3 turns | Stage 2; remove Poison |
| 5 | Meteor | 80 | 10 turns | Stage 3; deal 15 damage to every active enemy |

Offensive spell damage can start Bomb chains but cannot collect crystals. The
only player statuses are Poison and one-use Ward protection. Poison deals 3
damage per eligible enemy phase; refreshing Poison replaces its record rather
than stacking it. There are no floor hazards or revival effects.

## Stages and enemies

The canonical JSON files define the playable encounters. Ordinary waves retain
their configured timing while enemies remain. When a completed action clears
the battlefield, the next ordinary wave can appear at that safe boundary without
an extra empty-board shot. Boss eligibility and stage-clear checks are unchanged.

| Stage | Ordinary encounter | Final encounter |
|---|---|---|
| 1 | Slimes and 10-HP Bombs, five waves | Octopus and Hurricane, 15 HP each; 5-damage attacks |
| 2 | Cactus, Alligator, Bulb, Bigmouth Flower, and Snap Plant, six waves | Seedling, 30 HP; Poison at long range, 15 damage nearby |
| 3 | Root Plant, Mite, Greenberry, and Thorn Snake, seven waves | Iron Knight, 50 HP; repeating 40-damage Slash, 40-damage Slash, 50-damage Heavy Blow |

Standard orbs deal 4 damage. A Bomb has 10 HP; on defeat it deals 10 damage to
enemies in the eight neighboring cells and can trigger a deterministic chain.
The Cactus adjusts its row toward the player and attacks when aligned; the Alligator
attacks every third surviving phase. The Bigmouth Flower applies Poison every third phase,
and the Seedling uses Poison at long range or a direct attack nearby. The Mite
applies Poison every second surviving phase. The Greenberry becomes enraged
after taking real damage and then retaliates for 3 each surviving phase.
The Bulb, Snap Plant, Root Plant, and Thorn Snake use standard movement. The Iron
Knight's Heavy Blow is ordinary 50-point damage, so it cannot defeat a full-HP
player in one hit; Ward can block it.

All damage uses the common HP resolver. The Game Over screen shows both the
defeat type and the specific final source, such as a named enemy attack or
Poison from a named enemy. Escaping required enemies remains a separate defense
failure and is not presented as HP depletion.

Stage 1 and 2 clear screens advance through their registered introductions.
Stage 3 ends in Victory, then Results. Retry starts the failed stage fresh with
100 HP, 100 MP, 1 BP, Turn 1, Wave 1, cleared cooldowns/statuses, and fresh boss
progress. Restart Campaign returns to Stage 1. There are no checkpoints between
application sessions.

## Score and local high score

Scoring is authoritative and independent of rendering. The current score awards
100 for a common enemy, 200 for a special enemy, and 1,000 for a boss; eligible
Bomb-chain kills add 50, and one shot hitting at least three distinct enemies
adds 100. Stage completion may award 1,500 for full HP, 3,000 for full MP, and
20,000 for taking no HP damage during that stage. Results displays the actual
score breakdown.

Only a confirmed final campaign Victory is saved. The versioned JSON record
contains the best score and the last successfully saved completion, without
personal information. A higher score replaces the best; an equal score retains
it. Missing or malformed files do not prevent play. Runtime data is stored
outside the repository:

- macOS: `~/Library/Application Support/Bouncebound/save/high_scores.json`
- Windows: `%LOCALAPPDATA%\Bouncebound\save\high_scores.json`
- Linux development: `$XDG_DATA_HOME/bouncebound/save/high_scores.json`, or
  `~/.local/share/bouncebound/save/high_scores.json`.

To reset the stored score, close the game and delete `high_scores.json`. Stage
retry and campaign restart do not alter a stored record.

## Art and audio

The project includes original pixel sprites for the guardian, basic enemies,
crystals, projectile, and all named enemies and bosses. Sprite images use
nearest-neighbor scaling; missing or unreadable images fall back to procedural
shapes. Sound cues are optional, disabled by default, and fail silently if the
audio device or a resource is unavailable. Asset provenance and generator
commands are documented in [`assets/CREDITS.md`](assets/CREDITS.md).

## Smoke test and verification

From the main menu, open the field guide with **I**, navigate both pages, then
return with **Backspace**. Start with **Enter**, aim and shoot, pause during a
shot, then resume. On a failed Stage 2/3 attempt, use **T** and check that the
introduction leads to a fresh first wave; use **R** on a terminal screen to
restart Stage 1.

The automated full-suite command is:

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

The deterministic no-revival campaign fixture uses these shot rows:

- Stage 1: `3, 3, 2, 2, 4, 2, 1, 5, 2, 5`
- Stage 2: `3, 3, 2, 2, 4, 3, 1, 1, 5, 5, 3, 3, 3`
- Stage 3: `3, 3, 3, 2, 2, 3, 4, 4, 5, 1, 1, 5, 5, 2, 2, 3, 3, 3`,
  then cast **Ward** and shoot row `3`.

Use aim point `(96, 96 + 48 × row)` for each shot. Enter after each stage
introduction and clear. On the current deterministic build, this route reaches
Results on Stage 3 Turn 20 with 27 HP, 70 MP, and 5 BP, without a revival.

## Repository map

```text
src/                  World, combat, encounters, spells, scoring, persistence, renderer
config/stages/        Canonical JSON encounters and schema notes
assets/               Original sprites, sound cues, and editable generators
tests/                Model, integration, UI, score, persistence, and campaign tests
```
