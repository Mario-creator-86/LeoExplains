"""Read-only Whisper transcript of finished mp4 files (whisper-base.en, voice/asr_check.py).

Usage (python venv):  python whisper_mp4.py out.txt a/short.mp4 [b/short.mp4 ...]
Never modifies the mp4: the audio is decoded by ffmpeg into a temp wav.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "voice"))
import asr_check  # noqa: E402


def main():
    out, files = Path(sys.argv[1]), sys.argv[2:]
    lines = []
    for f in files:
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "a.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
            heard = asr_check.words_in(wav)
        lines.append(f"=== {f} ===")
        lines.append("FULL: " + " ".join(w for w, _, _ in heard))
        lines.append("WORDS:")
        lines += [f"  {s:5.2f}-{e:6.2f}  {w}" for w, s, e in heard]
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print("written", out)


main()
