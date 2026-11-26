"""Leo's voice, step 1: Voice Design candidates with Fish Audio Drama 3 (owner decision 2026-11-02:
test Drama 3 through the Hugging Face PRO subscription for one month).

Calls the official ZeroGPU Space fishaudio/Drama-3 ("Design" mode) with the HF token stored on this
PC, so the takes use the owner's own PRO GPU quota. Each candidate is saved as
voice/candidates/leo_cand_NN.wav, plus candidates.json with the exact text, description and settings.
The owner picks one by ear; pick_voice.py then copies it to voice/leo_en_v1.wav.

Runs with:  python voice\\design_leo.py [--n 8]
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import httpx
from gradio_client import Client
from huggingface_hub import get_token

SPACE = "fishaudio/Drama-3"
SPACE_URL = "https://fishaudio-drama-3.hf.space"
MODEL_REVISION = "e0a9218aa48888270f06ef1ed9ea67622c0e17d2"  # fishaudio/drama-3, preloaded by the Space
OUT = Path(__file__).resolve().parent / "candidates"

# The owner's description, condensed to the Space's 300-character limit.
DESCRIPTION = ("Young adult male narrator, natural American English, warm mid-range voice, clear and relaxed. "
               "A curious friend telling you something he just noticed about human behavior. Dry, understated "
               "humor; a slight smile when he catches himself being ridiculous; softer in vulnerable moments.")
SCENE = "Recording a calm, conversational psychology explainer in a quiet room, close to the microphone."
# What every candidate says: about 14 s, plain words only, so it can serve as the cloning reference.
TEXT = ("Have you ever rewritten a simple text three times before sending it? I do that too. "
        "It turns out our brains are very good at worrying about small things. "
        "And once you see why, it gets a little easier to laugh at yourself.")
TEMPERATURES = [0.7, 0.8, 0.9, 1.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    assert len(DESCRIPTION) <= 300 and len(SCENE) <= 200 and len(TEXT) <= 600
    OUT.mkdir(parents=True, exist_ok=True)
    token = get_token()
    client = Client(SPACE, token=token, verbose=False)
    meta_path = OUT / "candidates.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {
        "space": SPACE, "model": "fishaudio/drama-3", "model_revision": MODEL_REVISION,
        "mode": "Design", "name": "Leo", "description": DESCRIPTION, "scene": SCENE, "text": TEXT,
        "candidates": []}
    start = len(meta["candidates"])
    for i in range(start, start + a.n):
        temp = TEMPERATURES[i % len(TEMPERATURES)]
        t0 = time.time()
        result = client.predict(TEXT, "Design", "clone1", "", "Leo", DESCRIPTION, SCENE, temp, 0.9, 0,
                                api_name="/perform")
        # (streamed audio, metrics text, take dropdown update): the take id is the dropdown's value.
        metrics = next((r for r in result if isinstance(r, str) and "real time" in r), "")
        take_id = next((r.get("value") for r in result if isinstance(r, dict) and r.get("value")), None)
        if "went quiet" in metrics:
            print(f"candidate {i + 1}: cut short by the model, skipped ({take_id})")
            continue
        if not take_id:
            print(f"candidate {i + 1}: no take id in {result!r}")
            continue
        wav = httpx.get(f"{SPACE_URL}/api/takes/{take_id}.wav", headers={"Authorization": f"Bearer {token}"},
                        timeout=60, follow_redirects=True)
        wav.raise_for_status()
        path = OUT / f"leo_cand_{i + 1:02d}.wav"
        path.write_bytes(wav.content)
        meta["candidates"].append({"file": path.name, "take_id": take_id, "temperature": temp, "top_p": 0.9,
                                   "top_k": 0, "seconds_to_generate": round(time.time() - t0, 1),
                                   "made_at": datetime.now().isoformat(timespec="seconds")})
        meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print(f"candidate {i + 1}: {path.name} temp {temp} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
