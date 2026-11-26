"""Score how well a sound effect matches its text description with LAION CLAP (laion/clap-htsat-unfused,
Apache-2.0), because Claude cannot listen. Used by sfx_local.py to pick the best of several candidates and to
reject all of them when none matches well enough.
  sfx_score.py <prompt> <file.mp3> [<file2.mp3> ...]   prints one score per file (cosine similarity, -1..1)
Runs with: python
"""
import sys
import warnings

warnings.filterwarnings("ignore")
MODEL = "laion/clap-htsat-unfused"
_m = None


def _load():
    global _m
    if _m is None:
        from transformers import ClapModel, ClapProcessor
        _m = (ClapModel.from_pretrained(MODEL).eval(), ClapProcessor.from_pretrained(MODEL))
    return _m


def scores(prompt, files):
    import librosa
    import torch
    model, proc = _load()
    audios = [librosa.load(str(f), sr=48000, mono=True)[0] for f in files]
    with torch.no_grad():
        t = model.get_text_features(**proc(text=[prompt], return_tensors="pt", padding=True))
        a = model.get_audio_features(**proc(audio=audios, sampling_rate=48000, return_tensors="pt"))
    # newer transformers return an output object; the projected embedding is its pooler_output
    t = getattr(t, "pooler_output", t)
    a = getattr(a, "pooler_output", a)
    t = t / t.norm(dim=-1, keepdim=True)
    a = a / a.norm(dim=-1, keepdim=True)
    return (a @ t.T).squeeze(-1).tolist()


if __name__ == "__main__":
    prompt, files = sys.argv[1], sys.argv[2:]
    for f, s in zip(files, scores(prompt, files)):
        print(f"{s:.3f}  {f}")
