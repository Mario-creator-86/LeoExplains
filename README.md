# Leo Explains – content production pipeline

Tooling behind **"Leo Explains"**, a series of short animated psychology explainers starring Leo, a stickman with a
yellow backwards cap. Every episode is produced by a scripted pipeline: a ChatGPT-written script is turned into
per-scene image prompts, the pictures are drawn in Google Flow, the narration is synthesised (ElevenLabs, Fish Audio
Drama 3 or local Kokoro), subtitles are generated from the voice's own character timings, the long 16:9 video and the
vertical cuts (YouTube Shorts, TikTok, Reels) are rendered with Pillow + ffmpeg, checked automatically and uploaded
through the YouTube Data API. A small local dashboard tracks the channels.

This repository is a **curated public copy** of that tooling: the Python scripts, the prompt templates, the dashboard
code and a few small example inputs. Media assets (images, character sheets, music, sound effects, generated videos),
the model weights, the episode folders and all editorial / growth planning documents are **not included**.

```
script (ChatGPT) ──► scenes.json / narration.txt ──► scene prompts (Flow) ──► images
                                                                              │
          TTS (ElevenLabs | Fish Drama 3 | Kokoro) ──► voiceover.mp3 + alignment.json
                                                                              │
   make_srt ◄── render (16:9) ──► shorts (9:16 cuts) ──► preflight / motion_check / review_sheet ──► upload
```

## Folder layout

| Folder | What it holds |
|---|---|
| `scripts/` | The production tools. Episode folders `vN/` (scenes.json, images/, voiceover.mp3, …) live **next to these scripts**; most tools take `vN` as their first argument and resolve it relative to their own folder. |
| `scripts/voice/` | Local Whisper check of TTS takes (`asr_check.py`) and the Fish Audio voice-design / pick helpers. |
| `video_pipeline/` | The first, single-video pipeline (`assemble.py`: scene timing from ElevenLabs character timestamps, captions, ffmpeg assembly; `youtube_upload.py`: resumable upload + OAuth helpers reused by every upload script). |
| `dashboard/` | Stdlib-only local web dashboard (`server.py` + `index.html`, Chart.js from a CDN): YouTube / TikTok / Instagram statistics, publishing log, monetisation progress, desktop alerts. Its SQLite cache and logs are not included. |
| `flow_prompts/` | `build_prompts.py` turns `scenes.json` into per-scene, per-pose image prompts (16:9 and 9:16); `serve.py` serves them to the browser; `thumbnail_prompts.json` is the thumbnail prompt template. |
| `prompts/` | Prompt templates: the ChatGPT episode prompt, the story-hook Short template, an image batch prompt, and the writer skill / assignment templates. |
| `examples/` | One episode's `scenes.json`, `script.md` and `narration.txt`, plus the set-library notes. |
| `docs/` | The two working briefs that document how the scripts are used in order (`PRODUCTION_BRIEF.md`) and the `sfx.json` format (`SFX_BRIEF.md`), scrubbed of paths and account data. |

## The main scripts

| Script | Purpose |
|---|---|
| `series_tool.py parse N` | Parse the ChatGPT answer (`vN/chatgpt.md`) into `scenes.json`, `meta.json`, `narration.txt` and image batch files. |
| `flow_prompts/build_prompts.py` | Per-scene Flow image prompts (poses A/b/c/d, vertical 9:16 variants). |
| `compose_scene.py` / `leo_pose.py` | Local composition when the image model fails: cut a drawn character out, place it on a set, redraw a clock; draw Leo from a joint skeleton (any pose, always two arms and two legs). |
| `upscale_scene.py` | Real-ESRGAN x4 copy of a scene for tight crops (falls back to Lanczos). |
| `el_tool.py` / `tts_fish.py` / `tts_kokoro.py` | Narration with per-character timings: ElevenLabs API, Fish Audio Drama 3 (Hugging Face Space, voice cloning) or local Kokoro-82M. All write the same `voiceover.mp3` + `voiceover.alignment.json`. |
| `voice/asr_check.py`, `whisper_mp4.py` | Local Whisper transcript of takes / finished videos (missing words, tags read aloud). |
| `cut_phrase.py` | Remove a phrase from an episode's voice and timings without re-voicing. |
| `sfx_tool.py`, `sfx_local.py`, `sfx_score.py`, `sfx_check.py` | Sound effects: ElevenLabs generation, local Stable Audio generation scored with LAION CLAP, and a check of `sfx.json` against the cut. |
| `render.py` | The 16:9 episode: sub-pixel camera moves, pose dissolves, Veo clips, burned-in word captions, voice + music + effects mixed to -14 LUFS. |
| `shorts.py` | The vertical cuts: picks complete scenes, re-cuts the voice on scene boundaries, re-renders with per-platform safe zones (`safe_zones.py`), hook text, captions; `--check` validates length, size and loudness. |
| `make_srt.py` | Exact SRT subtitles from the alignment (long video and Short). |
| `thumbnail.py` | Places the 2-3 word text on a drawn thumbnail image. |
| `preflight.py`, `motion_check.py`, `review_sheet.py` | Mandatory checks before any upload: black / frozen / silent stretches, camera shake measurement (phase correlation), contact sheet including the last frame. |
| `compile_long.py` | 8-15 min compilation of several episodes with chapters and cross-fades. |
| `upload_long.py`, `youtube_upload_short.py`, `set_thumbnail.py`, `set_privacy.py`, `add_links.py` | YouTube Data API: resumable uploads, scheduled publishing, thumbnails, privacy, description links. |
| `release.py` | `vN/release.json`: hand-over between production and the per-platform publishing steps. |
| `team_settings.py` | Reads `team_settings.json` (voice speed/pause, allowed cut lengths). |
| `ro_cut.py` | Romanian TikTok version of an episode (re-voice + re-cut). |
| `dashboard/server.py` | Local statistics dashboard (`python dashboard/server.py`, then http://127.0.0.1:8010). |

### How the scripts import each other

The scripts are plain modules in one folder, so they import each other by name: `shorts.py` imports `render`,
`safe_zones`, `team_settings` and `assemble`; `compile_long.py` and `render.py` import `assemble` from
`video_pipeline/` (they add `../video_pipeline` to `sys.path`); the upload scripts import `access_token` / `request`
from `video_pipeline/youtube_upload.py`; `sfx_tool.py` imports `el_tool`; `tts_fish.py` and `whisper_mp4.py` import
`voice/asr_check.py`; `make_srt.py --short` imports `shorts` for the segment rule. Keep the folder layout as it is
and run the scripts from the `scripts/` folder.

## Requirements

* Python 3.11+ and **ffmpeg / ffprobe** on PATH (or `FFMPEG`, `FFPROBE` environment variables).
* `pip install -r requirements.txt` – Pillow and numpy for rendering; torch, torchaudio, soundfile, librosa,
  transformers, huggingface_hub, gradio_client, httpx and kokoro only for the TTS / SFX / upscale tools (see the
  comments in `requirements.txt`). Everything that talks to YouTube, ElevenLabs or Meta uses only the standard library.
* A bold TTF font for captions (default `C:\Windows\Fonts\ariblk.ttf`, override with `LEO_FONT`).
* Music beds (`<track>.mp3` + `music_library.json`) in `./music` or `LEO_MUSIC_DIR`; a character sheet and scene
  images drawn in Google Flow (not included).

### Environment variables

Copy `.env.example` to `.env` and fill in what you use. Names only:

`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`, `YOUTUBE_CHANNEL_ID`,
`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `HF_TOKEN`, `FISH_SPACE`, `LEO_MUSIC_DIR`, `LEO_FONT`,
`FFMPEG`, `FFPROBE`, `FFMPEG_DIR`, `TTS_PYTHON`, `LEO_LANG`, `META_CONNECTION_FILE`.

No key, token or account id is stored in the code; the scripts refuse to run without the variable they need and never
print the values.

## Producing an episode (order of operations)

Run from `scripts/`, with an episode folder `vN/` next to the scripts.

```bash
# 1. Script: paste the ChatGPT answer to prompts/episode_prompt_example.txt into vN/chatgpt.md, then
python series_tool.py N                          # -> vN/scenes.json, meta.json, narration.txt, batch_*.txt

# 2. Images: prompts for Google Flow (16:9 poses, then the 9:16 scenes of the vertical cuts)
python ../flow_prompts/build_prompts.py N        # -> flow_prompts/prompts_all.json
python ../flow_prompts/build_prompts.py --vertical N
#    draw them in Flow -> vN/images/scene_NN[b|c|d].jpeg, vN/images_v/scene_NN.jpeg
#    (compose_scene.py / leo_pose.py repair a scene the model keeps getting wrong)

# 3. Narration (pick one TTS back end; all write vN/voiceover.mp3 + vN/voiceover.alignment.json)
python tts_kokoro.py vN                          # local, free
python tts_fish.py vN                            # Fish Audio Drama 3 on a Hugging Face Space (FISH_SPACE)
python el_tool.py tts vN/narration.txt vN/voiceover.mp3   # ElevenLabs (ELEVENLABS_API_KEY)

# 4. Sound effects (optional): write vN/sfx.json, then
python sfx_check.py vN                           # validates it against the Short's scenes

# 5. Render
python render.py vN                              # -> vN/video.mp4 (16:9)
python shorts.py vN --plan && python shorts.py vN            # -> vN/short.mp4 (YouTube Short)
python shorts.py vN --tiktok && python shorts.py vN --reels  # -> short_tiktok.mp4, short_reels.mp4
python shorts.py vN --check vN/short_sheet.png   # length / size / loudness / voice start

# 6. Subtitles, thumbnail, checks
python make_srt.py vN && python make_srt.py vN --short
python thumbnail.py vN --hero vN/thumbnail_hero.png --text "TWO WORDS" --side left
python preflight.py vN/short.mp4 --short && python motion_check.py vN/short.mp4
python review_sheet.py vN/short.mp4              # contact sheet with the last frame, to look at

# 7. Hand-over and upload
python release.py vN ready
python upload_long.py vN <channel_id> public --publish-at 2026-01-01T14:00:00+02:00
python youtube_upload_short.py vN <channel_id> public
```

`docs/PRODUCTION_BRIEF.md` is the full working brief the production agents followed, with the reasoning behind
each rule.

## What is not included

* Media: character sheets, scene images, Veo clips, music beds, the sound-effect library, voices, rendered videos,
  thumbnails, and the Real-ESRGAN / Stable Audio model weights.
* The episode folders (`vN/`), the compilations, the dashboard's statistics database, logs and publishing records.
* Editorial plans, growth strategy, publishing schedules, account status and collaboration documents.
* Browser-automation helpers that drove Google Flow's web UI and the per-episode prompt JSON files.

All narration, prompts and code in this repository were written for the series; the character Leo is original.

## License

MIT, see [LICENSE](LICENSE). Media assets, the Leo character and the episode scripts are not covered by this license and are not included.
