# Brief: from finished images to published video (Leo Explains, v11 onward)

> Public copy: this is the working brief the production agents followed, kept as documentation of how the
> scripts are used in order. Paths, the channel id and account handles were replaced with placeholders.

Project folder: `scripts/` of this repository (episode folders `vN/` live next to the scripts).
Python for every script below (uploads, ElevenLabs, render): the project's virtualenv `python`.
YouTube channel id: `<CHANNEL_ID>` (your channel's UC... id). Never print tokens or API keys.
Everything public is in ENGLISH. Look at a finished episode (v10) for what each file should look like.

A video is ready to produce when `vN/images` has scene_01..scene_40 with all 4 poses (scene_NN, b, c, d).
Already in place for v11-v20: chatgpt.md, scenes.json, narration.txt, voiceover.mp3 (+alignment),
music.json, sfx.json + sfx/, meta.json, batch files.

## 1. Veo key clips (Google Flow, Claude in Chrome, manual mode)
- 2-3 clips per video, ONLY key scenes: usually the opening hook (scene 01 or 03), one emotional peak in
  the middle, and optionally the ending. Choose from scenes.json so the motion fits the story.
- Open the video's own Flow project (Flow home lists projects by date; the image agents made one per
  video). Settings: "Videoclip", Veo 3.1 Lite, "Cadre" (first frame = the scene's A image via
  "Început" → pick image → "Adaugă la solicitare"), 16:9, x1 — 10 credits per clip. Prompt: Leo's
  small natural motion for that moment, camera static or a slow push-in, same style, no text. End every Veo
  prompt with "No dialogue, no speech, no singing, no music; quiet room tone only." Veo always makes a sound track
  with the clip (render.py throws it away), and when that audio part fails Flow fails the whole clip with
  "Conținutul audio nu a putut fi generat" (seen 2026-11-01, usually when characters seem to talk). On that error:
  remove any talking/laughing/shouting from the prompt, add the line above, retry once; then use stills.
- Download the free "1080p upscale" and save as `vN/images/scene_NN_clip.mp4`.
- Watch the result (extract frames with ffmpeg): it must not contradict the story (e.g. v6: a fridge that
  should stay closed was opened → rejected). Reject bad clips into `vN/rejected/`; one retry at most.
- Never spend more than 40 credits per video. Use your own Chrome tab; never touch other agents' tabs.
  Never use the Flow agent chat. Stop and report if credits are insufficient.

- Before rendering, look at every scene's 4 poses (contact sheet) for drawing errors (owner 2026-11-01): every
  character has two arms and two legs attached to the body, no floating/detached limb, no limb growing out of an
  object, no extra hand, face intact, cap on Leo. Move a bad pose to `vN/rejected/` (render.py uses the remaining
  poses) and note it for the next Flow run.

## 2. Render
- `<python> render.py vN` (reads music.json and sfx.json; music bed must stay very quiet, -40 LUFS
  before ducking — do NOT raise it). Output `vN/video.mp4`.
- Music choice (2026-11-01): for episodes not yet rendered, set `vN/music.json` "track" to one of our OWN Google
  Flow Music beds (`flow-*` ids in music_library.json: lo-fi, acoustic, piano, playful, jazz, ambient, hopeful;
  commercial use verified via the Google AI Pro/Plus benefit), picked by the episode's mood, so the same music is
  safe on YouTube, TikTok, Instagram, Facebook and Pinterest video pins. Vary the bed between consecutive episodes.
- Check: duration ≈ voiceover; extract ~6 frames into a contact sheet (captions readable, Leo consistent,
  clips present); quick audio check that voice dominates and SFX play at the right scenes.

## 3. Thumbnail + upload
- **Thumbnail = a DEDICATED image drawn in Flow** (team vote 2026-11-06; replaces "scene crop + text on a band"):
  Leo big, close-up, one strong emotion, plain simple background, EMPTY space on one side for text. Prompt in
  `flow_prompts/thumbnail_prompts.json` (reference `character/leo_cap_sheet.png` + the episode's `cast.json` look);
  one Flow tab, one image at a time; save as `vN/thumbnail_hero.png`; anatomy check (two arms, no floating limbs).
  The text (2-3 words) is placed by `<python> thumbnail.py vN --hero vN/thumbnail_hero.png --text "TWO WORDS" --side left|right`
  — never drawn by the AI. ChatGPT proposes 3 text variants, the team picks one (optionally A/B test in YouTube Studio,
  long videos only). Legacy `thumbnail.py vN <scene> "<hook>"` still works but is no longer the standard.
  YouTube Shorts: no custom thumbnail through the API, only the first frame counts.
- `<python> upload_long.py vN <CHANNEL_ID> public` — adds links + study line, sets the
  thumbnail, writes `vN/youtube_result.json`. (youtube_upload_series.py is gone — antivirus; use upload_long.py.)

## 4. Shorts (read SHORTS_BRIEF.md and TIKTOK_BRIEF.md fully)
- YouTube Short < 60 s: story-complete short version of the whole video, must include the Veo scenes.
  `shorts.py vN --plan` writes the plan; add a per-video plan in shorts.py if it needs one; render → `vN/short.mp4`.
- Upload: `<python> youtube_upload_short.py vN <CHANNEL_ID> public` (links to the long video).
- In YouTube Studio (Chrome), set the Short's "Related video" to the long video.
- TikTok / Reels cut: 70-90 s (always ≥ 1 minute) → `vN/short_tiktok.mp4`.
- Post `short_tiktok.mp4` on TikTok @<handle> as in TIKTOK_BRIEF.md (AI-generated label on,
  caption + hashtags + "full video on YouTube"); write `vN/tiktok_result.json`.

## 5. Facebook + Instagram (read SOCIAL_BRIEF.md fully)
- Facebook Page facebook.com/<your-page>: one Reel (short_tiktok.mp4) + one photo post; captions and
  hashtags adapted to Facebook; AI label; record in `vN/facebook_result.json`.
- Instagram @<handle>: one Reel + one carousel (slides from scene images); IG-style caption and
  hashtags; record in `vN/instagram_result.json`. Copy the structure of v10's result files.

## Report
Per video: YouTube long + Short links, TikTok/Facebook/Instagram links, credits used, anything skipped.

## UPDATE 2026-11-01 (owner-approved) — production no longer publishes
Follow PUBLISHING_SCHEDULE.md. Production agents do steps 1–4 up to finished files only: Veo clips, render,
thumbnail, Short (NO end pointer since 2026-11-04: Shorts just end; the YouTube related-video link carries viewers to the episode), TikTok cut at 1080x1920
filling the vertical frame with hook text in the first 2 s, carousel slides (slide 2 = second hook, alt text),
FB/IG/TikTok captions per PUBLISHING_SCHEDULE.md §3, SRT subtitles from voiceover.alignment.json, chapters.
Then write vN/release.json {"status": "ready", "files": {...}, "captions": {...}} and STOP. Uploading and
posting are done only by the scheduled publishing tasks, one episode per day.

## Exact commands (tools upgraded 2026-11-01)
`<py>` = the project's `python`, run from the project folder; ffmpeg/ffprobe on PATH. Never print API keys.

**ElevenLabs (vault key, project files — the old scratchpad sfx_tool.py is obsolete):**
- **Voice since 2026-11-15 (owner: «Nu mai avem abonament pe huging face, deci vocea se face local»): Kokoro on this PC,**
  `python tts_kokoro.py vN [--force]` → vN/voiceover.mp3 + vN/voiceover.alignment.json
  (same files; about 15 s per Short; speed, pause and voice from team_settings.json "voice" and vN/voice.json; it reads
  "narration", the PERFORMANCE tags are not read). Episodes already voiced keep their voice. What follows is history:
- **Voice from 2026-11-02 to 2026-11-15 (one-month trial, ended): Fish Audio Drama 3, Leo's voice `voice/leo_en_v1.wav`.**
  `python tts_fish.py vN` → vN/voiceover.mp3 + vN/voiceover.alignment.json
  (same files as before). It runs in a private HF Space (FISH_SPACE; PRO GPU quota, no cost per
  episode). Each scene is one take in vN/voice_fish/; `--scene N` regenerates one scene with the same voice. The text
  sent to Fish is scenes.json "fish" (PERFORMANCE line: the narration + only [hesitates] / [small laugh] / [sighs] /
  one leading direction; never [pause], use "..."), subtitles use "narration". Every take is checked with local Whisper.
  Episodes already voiced with ElevenLabs "Brian" (v1–v23) keep it; Kokoro voices of unpublished v24–v30 are being
  replaced (leo-fish-revoice, 2/day, old files in vN/rejected/kokoro/). Kokoro (`tts_kokoro.py`, am_michael) stays
  installed only as a fallback until the owner decides at the end of the trial.
  ElevenLabs is no longer used for voice or sound effects.
- **Sound effects since 2026-11-01:** 1) reuse `sfx_library/` (320+ sounds, catalog.json, search it by description — point sfx.json at
  `../sfx_library/<name>.mp3`); 2) new sounds from the local Stable Audio 3 Small-SFX model (sfx_local.py, once the
  owner's Hugging Face access is set up); 3) never ElevenLabs sound-generation, and NOT Flow Music (its FX were
  wrong by ear on 2026-11-01). Claude cannot listen: run new sounds ONLY through
  `python sfx_local.py vN/sfx/<name>.mp3 <seconds> <3-8 plain words>`, which makes 4
  candidates and keeps the best LAION-CLAP match only at >= +0.20 (calibrated on the owner's ears). Exit 3 = uncertain
  (0.10-0.20): saved to sfx_library/review/ for the owner, use a library sound now; exit 2 = rejected. Never ship a
  sound that didn't pass. Tell the owner in the report when sfx_library/review/ has files to listen to.
- **Each sound at most ONCE per video (owner rule 2026-11-01: "nu de doua ori acelasi sunet").** The same file, or
  the same name with a number suffix (footsteps / footsteps_2), is the same sound. Don't carry an ambience (cafe,
  street, rain) through several scenes by repeating it: use it once, in the scene where it matters most. render.py and
  shorts.py refuse an sfx.json with a repeat (`render.load_sfx`): drop the repeat or pick a different sound.
- **Effects are quiet background (owner 2026-11-01: "mai incet", then still "destul de tare"):** render.py/shorts.py
  mix voice + music, normalise them, and only THEN add the effects (`render.sfx_after_loudnorm`), so the normaliser can
  no longer lift them in the pauses. On top of that, `SFX_TRIM_DB = -8` dB. Keep the usual sfx.json levels (lufs -26
  spot, about -33 ambience) and never raise them to compensate. Anything rendered before 23:00 on 2026-11-01 has
  the louder effects and must be rendered again before it is published.
- (Old, ElevenLabs — do not use) `<py> el_tool.py check` — vault readable + key present; no request, nothing billed.
- `<py> el_tool.py tts vN/narration.txt vN/voiceover.mp3 --dry-run` — shows the request and character count.
- `<py> el_tool.py tts vN/narration.txt vN/voiceover.mp3` — PAID: Brian (`nPczCjzI2devNBz1zQrb`),
  `eleven_multilingual_v2`; also writes `vN/voiceover.alignment.json` (scenes joined by "\n").
- `<py> el_tool.py subscription` — characters used / limit (free).
- `<py> sfx_tool.py vN/sfx/<name>.mp3 <secs> eleven_text_to_sound_v3 "<prompt>, no music, no voices"` — PAID;
  add `--dry-run` to only print the request. Reuse files for repeated sounds (SFX_BRIEF.md).

**YouTube Short** (story-complete; the last ~2.2 s show "Full episode on the channel / tap the link above
the title", pointing at the Related video link that the publishing task sets before it goes public):
- `<py> shorts.py vN --plan` (scenes from PLANS or the first line of `vN/short_plan.txt`; `--scenes 1,5,...` to change)
- `<py> shorts.py vN` → `vN/short.mp4`
- `<py> shorts.py vN --check vN/short_sheet.png` — must say `"ok": true` (1080x1920, 20–58 s, target 25–35 s: hook scene + the one key insight/study + payoff, −14 LUFS, voice at 0.0 s).
- **Vertical cuts use their OWN 9:16 pictures (owner decision 2026-11-01).** Each channel gets its own format, nothing
  mixed, no character ever cut. After choosing both plans (`--plan --scenes ...` for the Short and the TikTok cut), run
  `flow_prompts/build_prompts.py --vertical N` and generate every listed scene once in Flow as a 9:16 image (chip 9:16,
  0 credite only; references vN/images/scene_NN.* + the character sheet) into `vN/images_v/scene_NN.jpeg`; check each
  (all characters complete inside the picture, same scene and Leo). Optional: one 9:16 Veo key clip per episode as
  `vN/images_v/scene_NN_clip.mp4`. shorts.py refuses to render while a picked scene has no vertical image.

**TikTok / Reels cut** (picture fills 9:16, centred on Leo with a slow pan; hook text 0–2.5 s; voice at 0.0 s;
music −40 LUFS before ducking + SFX; on-TikTok action line in the last ~2 s; 1080x1920 CRF 17, ≤ 12 Mbps):
- `<py> shorts.py vN --tiktok --plan` (scenes from TIKTOK_PLANS or `vN/short_tiktok_plan.txt`; aim 70–90 s)
- `<py> shorts.py vN --tiktok [--hook "<= 8 words, the plain search phrase"] [--end "Follow for more Leo"]`
  → `vN/short_tiktok.mp4`. Hook default: topics.json `tiktok_hook`, else `hook` (≤ 8 words), else its
  question sentence, else the episode title; a WARNING means pass `--hook` yourself.
- `<py> shorts.py vN --tiktok --check vN/short_tiktok_sheet.png` — must say `"ok": true` (61–90 s);
  look at the sheet AND `vN/short_tiktok_sheet_hook.png` (first 3 s): Leo in frame, hook readable.
- **Every platform gets its own layout (owner 2026-11-03: "Tot contentul trebuie adaptat platformei").**
  `safe_zones.py` holds the strips each app covers (YouTube Shorts, TikTok, Instagram/Facebook Reels); captions,
  hook (and an end line only with --end) are placed from it. Render the Reels cut too, same scenes and hook:
  `<py> shorts.py vN --reels [--hook "..."]` → `vN/short_reels.mp4` (+ `--reels --check vN/short_reels_sheet.png`).
  YouTube gets short.mp4, TikTok short_tiktok.mp4, Instagram + Facebook Reels short_reels.mp4.
  Comic videos (PAUSED since 2026-11-06, see COMIC_FORMAT.md): `social/comics/comic_short.py` uses the same zones (panels in the visible area, the psychology
  text as a large card). When a phone screenshot shows covered text, fix the numbers in safe_zones.py.
- Do NOT make a 9.5 MB copy any more; only if an upload tool truly cannot take the full file:
  add `--small` (→ `vN/short_tiktok_small.mp4`). The plan file follows the output name
  (`--out test_x.mp4` → `vN/test_x_plan.txt`), so test renders never overwrite published plans.

**Subtitles:** `<py> make_srt.py vN` and `<py> make_srt.py vN --short` (release.py calls them if the SRTs are missing).

**Hand-over (last step, then STOP):**
- Put the captions in `vN/captions.json`: `{"tiktok": "...", "ig_reel": "...", "ig_carousel": "...", "fb_reel": "...", "fb_post": "..."}`.
- `<py> release.py vN ready --dry-run` — checks files (video.mp4, thumbnail.png, short.mp4, short_tiktok.mp4,
  captions_en.srt, short_captions_en.srt, social/ig/vN/slide_*.jpg, optional social/fb/vN/*.jpg) and durations
  (long ≈ voiceover + 4.6 s, Short < 60 s, TikTok 61–90 s, both 1080x1920); errors block, caption slips warn.
- `<py> release.py vN ready` — writes `vN/release.json` {"status": "ready", ...}. Fix every WARNING you can.

**Publishing tasks** (not production): `<py> release.py next tiktok` → lowest ready vN still missing that step;
after posting, `<py> release.py vN step tiktok --url <url>` (steps: yt_long, yt_short, tiktok, ig_reel,
ig_carousel, fb_reel, fb_post; a done step is refused, never re-upload); `<py> release.py vN status`.

## Short endings and YouTube volume (2026-11-04, from vidIQ "How to Escape EVERY YouTube Shorts View Jail")
- Shorts, TikTok and Reels cuts just END: no "subscribe", no "full episode" end card (shorts.py SHOW_END=False). Viewers swipe at the sign-off.
- YouTube gets at most 2 Shorts a day, both episode/psychology Shorts. The comic Short is paused since 2026-11-06 (COMIC_FORMAT.md decision: five gates before any comic video). No recuts of already-posted episodes on YouTube, because mass-produced or repetitive uploads land in the "0-view jail".
- To break a view jail, change something MEANINGFUL: format, topic or motion (visual movement on screen). Do not just post more of the same.
