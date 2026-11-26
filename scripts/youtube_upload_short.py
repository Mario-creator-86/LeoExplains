"""Upload <vdir>/short.mp4 as a public YouTube Short (OAuth credentials from the environment, see
video_pipeline/youtube_upload.py; same access_token / request helpers, resumable upload).
Title = the video's question + " #Shorts"; description = 2 hook lines + "Full video: <long URL>" +
5 hashtags from meta.json + #Shorts; tags from meta.json. Writes <vdir>/short_youtube_result.json
and refuses to upload twice. No thumbnail (custom thumbnails need a verified channel).

usage: python youtube_upload_short.py <vdir> <channel_id> [public|unlisted|private]
                                                       [--publish-at <ISO time>] [--dry-run]
--publish-at uploads the Short as private and lets YouTube make it public at that time.
--recut "<hook>" (2026-11-03) uploads vN/short_recut.mp4 instead: a second, different Short of an
already-released episode (other scenes, other hook; shorts.py vN --scenes ... --out short_recut.mp4).
The hook is the title and the description's first line; the result goes to
vN/short_recut_youtube_result.json.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video_pipeline"))
from youtube_upload import access_token, request  # noqa: E402
from upload_long import LINKS, publish_at  # noqa: E402


def build(vdir, recut=None):
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    scenes = json.loads((vdir / "scenes.json").read_text(encoding="utf-8"))
    long_file = vdir / "youtube_result.json"
    # a "What if" part can go out before its long episode exists (2026-11-03 fast track)
    long_id = json.loads(long_file.read_text(encoding="utf-8"))["video_id"] if long_file.exists() else None
    hook = recut or re.split(r"\s*[(:|-]", meta["title"])[0].strip()[:90]
    # 2026-11-14: the meta.json title of a Short-only episode already ends in "#Shorts"; the tag was then added a second time
    # ("... #Shorts #Shorts" on v82, v88, v90, scheduled that night). One tag only, whatever the title carries.
    hook = re.sub(r"(\s*#shorts\b)+\s*$", "", hook, flags=re.I).strip()
    tags = [t.strip() for t in meta["tags"].split(",") if t.strip()] + ["shorts"]
    while len(", ".join(tags)) > 480:
        tags.pop(-2)
    hashtags = re.findall(r"#\w+", meta["hashtags"])
    hashtags = [h for h in hashtags if h.lower() != "#shorts"][:5] + ["#Shorts"]
    description = (
        f"{recut or scenes['1']['narration']}\n"
        + ("" if (vdir / "short_episode.json").exists() else
           "The short version of Leo's story: why it happens, and what actually helps.\n") + "\n"
        + (f"Full video: https://youtu.be/{long_id}\n\n" if long_id
           # a stand-alone Short episode has no long video: promise nothing (team vote 2026-11-06)
           else "" if (vdir / "short_episode.json").exists() else "Full story: soon on the channel.\n\n") +
        f"{LINKS}\n\n"
        f"{' '.join(hashtags)}"
    )
    return {
        "snippet": {"title": f"{hook} #Shorts", "description": description, "tags": tags,
                    "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                   "embeddable": True, "license": "youtube", "containsSyntheticMedia": True},
    }


def main():
    when = publish_at(sys.argv)
    recut = None
    if "--recut" in sys.argv:
        i = sys.argv.index("--recut")
        recut = sys.argv[i + 1].strip()
        del sys.argv[i:i + 2]
    video_name = None          # --video short_part1.mp4: another file of the episode ("What if" parts)
    if "--video" in sys.argv:
        i = sys.argv.index("--video")
        video_name = sys.argv[i + 1].strip()
        del sys.argv[i:i + 2]
    dry = "--dry-run" in sys.argv
    if dry:
        sys.argv.remove("--dry-run")
    vdir, channel_id = Path(sys.argv[1]).resolve(), sys.argv[2]
    privacy = "private" if when else (sys.argv[3] if len(sys.argv) > 3 else "public")
    if video_name:
        result = vdir / (Path(video_name).stem + "_youtube_result.json")
    else:
        result = vdir / ("short_recut_youtube_result.json" if recut else "short_youtube_result.json")
    if result.exists():
        raise SystemExit(f"already uploaded: {result.read_text()}")
    video = vdir / (video_name or ("short_recut.mp4" if recut else "short.mp4"))
    if not video.exists():
        raise SystemExit(f"missing {video}")
    import preflight      # mandatory since 2026-11-04 (a black-screen compilation was scheduled unchecked)
    if not preflight.check(video, short=True):
        raise SystemExit("preflight failed: not uploading (see problems and the contact sheet)")
    body = build(vdir, recut)
    body["status"]["privacyStatus"] = privacy
    if when:
        body["status"]["publishAt"] = when
    if dry:
        print(json.dumps(body, indent=1, ensure_ascii=False))
        return
    token = access_token(channel_id)
    me = json.loads(request("https://www.googleapis.com/youtube/v3/channels?part=id&mine=true",
                            token).read())
    if channel_id not in [c["id"] for c in me.get("items", [])]:
        raise SystemExit("the stored connection is not for this channel")
    size = video.stat().st_size
    init = request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        token, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    with open(video, "rb") as fh:
        done = request(init.headers["Location"], token, data=fh.read(), method="PUT",
                       headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    vid = json.loads(done.read())["id"]
    info = {"video_id": vid, "privacy": privacy, "url": f"https://youtube.com/shorts/{vid}",
            "title": body["snippet"]["title"]}
    if when:
        info["publishAt"] = when
    result.write_text(json.dumps(info), encoding="utf-8")
    print("uploaded:", vid, privacy)
    print("https://youtube.com/shorts/" + vid)


if __name__ == "__main__":
    main()
