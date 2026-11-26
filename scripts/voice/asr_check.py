"""Hear what a take actually says: local Whisper (openai/whisper-base.en, CPU, free) with word timings.

Used to check Fish Drama 3 takes: every word of the line is there, no direction tag was read aloud,
and where each word starts (for subtitles). Never sends audio anywhere.

Runs with:  python voice\\asr_check.py file.wav [file2.wav ...]
"""
import os
import re
import sys
import unicodedata
import warnings
from functools import lru_cache

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")
# LEO_LANG=ro (2026-11-03, Romanian TikTok versions): multilingual whisper-small, told the language
LANG = os.environ.get("LEO_LANG", "en")
MODEL = "openai/whisper-base.en" if LANG == "en" else "openai/whisper-small"
WHISPER_LANG = {"ro": "romanian"}.get(LANG)
SR = 16000


@lru_cache(maxsize=1)
def recognizer():
    from transformers import pipeline
    return pipeline("automatic-speech-recognition", model=MODEL, device="cpu")


def load16k(path):
    import torch
    import torchaudio.functional as F
    wav, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = torch.from_numpy(wav.mean(axis=1))
    if rate != SR:
        mono = F.resample(mono, rate, SR)
    return mono.numpy()


def words_in(path):
    """[(word, start_s, end_s)] heard in the file."""
    audio = load16k(path)
    extra = {"generate_kwargs": {"language": WHISPER_LANG, "task": "transcribe"}} if WHISPER_LANG else {}
    out = recognizer()({"raw": audio, "sampling_rate": SR}, return_timestamps="word", chunk_length_s=30, **extra)
    return [(c["text"].strip(), float(c["timestamp"][0] or 0), float(c["timestamp"][1] or c["timestamp"][0] or 0))
            for c in out.get("chunks", [])]


def norm(text):
    # diacritics folded (ă â î ș ț -> a a i s t) so Romanian words compare whole
    # "Ți-a" / "ția": a hyphen joins a Romanian clitic to its word, so drop it instead of splitting
    text = unicodedata.normalize("NFKD", text.lower().replace("’", "'").replace("-", ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9' ]+", " ", text).split()


def compare(expected, heard):
    """(missing words, extra words) between the expected line and what Whisper heard (bag of words)."""
    from collections import Counter
    e, h = Counter(norm(expected)), Counter(norm(" ".join(w for w, _, _ in heard)))
    return sorted((e - h).elements()), sorted((h - e).elements())


if __name__ == "__main__":
    for p in sys.argv[1:]:
        heard = words_in(p)
        dur = sf.info(p).duration
        print(f"{p}: {dur:.1f}s | {' '.join(w for w, _, _ in heard)}")
