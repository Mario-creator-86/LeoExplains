"""Change the privacy of uploaded videos (public / unlisted / private) on the Leo Explains channel.

usage: python set_privacy.py <channel_id> <unlisted|private|public> <video_id> [<video_id> ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video_pipeline"))
from youtube_upload import access_token, request  # noqa: E402

API = "https://www.googleapis.com/youtube/v3/videos"


def main():
    channel_id, privacy, ids = sys.argv[1], sys.argv[2], sys.argv[3:]
    if privacy not in ("public", "unlisted", "private"):
        raise SystemExit("privacy must be public, unlisted or private")
    token = access_token(channel_id)
    for vid in ids:
        item = json.loads(request(f"{API}?part=status,snippet&id={vid}", token).read())["items"][0]
        if item["snippet"]["channelId"] != channel_id:
            raise SystemExit(f"{vid} is not on this channel")
        status = item["status"]
        status["privacyStatus"] = privacy
        status.pop("publishAt", None)
        request(f"{API}?part=status", token, data=json.dumps({"id": vid, "status": status}).encode(),
                method="PUT", headers={"Content-Type": "application/json; charset=UTF-8"})
        print(f"{vid}: {privacy} ({item['snippet']['title'][:60]})")


if __name__ == "__main__":
    main()
