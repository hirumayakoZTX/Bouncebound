# Optional sound resources

Eight original short WAV cues are bundled: `shoot`, `bounce`, `hit`, `death`,
`spellcast`, `damage`, `victory`, and `defeat`. Audio is off by default. Run
`python main.py --audio` to opt in. Cues reflect already-resolved events; playback
has no authority over gameplay. Missing/corrupt files, mixer failure, and device
loss produce silence. No audio device is required for normal play.

Rebuild these files offline with `python -B assets/generate_cues.py`. The editable
source uses only mathematical tones and Python's standard library. The WAVs are
quiet 16-bit mono PCM at 22050 Hz, each shorter than 0.3 seconds. Source, creator,
license, and attribution details are in `assets/CREDITS.md`. No external sampled
or extracted game audio is used. Other optional formats depend on SDL_mixer codecs.
