"""Add the channel links block (LINKS) to the description of already uploaded videos.

Inserts it before the last paragraph (the hashtags); skips videos that already contain it.
usage: python add_links.py <channel_id> <video_id> [<video_id> ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video_pipeline"))
from youtube_upload import access_token, request  # noqa: E402
from upload_long import LINKS  # noqa: E402

API = "https://www.googleapis.com/youtube/v3/videos"


def main():
    token = access_token(sys.argv[1])
    for vid in sys.argv[2:]:
        item = json.loads(request(f"{API}?part=snippet&id={vid}", token).read())["items"][0]
        sn = item["snippet"]
        desc = sn.get("description", "")
        if LINKS in desc:
            print("already linked:", vid)
            continue
        short = "\n".join(LINKS.split("\n")[:2])  # the earlier two-line block (YouTube + TikTok)
        stale = "https://www.facebook.com/profile.php?id=OLD_PAGE_ID"
        if stale in desc:  # the Page got its username: swap the old Page link
            sn["description"] = desc.replace(stale, "https://www.facebook.com/YOUR_PAGE")
        elif short in desc:
            sn["description"] = desc.replace(short, LINKS)
        else:
            head, sep, tail = desc.rpartition("\n\n")
            sn["description"] = f"{head}\n\n{LINKS}\n\n{tail}" if sep else f"{desc}\n\n{LINKS}"
        body = {"id": vid, "snippet": {k: sn[k] for k in ("title", "description", "tags",
                                                         "categoryId", "defaultLanguage",
                                                         "defaultAudioLanguage") if k in sn}}
        request(f"{API}?part=snippet", token, data=json.dumps(body).encode(), method="PUT",
                headers={"Content-Type": "application/json; charset=UTF-8"})
        print("linked:", vid, sn["title"][:60])


if __name__ == "__main__":
    main()
