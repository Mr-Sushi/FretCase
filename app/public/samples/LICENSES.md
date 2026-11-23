# Instrument samples

Made by `scripts/fetch-samples.py`: each file is trimmed, converted to mono MP3 and loudness-normalised.
The app plays them through Tone.js samplers (`app/src/audio/voices.ts`); `manifest.json` lists the files.

| Folder | Source | Licence |
| --- | --- | --- |
| `synth-male` (choir aahs), `synth-female` (voice oohs), `piano`, `whistle`, `flute`, `steel`, `nylon`, `electric-clean`, `finger-bass`, `upright-bass`, `synth-bass` | FluidR3_GM SoundFont by Frank Wen, rendered per note by Benjamin Gleitzman ([gleitz/midi-js-soundfonts](https://github.com/gleitz/midi-js-soundfonts)) | [Creative Commons Attribution 3.0](https://creativecommons.org/licenses/by/3.0/) |
| `harmonica` (Hohner Special 20 in C), `jazz-kit`, `pop-kit`, `hand-drum` | VCSL, the Versilian Community Sample Library by Sam Gossner ([sgossner/VCSL](https://github.com/sgossner/VCSL)), via [danigb/samples](https://github.com/danigb/samples) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

`synth-soft` plays the `synth-female` files and `ukulele` the `nylon` files, with a different envelope.

Attribution for anything published with these sounds: "Instrument samples: FluidR3_GM by Frank Wen (CC BY 3.0); VCSL by Sam Gossner (CC0)."
