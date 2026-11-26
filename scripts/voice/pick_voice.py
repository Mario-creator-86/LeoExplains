"""Leo's voice, step 2: make the candidate the owner picked the permanent reference.

Copies voice/candidates/leo_cand_NN.wav to voice/leo_en_v1.wav and writes voice/leo_en_v1.json with
the exact transcript, the model and revision, the Voice Design description and the settings, so every
episode, Short and single-scene regeneration clones the same voice (tts_fish.py reads this file).
Refuses to overwrite an existing leo_en_v1 (a new voice is leo_en_v2).

Runs with:  python voice\\pick_voice.py NN
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent


def main():
    n = int(sys.argv[1])
    meta = json.loads((HERE / "candidates" / "candidates.json").read_text(encoding="utf-8"))
    cand = next(c for c in meta["candidates"] if c["file"] == f"leo_cand_{n:02d}.wav")
    wav, json_out = HERE / "leo_en_v1.wav", HERE / "leo_en_v1.json"
    if wav.exists() or json_out.exists():
        raise SystemExit("leo_en_v1 exists already; a different voice must be saved as leo_en_v2")
    shutil.copyfile(HERE / "candidates" / cand["file"], wav)
    info = sf.info(str(wav))
    json_out.write_text(json.dumps({
        "file": wav.name,
        "transcript": meta["text"],
        "seconds": round(info.duration, 2),
        "sample_rate": info.samplerate,
        "made_with": {"model": meta["model"], "model_revision": meta["model_revision"], "space": meta["space"],
                      "mode": meta["mode"], "name": meta["name"], "description": meta["description"],
                      "scene": meta["scene"], "temperature": cand["temperature"], "top_p": cand["top_p"],
                      "top_k": cand["top_k"], "take_id": cand["take_id"], "candidate": cand["file"]},
        "use": "tts_fish.py clones this reference for every scene (temperature 0.8, top_p 0.9)",
        "picked_by": f"owner, {datetime.now():%Y-%m-%d}",
    }, indent=1), encoding="utf-8")
    print("saved", wav, "and", json_out)


if __name__ == "__main__":
    main()
