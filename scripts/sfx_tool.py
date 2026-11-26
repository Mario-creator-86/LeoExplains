"""ElevenLabs sound effects for Leo Explains (ELEVENLABS_API_KEY from the environment, never printed).

PAID (credits per generation): POST /v1/sound-generation. Reuse a generated file for repeated
sounds instead of generating again (SFX_BRIEF.md).

usage: sfx_tool.py <out_mp3> <seconds> <model_id|default> <prompt...> [--dry-run]
         model: eleven_text_to_sound_v3 (current), or "default" (the API's default model)
         seconds: 0.5-30; prompts end with "no music, no voices" (SFX_BRIEF.md)
         --dry-run: print the request (without the key) and send nothing
       sfx_tool.py --check       key present; no request sent
example: sfx_tool.py v21/sfx/door.mp3 1.5 eleven_text_to_sound_v3 "a wooden door closing softly, no music, no voices"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from el_tool import api_key, call  # noqa: E402

MODEL = "eleven_text_to_sound_v3"


def request_body(secs, model, prompt):
    if not 0.5 <= secs <= 30:
        raise SystemExit(f"seconds must be 0.5-30 (got {secs})")
    body = {"text": prompt, "duration_seconds": secs, "prompt_influence": 0.5}
    if model != "default":
        body["model_id"] = model
    return body


def main():
    args = [x for x in sys.argv[1:] if x != "--dry-run"]
    dry = len(args) != len(sys.argv) - 1
    if args == ["--check"]:
        api_key()
        print("ElevenLabs key: found in ELEVENLABS_API_KEY; no request sent")
        return
    if len(args) < 4:
        raise SystemExit(__doc__)
    out, secs, model = Path(args[0]), float(args[1]), args[2]
    body = request_body(secs, model, " ".join(args[3:]))
    if dry:
        print(json.dumps({"POST": "/v1/sound-generation", "body": body, "out": str(out)},
                         indent=1, ensure_ascii=False))
        print("dry run: nothing sent")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(call("/v1/sound-generation", api_key(), body, accept="audio/mpeg"))
    print("wrote", out, model)


if __name__ == "__main__":
    main()
