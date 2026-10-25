# Asset credits

The five pixel placeholders below were created for Bouncebound from local,
AI-assisted pixel-map designs. They are original project placeholders, not sprites
extracted from FFXIV or copied from external artwork. No third-party image,
audio, or font file was downloaded or added for this set.

| Asset title | Category / file | Creator | External source URL | License | Modifications | Attribution requirements |
|---|---|---|---|---|---|---|
| Kite Guardian | Player — `images/player/guardian.png` | Bouncebound project (AI-assisted pixel-map design) | Not applicable; original project asset | GNU GPL v3; see repository `LICENSE` | Generated from the supplied pixel map; integer scaling at runtime | GPL v3 redistribution conditions; no extra attribution terms |
| Moss Slime | Enemy — `images/enemies/slime.png` | Bouncebound project (AI-assisted pixel-map design) | Not applicable; original project asset | GNU GPL v3; see repository `LICENSE` | Generated from the supplied pixel map; integer scaling at runtime | GPL v3 redistribution conditions; no extra attribution terms |
| Ember Capsule | Enemy — `images/enemies/bomb.png` | Bouncebound project (AI-assisted pixel-map design) | Not applicable; original project asset | GNU GPL v3; see repository `LICENSE` | Generated from the supplied pixel map; integer scaling at runtime | GPL v3 redistribution conditions; no extra attribution terms |
| Blue BP Shard | Collectible / UI — `images/ui/bp_crystal.png` | Bouncebound project (AI-assisted pixel-map design) | Not applicable; original project asset | GNU GPL v3; see repository `LICENSE` | Generated from the supplied pixel map; integer scaling at runtime | GPL v3 redistribution conditions; no extra attribution terms |
| Amber Orb | Projectile — `images/projectiles/orb.png` | Bouncebound project (AI-assisted pixel-map design) | Not applicable; original project asset | GNU GPL v3; see repository `LICENSE` | Generated from the supplied pixel map; native scale at runtime | GPL v3 redistribution conditions; no extra attribution terms |

All source maps and palette entries are in [generate_placeholders.py](generate_placeholders.py).
Every PNG is 16 × 16 with transparency. Rebuild them offline from the repository
root using `.venv/bin/python -B assets/generate_placeholders.py`. The script uses
only Pygame, initializes no display or audio, and writes only the five named PNGs.
The editable maps are the corresponding source for these placeholders.

The renderer still uses Pygame's bundled default font through `Font(None, size)`;
no font file has been copied into the project. No sound files are bundled.

For each future external asset, record its actual title, category, creator,
source URL, redistribution license, modifications, and required attribution here
before distributing it. An online image or audio file is not automatically free
to reuse. This table does not grant rights to third-party replacement files.
