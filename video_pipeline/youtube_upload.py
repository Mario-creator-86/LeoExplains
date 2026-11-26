"""Upload leo_procrastination.mp4 to YouTube with an OAuth refresh token (YouTube Data API v3).

Reads title/description/tags from youtube_metadata.md, exchanges the refresh token for an access token
(the token is never printed), uploads with the resumable protocol, then sets thumbnail.png.

Credentials come from the environment (see .env.example):
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
The other upload scripts (scripts/upload_long.py, youtube_upload_short.py, add_links.py, set_privacy.py,
set_thumbnail.py and the dashboard) import access_token() and request() from this module.

usage: python youtube_upload.py <channel_id> [public|unlisted|private]
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def access_token(channel_id: str) -> str:
    """A fresh Google access token for the channel's OAuth client (refresh-token grant)."""
    missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
               if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"no YouTube credentials for channel {channel_id}: set {', '.join(missing)}")
    form = urllib.parse.urlencode({
        "client_id": os.environ["YOUTUBE_CLIENT_ID"], "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", form, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def metadata() -> dict:
    text = (HERE / "youtube_metadata.md").read_text(encoding="utf-8")
    sec = dict(re.findall(r"^## (\w+)\n(.*?)(?=^## |\Z)", text, re.S | re.M))
    return {
        "title": sec["Title"].strip(),
        "description": sec["Description"].strip(),
        "tags": [t.strip() for t in sec["Tags"].split(",") if t.strip()],
    }


def request(url, token, *, data=None, headers=None, method="GET"):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read()[:800].decode(errors='replace')}")


def main():
    channel_id = sys.argv[1]
    privacy = sys.argv[2] if len(sys.argv) > 2 else "public"
    token = access_token(channel_id)
    me = json.loads(request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                            token).read())
    got = [c["id"] for c in me.get("items", [])]
    if channel_id not in got:
        raise SystemExit(f"token belongs to {got}, not {channel_id}")

    meta = metadata()
    video = HERE / "leo_procrastination.mp4"
    body = {
        "snippet": {"title": meta["title"], "description": meta["description"],
                    "tags": meta["tags"], "categoryId": "27",
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "embeddable": True, "license": "youtube", "containsSyntheticMedia": False},
    }
    size = video.stat().st_size
    init = request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        token, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    upload_url = init.headers["Location"]
    with open(video, "rb") as fh:
        done = request(upload_url, token, data=fh.read(), method="PUT",
                       headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    result = json.loads(done.read())
    vid = result["id"]
    print("uploaded:", vid, "| privacy:", result["status"]["privacyStatus"])

    thumb = HERE / "thumbnail.png"
    t = request(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                token, data=thumb.read_bytes(), method="POST",
                headers={"Content-Type": "image/png"})
    print("thumbnail:", "set" if t.status == 200 else t.status)
    print("url: https://youtu.be/" + vid)
    (HERE / "youtube_result.json").write_text(json.dumps({"video_id": vid, "privacy": privacy},
                                                         indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
