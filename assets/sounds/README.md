# Optional sound resources

No sound files are bundled and the game currently plays no audio. AssetManager
supports opt-in, lazy sound loading with silent fallback when a file or device
is unavailable. Importing the game or loading images does not initialize audio.

Suitable future cue names are `shoot.wav`, `bounce.wav`, `damage.wav`,
`spellcast.wav`, `victory.wav`, and `defeat.wav`. Naming a file does not wire it
to gameplay: no sound event playback system is installed yet. Prefer WAV for a
portable initial resource; other formats depend on the installed SDL_mixer codecs.
Document actual source/license information in `assets/CREDITS.md` before adding
any external sound file.
