"""Set <vdir>/thumbnail.png on the already uploaded long video (<vdir>/youtube_result.json).

usage: python set_thumbnail.py <channel_id> <vdir> [<vdir> ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "video_pipeline"))
from youtube_upload import access_token, request  # noqa: E402


def main():
    token = access_token(sys.argv[1])
    for arg in sys.argv[2:]:
        vdir = Path(arg).resolve()
        vid = json.loads((vdir / "youtube_result.json").read_text(encoding="utf-8"))["video_id"]
        request(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                token, data=(vdir / "thumbnail.png").read_bytes(), method="POST",
                headers={"Content-Type": "image/png"})
        print("thumbnail set:", vdir.name, vid)


if __name__ == "__main__":
    main()
