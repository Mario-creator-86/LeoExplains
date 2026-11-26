"""Assemble the Leo stickman video: scene images + motion, ElevenLabs voice, music, captions.

Inputs (this folder): scenes.json, images/leo_scene_NN.webp, voiceover.mp3,
voiceover.alignment.json (ElevenLabs character timestamps). Output: leo_procrastination.mp4
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
FPS = 30
W, H = 1920, 1080
TAIL = 1.6  # seconds held on the last scene after the voice ends
# music beds: <id>.mp3 files plus music_library.json next to them (not included in this repository)
MUSIC_DIR = Path(os.environ.get("LEO_MUSIC_DIR", str(HERE.parent / "music")))


def run(cmd):
    subprocess.run(cmd, check=True)


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def scene_starts(scenes, align):
    """Start time of each scene: the first spoken character after each newline separator."""
    chars, starts = align["characters"], align["character_start_times_seconds"]
    text = "".join(chars)
    assert text == "\n".join(scenes), "alignment text differs from narration"
    result, pos = [], 0
    for line in scenes:
        result.append(starts[pos] if pos < len(starts) else starts[-1])
        pos += len(line) + 1
    result[0] = 0.0
    return result


def words(align):
    """(word, start, end) from character timings."""
    out, cur, t0, t1 = [], "", None, None
    for ch, s, e in zip(align["characters"], align["character_start_times_seconds"],
                        align["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                out.append((cur, t0, t1))
            cur, t0 = "", None
            continue
        if not cur:
            t0 = s
        cur += ch
        t1 = e
    if cur:
        out.append((cur, t0, t1))
    return out


def ass_time(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def captions(align, path):
    """Short chunks (max 4 words, break on punctuation), white with yellow on the spoken word."""
    ws = words(align)
    chunks, cur = [], []
    for w in ws:
        cur.append(w)
        if len(cur) >= 4 or re.search(r"[.,!?:;\"]$", w[0]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    lines = []
    for ci, ch in enumerate(chunks):
        end_chunk = chunks[ci + 1][0][1] if ci + 1 < len(chunks) else ch[-1][2] + 0.4
        end_chunk = min(end_chunk, ch[-1][2] + 0.6)
        for wi, (wtxt, ws_, we_) in enumerate(ch):
            start = ws_ if wi else ch[0][1]
            stop = ch[wi + 1][1] if wi + 1 < len(ch) else end_chunk
            parts = []
            for k, (t, _, _) in enumerate(ch):
                t = t.replace("{", "(").replace("}", ")")
                parts.append("{\\c&H00D7FF&}" + t + "{\\c&HFFFFFF&}" if k == wi else t)
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(stop)},Cap,,0,0,0,,"
                         + " ".join(parts))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,5,2,2,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def scene_clip(img, out, seconds, index):
    """Slow push in / pull out with a gentle drift, alternating per scene."""
    frames = max(1, round(seconds * FPS))
    zoom_in = index % 2 == 0
    z = (f"1+0.08*on/{frames}" if zoom_in else f"1.08-0.08*on/{frames}")
    drift = ["iw/2-(iw/zoom/2)", "iw/2-(iw/zoom/2)+(on/{f})*40", "iw/2-(iw/zoom/2)-(on/{f})*40"]
    x = drift[index % 3].format(f=frames)
    vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=decrease,"
          f"pad={W*2}:{H*2}:(ow-iw)/2:(oh-ih)/2:white,"
          f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
          f"format=yuv420p")
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(img), "-vf", vf,
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-r", str(FPS), str(out)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--music", default="yal-calm-angels-dream",
                        help="track id from the music library (LEO_MUSIC_DIR), or 'none'")
    parser.add_argument("--music-db", type=float, default=-30.0, help="music gain under voice")
    parser.add_argument("--out", default="leo_procrastination.mp4")
    parser.add_argument("--reuse", action="store_true", help="reuse work/video_silent.mp4")
    args = parser.parse_args()
    WORK.mkdir(exist_ok=True)
    data = json.loads((HERE / "scenes.json").read_text(encoding="utf-8"))
    scenes = [data[str(n)]["narration"] for n in range(1, len(data) + 1)]
    align = json.loads((HERE / "voiceover.alignment.json").read_text(encoding="utf-8"))
    voice = HERE / "voiceover.mp3"
    total = probe_duration(voice) + TAIL
    starts = scene_starts(scenes, align) + [total]

    silent = WORK / "video_silent.mp4"
    if not (args.reuse and silent.exists()):
        listing = []
        for i in range(len(scenes)):
            clip = WORK / f"clip_{i + 1:02d}.mp4"
            scene_clip(HERE / "images" / f"leo_scene_{i + 1:02d}.webp", clip,
                       starts[i + 1] - starts[i], i)
            listing.append(f"file '{clip.as_posix()}'")
            print(f"scene {i + 1}: {starts[i]:.2f}-{starts[i + 1]:.2f}s")
        (WORK / "clips.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i",
             str(WORK / "clips.txt"), "-c", "copy", str(silent)])

    ass = WORK / "captions.ass"
    captions(align, ass)
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:")
    out = HERE / args.out
    inputs = ["-i", str(silent), "-i", str(voice)]
    if args.music == "none":
        audio = f"[1:a]apad,atrim=0:{total:.2f},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    else:
        inputs += ["-stream_loop", "-1", "-i", str(MUSIC_DIR / f"{args.music}.mp3")]
        audio = (f"[1:a]apad,atrim=0:{total:.2f}[v];"
                 f"[2:a]atrim=0:{total:.2f},volume={args.music_db}dB,afade=t=in:d=3,"
                 f"afade=t=out:st={total - 4:.2f}:d=4[m];"
                 f"[v][m]amix=inputs=2:duration=first:normalize=0,"
                 f"loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    run(["ffmpeg", "-v", "error", "-y", *inputs,
         "-filter_complex", f"[0:v]subtitles='{ass_arg}'[vo];{audio}",
         "-map", "[vo]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
         "-t", f"{total:.2f}", str(out)])
    print("wrote", out, f"{total:.1f}s")


if __name__ == "__main__":
    main()
