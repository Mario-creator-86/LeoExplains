"""Free, local sound effects for Leo Explains with Stable Audio 3 Small-SFX (Stability AI Community License,
free commercial use under US$1M/year revenue; the owner accepted the model terms on Hugging Face on
2026-11-01, account logged in with `hf auth login`). Replaces sfx_tool.py (ElevenLabs, paid) with the SAME
command shape, so SFX_BRIEF.md / sfx.json workflows don't change:
  sfx_local.py <out_mp3> <seconds> <prompt...> [--candidates 4] [--min-score 0.20] [--review-score 0.10] [--steps 8] [--cfg 1.0]
  sfx_local.py --check                       model files present, no generation
Keep the prompt SHORT, 3–8 plain words for ONE sound ("fridge door opening", "phone notification sound"):
on 2026-11-01 long, detailed prompts scored negative on every candidate while the short ones scored +0.19..+0.32. Output: mono-compatible stereo 44.1 kHz mp3 192 kbps,
normalised to about -20 LUFS (render.py re-levels every effect from sfx.json "lufs" anyway).
Claude cannot listen, so every sound is checked with LAION CLAP (sfx_score.py): N candidates are generated,
the one that best matches the prompt is kept, kept automatically only if it scores >= --min-score (0.20); a best score between --review-score (0.10) and 0.20
is saved to sfx_library/review/ for the owner to listen to (exit 3) and the episode uses a library sound meanwhile;
below 0.10 nothing is written (exit 2). Calibrated on 2026-11-01 against the owner's ears: the 3 sounds the
owner approved scored +0.13..+0.42, the 2 rejected ones -0.17/-0.18; known-good library sounds +0.25..+0.41;
second round: approved +0.32 and +0.196, rejected +0.187 — so 0.10..0.20 is uncertain and goes to review.
Before generating anything, check sfx_library/catalog.json — about 320 sounds already exist.
Runs with:  python   (CPU: a few seconds to ~1 minute per sound)
"""
import argparse
import subprocess
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
MODEL = "small-sfx"
REPO = "stabilityai/stable-audio-3-small-sfx"
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")   # path to ffmpeg, default: on PATH
_model = None


def check():
    from huggingface_hub import scan_cache_dir
    for r in scan_cache_dir().repos:
        if r.repo_id == REPO:
            print(f"{REPO}: {r.size_on_disk / 1e9:.2f} GB cached, {len(list(r.revisions))} revision(s)")
            return True
    print(f"{REPO}: not downloaded (run: hf download {REPO})")
    return False


def model():
    global _model
    if _model is None:
        import torch
        from stable_audio_3 import StableAudioModel
        torch.set_num_threads(max(2, (torch.get_num_threads() or 4) - 2))   # leave CPU for the owner
        _model = StableAudioModel.from_pretrained(MODEL, device="cpu", model_half=False)
    return _model


def generate(out: Path, seconds: float, prompt: str, steps=8, seed=-1, cfg=1.0):
    import torch
    import soundfile as sf
    m = model()
    t0 = time.time()
    audio = m.generate(prompt=prompt, duration=float(seconds), steps=steps, cfg_scale=cfg, seed=seed,
                       truncate_output_to_duration=True)
    sr = getattr(m, "sample_rate", None) or getattr(getattr(m, "model_config", {}), "get", lambda k, d: d)("sample_rate", 44100)
    a = audio
    if isinstance(a, torch.Tensor):
        a = a.detach().float().cpu()
        if a.dim() == 3:
            a = a[0]
        a = a.numpy().T          # (samples, channels)
    peak = max(1e-6, float(abs(a).max()))
    a = a / peak * 0.9
    wav = out.with_suffix(".tmp.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(wav, a, int(sr))
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(wav), "-af", "loudnorm=I=-20:TP=-2",
                    "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k", str(out)], check=True)
    wav.unlink()
    print(f"wrote {out} ({seconds}s, {steps} steps, {time.time() - t0:.0f}s)")


def best_of(out: Path, seconds: float, prompt: str, candidates=4, min_score=0.20, steps=8, cfg=1.0,
            review_score=0.10):
    """Generate `candidates` versions, keep the best CLAP match if it reaches min_score. Returns the score
    or None (nothing written)."""
    from sfx_score import scores
    tmp = out.parent / f".cand_{out.stem}"
    files = []
    for k in range(candidates):
        f = tmp / f"{k}.mp3"
        generate(f, seconds, prompt, steps, seed=1000 + k, cfg=cfg)
        files.append(f)
    sc = scores(prompt, files)
    best = max(range(len(files)), key=lambda i: sc[i])
    print("CLAP scores:", ", ".join(f"{s:+.3f}" for s in sc))
    ok = sc[best] >= min_score
    if ok:
        out.parent.mkdir(parents=True, exist_ok=True)
        files[best].replace(out)
        print(f"kept candidate {best} ({sc[best]:+.3f}) -> {out}")
    elif sc[best] >= review_score:
        review = Path(__file__).resolve().parent / "sfx_library" / "review"
        review.mkdir(parents=True, exist_ok=True)
        dest = review / f"{out.stem}__{sc[best]:.3f}.mp3"
        files[best].replace(dest)
        print(f"REVIEW: best {sc[best]:+.3f} is uncertain -> {dest} (owner listens; use a library sound now)")
        ok = None
    else:
        print(f"REJECTED: best {sc[best]:+.3f} < {review_score} - use a library sound or none")
    for f in files:
        f.unlink(missing_ok=True)
    tmp.rmdir()
    return sc[best] if ok else ("review" if ok is None else None)


def main():
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("seconds", type=float)
    p.add_argument("prompt", nargs="+")
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--candidates", type=int, default=4)
    p.add_argument("--min-score", type=float, default=0.20)
    p.add_argument("--review-score", type=float, default=0.10)
    p.add_argument("--cfg", type=float, default=1.0)
    a = p.parse_args()
    if not 0.5 <= a.seconds <= 30:
        raise SystemExit("seconds must be 0.5-30 for an effect")
    s = best_of(a.out, a.seconds, " ".join(a.prompt), a.candidates, a.min_score, a.steps, a.cfg,
                a.review_score)
    sys.exit(3 if s == "review" else 0 if s is not None else 2)


if __name__ == "__main__":
    main()
