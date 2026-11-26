"""Upload one Leo series video (full quality) to YouTube (OAuth credentials from the environment, see
video_pipeline/youtube_upload.py).

Reads <vdir>/meta.json (title, description, hashtags, tags from ChatGPT), uploads <vdir>/video.mp4
with the resumable protocol, sets <vdir>/thumbnail.png when present, and writes
<vdir>/youtube_result.json. The refresh token is never printed.

usage: python upload_long.py <vdir> <channel_id> [public|unlisted|private]
                                              [--publish-at 2026-11-03T14:00:00+02:00]
--publish-at uploads the video as private and lets YouTube make it public at that time.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video_pipeline"))
from youtube_upload import access_token, request  # noqa: E402

# the channel links block appended to every description: fill in your own handles
LINKS = ("▶ Subscribe: https://www.youtube.com/@YOUR_CHANNEL?sub_confirmation=1\n"
         "🎵 TikTok: https://www.tiktok.com/@YOUR_HANDLE\n"
         "📸 Instagram: https://www.instagram.com/YOUR_HANDLE/\n"
         "👍 Facebook: https://www.facebook.com/YOUR_PAGE")


def build(meta):
    tags = [t.strip() for t in meta["tags"].split(",") if t.strip()]
    while len(", ".join(tags)) > 480:
        tags.pop()
    hashtags = " ".join(re.findall(r"#\w+", meta["hashtags"]))[:300]
    # the study the episode mentions (topics.json "study"/"study_url"), so viewers can read it
    study = f"📚 Research mentioned: {meta['study']}\n{meta['study_url']}\n\n" if meta.get("study_url") else ""
    description = (
        f"{meta['description']}\n\n"
        "Follow Leo's story to understand what is really happening in your brain, and pick up a few "
        "simple, realistic habits you can try today.\n\n"
        f"{study}"
        "💬 Which part felt most familiar? Tell me in the comments.\n"
        "🔔 Subscribe for more psychology explained simply.\n\n"
        f"{LINKS}\n\n"
        "This video is for educational purposes and is not a substitute for professional mental "
        "health advice. Visuals and narration were created with AI tools.\n\n"
        f"{hashtags}"
    )
    return {
        "snippet": {"title": meta["title"][:100], "description": description, "tags": tags,
                    "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                   "embeddable": True, "license": "youtube", "containsSyntheticMedia": True},
    }


def publish_at(argv):
    """Pop --publish-at <ISO time> from argv; returns the time or None."""
    if "--publish-at" not in argv:
        return None
    i = argv.index("--publish-at")
    when = argv[i + 1]
    del argv[i:i + 2]
    return when


def main():
    when = publish_at(sys.argv)
    vdir, channel_id = Path(sys.argv[1]).resolve(), sys.argv[2]
    privacy = "private" if when else (sys.argv[3] if len(sys.argv) > 3 else "public")
    if (vdir / "youtube_result.json").exists():
        raise SystemExit(f"already uploaded: {(vdir / 'youtube_result.json').read_text()}")
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    # compilations (c1, c2…, 2026-11-03) have no topics.json entry; their meta.json carries everything
    n = int(vdir.name.lstrip("v")) if vdir.name.lstrip("v").isdigit() else None
    topic = next((t for t in json.loads((vdir.parent / "topics.json").read_text(encoding="utf-8"))
                  if t["n"] == n), {}) if n else {}
    meta.update({k: topic[k] for k in ("study", "study_url") if k in topic})
    body = build(meta)
    body["status"]["privacyStatus"] = privacy
    if when:
        body["status"]["publishAt"] = when
    token = access_token(channel_id)
    me = json.loads(request("https://www.googleapis.com/youtube/v3/channels?part=id&mine=true",
                            token).read())
    if channel_id not in [c["id"] for c in me.get("items", [])]:
        raise SystemExit("the stored connection is not for this channel")
    video = vdir / "video.mp4"
    import preflight      # mandatory since 2026-11-04 (a black-screen compilation was scheduled unchecked)
    if not preflight.check(video):
        raise SystemExit("preflight failed: not uploading (see problems and the contact sheet)")
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
    print("uploaded:", vid, privacy)
    thumb = vdir / "thumbnail.png"
    if thumb.exists():
        try:
            request(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                    token, data=thumb.read_bytes(), method="POST",
                    headers={"Content-Type": "image/png"})
            print("thumbnail set")
        except SystemExit as e:  # custom thumbnails need a verified channel
            print("thumbnail not set:", e)
    result = {"video_id": vid, "privacy": privacy}
    if when:
        result["publishAt"] = when
    (vdir / "youtube_result.json").write_text(json.dumps(result), encoding="utf-8")
    print("https://youtu.be/" + vid)


if __name__ == "__main__":
    main()
