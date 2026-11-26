# Brief: sound effects for a Leo Explains video

> Public copy: the working brief for the sound-effects pass, kept because it documents `sfx.json` and the sfx tools.

Project folder: `scripts/` of this repository.
Python: the project's virtualenv `python`.
ElevenLabs (ELEVENLABS_API_KEY from the environment, never printed):
`sfx_tool.py <out_mp3> <seconds> eleven_text_to_sound_v3 <prompt...>` (project file since 2026-11-01,
uses `el_tool.py`; add `--dry-run` to print the request without sending; `sfx_tool.py --check` tests the key)

## Goal (user's words: effects "where they belong, e.g. fridge, phone, cars, rain, TV — wherever
## the scene needs them to feel real")
For video vN, go through all 40 scenes (`vN/scenes.json`: narration + IMAGE prompt; look at
`vN/images/scene_NN.webp` too, and `scene_NN_clip.mp4` where present) and add a sound wherever the
picture shows or the narration names a real sound source:
- **Spot effects** (lufs -26): fridge door, phone buzz/unlock/notification ping, keyboard typing,
  door, footsteps, cup on table, page turn, shopping bag rustle, cash register, alarm clock, etc.
  Timed to the moment (offset inside the scene, use the narration timing: scene starts come from
  `scene_starts` in `../video_pipeline/assemble.py` on `vN/voiceover.alignment.json`).
- **Ambience** (lufs -32 to -34, with "length" = the scene duration so it ends with the scene):
  rain on the window, city traffic/cars outside, café chatter, office hum, TV murmur, night
  crickets in a park, shop/mall atmosphere — only where that place is on screen.
- No effects on abstract scenes (brain diagrams, glowing loops) except at most a soft whoosh/sparkle.
- Typically 8-15 entries per video. Don't stack more than two sounds at the same moment.
  Prompts always end with "no music, no voices" (except crowd ambience: "indistinct chatter").
  Reuse a generated file for repeated sounds instead of generating again (saves credits).
  Keep durations short (spot 1-2.5 s, ambience <= the scene length, max 10 s).

Save files to `vN/sfx/<name>.mp3` and write `vN/sfx.json`:
`[{"file": "sfx/fridge.mp3", "scene": 1, "offset": 2.6, "lufs": -26, "db": 0},
  {"file": "sfx/rain.mp3", "scene": 12, "offset": 0, "lufs": -33, "length": 4.2}, ...]`
(`render.py` mixes them under the voice; final loudnorm -14.)

## Check
Render a preview of the first 60 s: `python render.py vN --preview 60` and confirm with
`ffmpeg ... -af volumedetect` that no effect peaks over the voice (compare the effect moments with
nearby voice-only moments; effects must stay clearly under the narrator). Fix levels with "db".
Don't render the full video and don't upload anything. Report the sfx.json table (scene, sound,
why) and how many ElevenLabs generations you used. If ElevenLabs returns a quota error, stop and
report.
