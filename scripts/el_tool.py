"""ElevenLabs for Leo Explains: narration with character timings.

The API key is read from the environment variable ELEVENLABS_API_KEY (see .env.example); the voice can
be changed with ELEVENLABS_VOICE_ID. The key is never printed, logged or written anywhere.

usage: el_tool.py check
           key present; no network call, nothing billed
       el_tool.py tts <text_file> <out.mp3> [--alignment out.json] [--voice ID] [--model ID]
                      [--stability 0.5] [--similarity 0.75] [--style 0] [--dry-run]
           PAID (characters): POST /v1/text-to-speech/{voice}/with-timestamps. Writes the mp3 and
           the alignment ({characters, character_start_times_seconds,
           character_end_times_seconds}, the format of vN/voiceover.alignment.json; default
           <out>.alignment.json -> for vN/voiceover.mp3 that is vN/voiceover.alignment.json).
           For an episode: el_tool.py tts vN/narration.txt vN/voiceover.mp3 (the text must be the
           scenes' narration joined by "\\n", as assemble.scene_starts expects). --dry-run prints
           the request (without the key) and the character count, and sends nothing.
       el_tool.py subscription
           free GET /v1/user/subscription: characters used / limit
Library: api_key(), call(path, key, body=None, accept=..., method=...), tts(text, out_mp3, ...)
(sfx_tool.py imports api_key and call.)
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOST = "https://api.elevenlabs.io"
VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "nPczCjzI2devNBz1zQrb")   # default: "Brian", an ElevenLabs premade voice
MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75}   # ElevenLabs API defaults
MAX_CHARS = 10000                       # eleven_multilingual_v2 per-request limit


def api_key() -> str:
    """The ElevenLabs API key from the environment (never print it)."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set (see .env.example)")
    return key


def call(path, key, body=None, accept="application/json", method=None, timeout=300):
    """One ElevenLabs request; returns the raw response bytes. Errors are reported without the key."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HOST + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"xi-api-key": key, "Accept": accept,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ElevenLabs HTTP {e.code} on {path}: "
                         f"{e.read()[:600].decode(errors='replace')}") from None


def tts_request(text, voice=VOICE, model=MODEL, settings=None):
    path = f"/v1/text-to-speech/{voice}/with-timestamps?output_format={OUTPUT_FORMAT}"
    body = {"text": text, "model_id": model,
            "voice_settings": {**DEFAULT_SETTINGS, **(settings or {})}}
    return path, body


def tts(text, out_mp3, alignment_out=None, voice=VOICE, model=MODEL, settings=None, key=None):
    """PAID. Narration audio + character alignment (the text as sent, not the normalised one, so
    it matches scenes.json exactly). Returns (mp3 path, alignment dict)."""
    if len(text) > MAX_CHARS:
        raise SystemExit(f"text is {len(text)} characters (limit {MAX_CHARS} per request)")
    path, body = tts_request(text, voice, model, settings)
    data = json.loads(call(path, key or api_key(), body))
    audio = base64.b64decode(data["audio_base64"])
    align = data.get("alignment") or {}
    align = {k: align.get(k, []) for k in ("characters", "character_start_times_seconds",
                                           "character_end_times_seconds")}
    if "".join(align["characters"]) != text:
        print("WARNING: alignment text differs from the text sent")
    out_mp3 = Path(out_mp3)
    out_mp3.write_bytes(audio)
    alignment_out = Path(alignment_out or out_mp3.with_suffix(".alignment.json"))
    alignment_out.write_text(json.dumps(align, ensure_ascii=False), encoding="utf-8")
    return out_mp3, align


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("subscription")
    t = sub.add_parser("tts")
    t.add_argument("text_file", type=Path)
    t.add_argument("out", type=Path)
    t.add_argument("--alignment", type=Path)
    t.add_argument("--voice", default=VOICE)
    t.add_argument("--model", default=MODEL)
    t.add_argument("--stability", type=float)
    t.add_argument("--similarity", type=float)
    t.add_argument("--style", type=float)
    t.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.cmd == "check":
        key = api_key()
        print(f"ElevenLabs key: found in ELEVENLABS_API_KEY ({'ok' if len(key) > 20 else 'short?'}"
              f"); voice {VOICE} (Brian), model {MODEL}; no request sent")
        return
    if a.cmd == "subscription":
        s = json.loads(call("/v1/user/subscription", api_key()))
        print(json.dumps({k: s.get(k) for k in ("tier", "character_count", "character_limit",
                                                "next_character_count_reset_unix")}, indent=1))
        return
    text = a.text_file.read_text(encoding="utf-8-sig").strip("\n")
    settings = {k: v for k, v in (("stability", a.stability), ("similarity_boost", a.similarity),
                                  ("style", a.style)) if v is not None}
    if a.dry_run:
        path, body = tts_request(text, a.voice, a.model, settings)
        body["text"] = body["text"][:80] + ("..." if len(text) > 80 else "")
        print(json.dumps({"POST": path, "body": body, "characters": len(text),
                          "out": str(a.out),
                          "alignment": str(a.alignment or a.out.with_suffix(".alignment.json"))},
                         indent=1, ensure_ascii=False))
        print("dry run: nothing sent")
        return
    out, align = tts(text, a.out, a.alignment, a.voice, a.model, settings)
    end = align["character_end_times_seconds"][-1] if align["characters"] else 0
    print(f"wrote {out} and its alignment ({len(text)} characters, voice ends {end:.2f} s)")


if __name__ == "__main__":
    main()
