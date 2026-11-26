"""Production settings the TEAM owns (owner 2026-11-12: «Echipa trebuie sa aibă libertatea totala ... Format, durata,
postări, canale, sunet, viteza voce, numele persoanei din Fish»).

The team changes team_settings.json (next to this file) through a vote and the leo-change job; the scripts read it at
start. A key that is missing keeps the built-in default, so an absent file changes nothing. A file that cannot be read
as JSON stops the script with a clear message: a silent fall-back would hide the team's decision.

    {
      "voice":   {"reference": "leo_en_v1", "speed": 1.1, "pause": 0.30},
      "lengths": {"youtube_shorts": [20, 58], "tiktok": [20, 35], "reels": [61, 90], "tiktok_long": [60, 600]}
    }

voice.reference is the name of a voice/<name>.json written by voice/pick_voice.py (the Fish voice the takes are cloned
from). lengths are [shortest, longest] seconds that shorts.py --check accepts for each cut.
"""
import json
from pathlib import Path

FILE = Path(__file__).resolve().parent / "team_settings.json"


def section(name):
    """One top-level object of team_settings.json, {} when the file or the key is absent."""
    try:
        text = FILE.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except ValueError as err:
        raise SystemExit(f"team_settings.json is not valid JSON ({err}); fix or delete it")
    part = data.get(name, {}) if isinstance(data, dict) else None
    if not isinstance(part, dict):
        raise SystemExit(f'team_settings.json: "{name}" must be an object')
    return part


def number(part, key, default, lo, hi):
    """A number from a section, checked against the technical range lo..hi."""
    value = part.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise SystemExit(f"team_settings.json: {key} = {value!r} must be a number from {lo} to {hi}")
    return float(value)
