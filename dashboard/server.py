"""Leo Explains - local progress dashboard (YouTube + TikTok).

Stdlib only. Needs the YouTube OAuth variables of .env.example (video_pipeline/youtube_upload.py) and
YOUTUBE_CHANNEL_ID. Run:  python dashboard/server.py   then open http://127.0.0.1:8010

The Google access token lives only in this process' memory. It is never printed, logged, written to
disk or sent to the browser: the endpoints return statistics only.
"""
import base64
import hashlib
import html as htmllib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent                 # repository root
SERIES = REPO / "scripts"          # the production folder: episode folders vN/ live next to the scripts
DB_PATH = HERE / "stats.sqlite"
CONFIG_PATH = HERE / "config.json"
INDEX_PATH = HERE / "index.html"
MON_PATH = HERE / "monetization.json"
ALERTS_LOG = HERE / "alerts.log"
THUMBS_DIR = HERE / "thumbs"

HOST, PORT = "127.0.0.1", 8010
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")   # the channel's UC... id
AUTO_INTERVAL = 15 * 60          # background refresh
MANUAL_MIN_GAP = 60              # "Refresh now" at most once per minute
ANALYTICS_RETRY_AFTER_DENIED = 6 * 3600
YT_API = "https://www.googleapis.com/youtube/v3/"
YTA_API = "https://youtubeanalytics.googleapis.com/v2/reports"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


# ----------------------------------------------------------------------------- helpers

_SECRET_PATTERNS = [re.compile(r"ya29\.[\w\-.]+"), re.compile(r"1//[\w\-.]+"),
                    re.compile(r"(?i)bearer\s+[\w\-.]+")]


def redact(text) -> str:
    s = str(text)
    for p in _SECRET_PATTERNS:
        s = p.sub("[hidden]", s)
    return s[:400]


def now() -> int:
    return int(time.time())


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def iso_duration_seconds(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# ----------------------------------------------------------------------------- config / local files

DEFAULT_CONFIG = {
    "tiktok_handle": "",
    "instagram_handle": "",
    "facebook_page_url": "",
}


def load_config() -> dict:
    cfg = read_json(CONFIG_PATH)
    if not isinstance(cfg, dict):
        cfg = {}
    missing = {k: v for k, v in DEFAULT_CONFIG.items() if k not in cfg}
    if missing:  # add new fields, never overwrite what the user typed
        cfg.update(missing)
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        except OSError:
            pass
    return cfg


def clean_handle(h) -> str:
    h = (h or "").strip().lstrip("@")
    return h if re.fullmatch(r"[A-Za-z0-9._]{1,30}", h) else ""


IG_RESERVED = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct", "about"}


def _post_id(platform: str, url: str) -> str:
    pats = {
        "facebook": [r"/reel/(\d+)", r"/videos/(?:[^/]+/)?(\d+)", r"[?&]v=(\d+)", r"story_fbid=(\w+)",
                     r"/posts/([\w]+)", r"fbid=(\d+)", r"/share/[rv]/(\w+)"],
        "instagram": [r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)"],
    }[platform]
    for p in pats:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return "u" + hashlib.sha1(url.encode()).hexdigest()[:12]   # stable across restarts


def _social_posts(platform: str, path: Path) -> list:
    """Every posted item in vN/<platform>_result.json: the top-level url plus a "posts" list."""
    if not path.exists():
        return []
    rec = read_json(path) or {}
    if not isinstance(rec, dict):
        return []
    items = []
    if rec.get("url"):
        items.append(rec)
    for p in rec.get("posts") or []:
        if isinstance(p, str):
            p = {"url": p}
        if isinstance(p, dict) and p.get("url"):
            items.append({**{k: rec.get(k) for k in ("caption", "posted_at", "posted")}, **p})
    out, seen = [], set()
    for it in items:
        url = str(it.get("url") or "")
        if not url.startswith("https://") or url in seen:
            continue
        seen.add(url)
        if it.get("posted") is False:
            continue
        out.append({
            "url": url, "id": _post_id(platform, url),
            "kind": it.get("kind") or it.get("type"),
            "caption": it.get("caption") or "",
            "posted_at": it.get("posted_at"),
            "file_ts": int(path.stat().st_mtime),
            "page": rec.get("page") or rec.get("profile") or rec.get("account"),
        })
    return out


def local_series() -> list:
    """v1..vN folders: long video id, Short id, TikTok / Facebook / Instagram posts."""
    out = []
    dirs = [p for p in SERIES.iterdir() if p.is_dir() and re.fullmatch(r"v\d+", p.name)]
    for d in sorted(dirs, key=lambda p: int(p.name[1:])):
        meta = read_json(d / "meta.json") or {}
        # youtube_long.json: fallback copy when youtube_result.json is locked (v1, antivirus)
        yt = read_json(d / "youtube_result.json") or read_json(d / "youtube_long.json") or {}
        sh = read_json(d / "short_youtube_result.json") or {}
        tt_path = d / "tiktok_result.json"
        tt = read_json(tt_path) or {}
        tt_url = tt.get("url") or ""
        mt = re.search(r"/video/(\d+)", tt_url)
        mh = re.search(r"tiktok\.com/@([A-Za-z0-9._]+)", tt_url)
        out.append({
            "series": d.name,
            "title": meta.get("title") or d.name,
            "long_id": yt.get("video_id") or yt.get("id"),
            "short_id": sh.get("video_id") or sh.get("id"),
            "tiktok": {
                "posted": bool(tt.get("posted")),
                "url": tt_url or None,
                "id": mt.group(1) if mt else None,
                "handle": mh.group(1) if mh else None,
                "caption": tt.get("caption") or "",
                "file_ts": int(tt_path.stat().st_mtime) if tt_path.exists() else None,
            } if tt_path.exists() else None,
            "facebook": _social_posts("facebook", d / "facebook_result.json"),
            "instagram": _social_posts("instagram", d / "instagram_result.json"),
        })
    return out


def tiktok_handle(series=None) -> str:
    h = clean_handle(load_config().get("tiktok_handle"))
    if h:
        return h
    for s in series or local_series():
        if s["tiktok"] and s["tiktok"]["handle"]:
            return s["tiktok"]["handle"]
    return ""


def instagram_handle(series=None) -> str:
    h = clean_handle(load_config().get("instagram_handle"))
    if h:
        return h
    for s in series or local_series():
        for p in s["instagram"]:
            for src in (p["url"], p.get("page") or ""):
                m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", src)
                if m and m.group(1).lower() not in IG_RESERVED:
                    return m.group(1)
    return ""


def facebook_page(series=None) -> str:
    u = str(load_config().get("facebook_page_url") or "").strip()
    if u.startswith("https://www.facebook.com/") or u.startswith("https://facebook.com/"):
        return u
    for s in series or local_series():
        for p in s["facebook"]:
            if str(p.get("page") or "").startswith("https://"):
                return p["page"]
    return ""


# ----------------------------------------------------------------------------- database

def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        create table if not exists channel_snap(
            ts integer not null, platform text not null,
            followers integer, views integer, likes integer, videos integer, comments integer);
        create index if not exists channel_snap_i on channel_snap(platform, ts);
        create table if not exists video_snap(
            ts integer not null, platform text not null, video_id text not null,
            views integer, likes integer, comments integer, shares integer);
        create index if not exists video_snap_i on video_snap(platform, video_id, ts);
        create table if not exists video_meta(
            platform text not null, video_id text not null, title text, kind text,
            published text, duration integer, privacy text, thumb text, url text,
            primary key(platform, video_id));
        create table if not exists analytics_day(
            day text primary key, views integer, minutes integer, avg_dur integer,
            subs_gained integer, subs_lost integer);
        create table if not exists kv(k text primary key, v text);
        create table if not exists mon_state(
            program text primary key, met integer not null, ts integer not null);
        create table if not exists alerts(
            id integer primary key autoincrement, ts integer not null, program text,
            title text, message text, dismissed integer not null default 0);
        """)


def kv_get(key, default=None):
    with db() as con:
        r = con.execute("select v from kv where k=?", (key,)).fetchone()
    return json.loads(r["v"]) if r else default


def kv_set(key, value):
    with db() as con:
        con.execute("insert or replace into kv(k, v) values(?, ?)", (key, json.dumps(value)))


# ----------------------------------------------------------------------------- YouTube

_tok = {"value": None, "exp": 0.0}
_tok_lock = threading.Lock()
_yt_mod = None


def _yt_module():
    global _yt_mod
    if _yt_mod is None:
        sys.path.insert(0, str(REPO / "video_pipeline"))
        import youtube_upload  # noqa: E402  (OAuth refresh-token grant from the environment)
        _yt_mod = youtube_upload
    return _yt_mod


def get_token() -> str:
    with _tok_lock:
        if _tok["value"] and time.time() < _tok["exp"]:
            return _tok["value"]
        try:
            value = _yt_module().access_token(CHANNEL_ID)
        except BaseException as e:  # SystemExit from the helper, URLError, vault errors
            if isinstance(e, KeyboardInterrupt):
                raise
            raise ApiError(0, "Google token unavailable: " + redact(e or type(e).__name__))
        _tok["value"], _tok["exp"] = value, time.time() + 45 * 60
        return value


def authed_json(url: str) -> dict:
    for attempt in (0, 1):
        tok = get_token()
        try:
            with _yt_module().request(url, tok) as r:
                return json.loads(r.read())
        except SystemExit as e:  # youtube_upload.request raises SystemExit("HTTP <code>: <body>")
            msg = str(e)
            m = re.match(r"HTTP (\d+)", msg)
            code = int(m.group(1)) if m else 0
            if code == 401 and attempt == 0:
                with _tok_lock:
                    _tok["value"] = None
                continue
            raise ApiError(code, redact(msg))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(0, redact(e))
    raise ApiError(401, "authorization rejected")


def yt(path, **params) -> dict:
    return authed_json(YT_API + path + "?" + urllib.parse.urlencode(params))


def fetch_youtube(series) -> dict:
    ch = yt("channels", part="snippet,statistics,brandingSettings,contentDetails", id=CHANNEL_ID)
    items = ch.get("items") or []
    if not items:
        raise ApiError(404, "channel not found")
    c = items[0]
    sn, st = c.get("snippet", {}), c.get("statistics", {})
    uploads = c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads") \
        or "UU" + CHANNEL_ID[2:]
    thumbs = sn.get("thumbnails", {})
    info = {
        "title": sn.get("title"),
        "handle": sn.get("customUrl"),
        "avatar": (thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
        "url": f"https://www.youtube.com/channel/{CHANNEL_ID}",
        "created": sn.get("publishedAt"),
        "country": sn.get("country"),
        "hidden_subs": bool(st.get("hiddenSubscriberCount")),
    }
    if info["handle"]:
        info["url"] = "https://www.youtube.com/" + info["handle"]

    ids, token = [], None
    for _ in range(20):  # 50 per page; safety cap 1000 videos
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if token:
            params["pageToken"] = token
        try:
            page = yt("playlistItems", **params)
        except ApiError as e:
            if e.code == 404:  # no uploads playlist yet
                break
            raise
        ids += [i["contentDetails"]["videoId"] for i in page.get("items", [])]
        token = page.get("nextPageToken")
        if not token:
            break

    short_ids = {s["short_id"] for s in series if s["short_id"]}
    videos = []
    for i in range(0, len(ids), 50):
        res = yt("videos", part="snippet,statistics,contentDetails,status", id=",".join(ids[i:i + 50]))
        for v in res.get("items", []):
            vsn, vst = v.get("snippet", {}), v.get("statistics", {})
            dur = iso_duration_seconds(v.get("contentDetails", {}).get("duration"))
            title = vsn.get("title") or ""
            is_short = (0 < dur <= 60) or "#shorts" in title.lower() or v["id"] in short_ids
            th = vsn.get("thumbnails", {})
            videos.append({
                "id": v["id"], "title": title, "kind": "short" if is_short else "long",
                "published": vsn.get("publishedAt"), "duration": dur,
                "privacy": v.get("status", {}).get("privacyStatus"),
                "thumb": (th.get("medium") or th.get("default") or {}).get("url"),
                "url": (f"https://www.youtube.com/shorts/{v['id']}" if is_short
                        else f"https://youtu.be/{v['id']}"),
                "views": to_int(vst.get("viewCount")) or 0,
                "likes": to_int(vst.get("likeCount")),
                "comments": to_int(vst.get("commentCount")),
            })
    return {
        "info": info,
        "subscribers": to_int(st.get("subscriberCount")),
        "views": to_int(st.get("viewCount")) or 0,
        "video_count": to_int(st.get("videoCount")) or len(videos),
        "videos": videos,
    }


def fetch_analytics() -> list:
    end = date.today()
    start = end - timedelta(days=28)
    url = YTA_API + "?" + urllib.parse.urlencode({
        "ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
        "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
        "dimensions": "day", "sort": "day",
    })
    res = authed_json(url)
    cols = [h["name"] for h in res.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in res.get("rows", []) or []]


# ----------------------------------------------------------------------------- TikTok (public page, no login)

def tt_scope(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=20) as r:   # default opener: no cookie jar
        html = r.read(4_000_000).decode("utf-8", "replace")
    m = re.search(r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    return (json.loads(m.group(1)) or {}).get("__DEFAULT_SCOPE__") or {}


def _stats(obj: dict) -> dict:
    s = dict(obj.get("stats") or {})
    for k, v in (obj.get("statsV2") or {}).items():   # statsV2 = exact values as strings
        if to_int(v) is not None:
            s[k] = to_int(v)
    return s


def fetch_tiktok(handle: str, series) -> dict:
    out = {"user": None, "videos": {}, "errors": []}
    try:
        scope = tt_scope(f"https://www.tiktok.com/@{handle}")
        ui = ((scope or {}).get("webapp.user-detail") or {}).get("userInfo") or {}
        if ui.get("user"):
            s = _stats(ui)
            out["user"] = {
                "followers": to_int(s.get("followerCount")),
                "likes": to_int(s.get("heartCount") if s.get("heartCount") is not None else s.get("heart")),
                "videos": to_int(s.get("videoCount")),
                "nickname": ui["user"].get("nickname"),
                "avatar": ui["user"].get("avatarMedium") or ui["user"].get("avatarThumb"),
            }
        else:
            out["errors"].append("profile returned no public data")
    except Exception as e:
        out["errors"].append("profile: " + redact(e))
    for s in series:
        t = s["tiktok"]
        if not (t and t["id"]):
            continue
        url = t["url"] if t["url"].startswith("https://www.tiktok.com/") else \
            f"https://www.tiktok.com/@{handle}/video/{t['id']}"
        try:
            scope = tt_scope(url)
            item = (((scope or {}).get("webapp.video-detail") or {}).get("itemInfo") or {}).get("itemStruct")
            if not item:
                out["errors"].append(f"{s['series']}: no public data")
                continue
            st = _stats(item)
            ct = to_int(item.get("createTime"))
            out["videos"][t["id"]] = {
                "views": to_int(st.get("playCount")), "likes": to_int(st.get("diggCount")),
                "comments": to_int(st.get("commentCount")), "shares": to_int(st.get("shareCount")),
                "published": datetime.fromtimestamp(ct, timezone.utc).isoformat() if ct else None,
                "duration": to_int((item.get("video") or {}).get("duration")),
                "thumb": (item.get("video") or {}).get("cover"),
            }
        except Exception as e:
            out["errors"].append(f"{s['series']}: " + redact(e))
        time.sleep(1)
    return out


# ----------------------------------------------------------------------------- Facebook / Instagram (public pages)
# Plain GET of the public page with an honest, self-identifying User-Agent. No cookies, no login, and no
# impersonation of a browser or of Meta's own crawler. Whatever public numbers the page carries are used;
# anything missing stays empty and the dashboard says "stats unavailable automatically".

META_UA = "LeoExplainsDashboard/1.0 (local personal stats page; no login)"


def public_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": META_UA, "Accept-Language": "en-US,en;q=0.9",
                                               "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:   # default opener: no cookie jar
        return r.read(4_000_000).decode("utf-8", "replace")


def meta_content(html: str, prop: str):
    for pat in (rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"',
                rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"'):
        m = re.search(pat, html)
        if m:
            return htmllib.unescape(m.group(1))
    return None


def parse_count(s):
    """'1,234' / '1.2K' / '3M' / '12' -> int."""
    if s is None:
        return None
    m = re.fullmatch(r"\s*([\d][\d,.\s]*)\s*([KkMmBb]?)\s*", str(s))
    if not m:
        return None
    num, suf = m.group(1).replace(" ", ""), m.group(2).upper()
    if suf:
        try:
            return int(round(float(num.replace(",", "")) * {"K": 1e3, "M": 1e6, "B": 1e9}[suf]))
        except ValueError:
            return None
    return to_int(re.sub(r"[,.]", "", num))


def _near(html: str, anchor: str, patterns, window=40000):
    """First number for any pattern, preferring the match closest to the anchor (the post id)."""
    anchors = [m.start() for m in re.finditer(re.escape(anchor), html)] if anchor else []
    best = None
    for pat in patterns:
        for m in re.finditer(pat, html):
            if anchors:
                d = min(abs(m.start() - a) for a in anchors)
                if d > window:
                    continue
            else:
                d = 0
            v = to_int(m.group(1))
            if v is not None and (best is None or d < best[0]):
                best = (d, v)
    return best[1] if best else None


# optional: a JSON file {"ig": {"id": ...}, "pageToken": ...} with a Meta Graph API page token (never committed)
META_CONNECTION = Path(os.environ.get("META_CONNECTION_FILE", str(HERE / "meta-connection.json")))


def instagram_official() -> dict | None:
    """Followers and post count from the official Instagram Graph API, through an existing Meta connection file.
    The logged-out public profile page can lag behind the API (seen: 6 vs 9 followers)."""
    try:
        c = json.loads(META_CONNECTION.read_text(encoding="utf-8"))
        ig, token = c.get("ig") or {}, c.get("pageToken")
        if not ig.get("id") or not token:
            return None
        q = urllib.parse.urlencode({"fields": "username,followers_count,media_count,profile_picture_url", "access_token": token})
        with urllib.request.urlopen(f"https://graph.facebook.com/v25.0/{ig['id']}?{q}", timeout=20) as r:
            j = json.loads(r.read().decode("utf-8"))
        if not isinstance(j.get("followers_count"), int):
            return None
        return {"followers": j["followers_count"], "posts": j.get("media_count"), "nickname": j.get("username"), "avatar": j.get("profile_picture_url")}
    except Exception:
        return None


def fetch_instagram(handle: str, series) -> dict:
    out = {"user": None, "posts": {}, "errors": []}
    official = instagram_official()
    if official:
        out["user"] = official
    elif handle:
        try:
            html = public_html(f"https://www.instagram.com/{handle}/")
            desc = meta_content(html, "og:description") or ""
            m = re.search(r"([\d.,]+[KMB]?)\s+Followers?,\s*([\d.,]+[KMB]?)\s+Following,\s*([\d.,]+[KMB]?)\s+Posts?",
                          desc, re.I)
            if m:
                title = meta_content(html, "og:title") or ""
                out["user"] = {"followers": parse_count(m.group(1)), "posts": parse_count(m.group(3)),
                               "nickname": re.sub(r"\s*\(@.*$", "", title).strip() or None,
                               "avatar": meta_content(html, "og:image")}
            else:
                out["errors"].append("profile page carried no public counters")
        except Exception as e:
            out["errors"].append("profile: " + redact(e))
    for s in series:
        for p in s["instagram"]:
            try:
                html = public_html(p["url"])
                out.setdefault("images", {})[p["id"]] = meta_content(html, "og:image")
                desc = meta_content(html, "og:description") or meta_content(html, "description") or ""
                likes = re.search(r"([\d.,]+[KMB]?)\s+likes?", desc, re.I)
                comments = re.search(r"([\d.,]+[KMB]?)\s+comments?", desc, re.I)
                views = _near(html, p["id"], [r'"(?:video_view_count|play_count|view_count)"\s*:\s*(\d+)'])
                if likes or comments or views is not None:
                    out["posts"][p["id"]] = {"views": views, "likes": parse_count(likes.group(1)) if likes else None,
                                             "comments": parse_count(comments.group(1)) if comments else None}
                else:
                    out["errors"].append(f"{s['series']}: no public counters")
            except Exception as e:
                out["errors"].append(f"{s['series']}: " + redact(e))
            time.sleep(1)
    return out


def fetch_facebook(page_url: str, series) -> dict:
    out = {"user": None, "posts": {}, "errors": []}
    if page_url:
        try:
            html = public_html(page_url)
            texts = " ".join(filter(None, [meta_content(html, "og:description"), meta_content(html, "description")]))
            followers = _near(html, "", [r'"(?:follower_count|followers_count|subscriber_count)"\s*:\s*(\d+)'])
            likes = _near(html, "", [r'"(?:page_likers|fan_count)"\s*:\s*\{?"?(?:count"\s*:\s*)?(\d+)'])
            if followers is None:
                m = re.search(r"([\d.,]+[KMB]?)\s+followers", texts, re.I) or \
                    re.search(r'"text"\s*:\s*"([\d.,]+[KMB]?)\s+followers"', html, re.I)
                followers = parse_count(m.group(1)) if m else None
            if likes is None:
                m = re.search(r"([\d.,]+[KMB]?)\s+likes", texts, re.I)
                likes = parse_count(m.group(1)) if m else None
            out["user"] = {"followers": followers, "likes": likes,
                           "nickname": meta_content(html, "og:title"), "avatar": meta_content(html, "og:image")}
            if followers is None and likes is None:
                out["errors"].append("page carried no public follower/like counters")
        except Exception as e:
            out["errors"].append("page: " + redact(e))
    for s in series:
        for p in s["facebook"]:
            try:
                html = public_html(p["url"])
                pid = p["id"]
                out.setdefault("images", {})[pid] = meta_content(html, "og:image")
                views = _near(html, pid, [r'"(?:play_count|video_view_count)"\s*:\s*(\d+)'])
                likes = _near(html, pid, [r'"likers"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
                                          r'"reaction_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
                                          r'"reaction_count"\s*:\s*"?(\d+)'])
                comments = _near(html, pid, [r'"total_comment_count"\s*:\s*(\d+)',
                                             r'"comment_count"\s*:\s*\{\s*"total_count"\s*:\s*(\d+)'])
                shares = _near(html, pid, [r'"share_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)'])
                if any(v is not None for v in (views, likes, comments)):
                    out["posts"][pid] = {"views": views, "likes": likes, "comments": comments, "shares": shares}
                else:
                    out["errors"].append(f"{s['series']}: no public counters")
            except Exception as e:
                out["errors"].append(f"{s['series']}: " + redact(e))
            time.sleep(1)
    return out


def store_social(ts, platform, res, posted_count):
    """Snapshot rows for Facebook / Instagram. A channel row only when the page gave a public number."""
    posts = res["posts"]
    user = res["user"] or {}
    views = sum(v["views"] for v in posts.values() if v.get("views") is not None) \
        if any(v.get("views") is not None for v in posts.values()) else None
    likes_posts = sum(v["likes"] for v in posts.values() if v.get("likes") is not None) \
        if any(v.get("likes") is not None for v in posts.values()) else None
    comments = sum(v["comments"] for v in posts.values() if v.get("comments") is not None) \
        if any(v.get("comments") is not None for v in posts.values()) else None
    followers = user.get("followers")
    likes = user.get("likes") if user.get("likes") is not None else likes_posts
    videos = user.get("posts") if user.get("posts") is not None else posted_count
    with db() as con:
        if any(v is not None for v in (followers, views, likes)):
            con.execute("insert into channel_snap values(?,?,?,?,?,?,?)",
                        (ts, platform, followers, views, likes, videos, comments))
        for pid, v in posts.items():
            con.execute("insert into video_snap values(?,?,?,?,?,?,?)",
                        (ts, platform, pid, v.get("views"), v.get("likes"), v.get("comments"), v.get("shares")))
    if res["user"]:
        kv_set(f"{platform}_info", {"nickname": user.get("nickname"), "avatar": user.get("avatar")})


# ----------------------------------------------------------------------------- thumbnails (cached locally)
# TikTok / Facebook / Instagram image URLs expire, so every thumbnail is downloaded once into dashboard/thumbs/
# and served from there. Fallback: a frame of the episode's local short.mp4 (or its thumbnail.png).

def _safe_name(platform, vid) -> str:
    return f"{platform}_{re.sub(r'[^A-Za-z0-9_-]', '', str(vid))[:60]}.jpg"


def download_image(url: str, dest: Path) -> bool:
    if not (isinstance(url, str) and url.startswith("https://")):
        return False
    req = urllib.request.Request(url, headers={"User-Agent": META_UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        if not (r.headers.get("Content-Type") or "").startswith("image/"):
            return False
        data = r.read(3_000_001)
    if not data or len(data) > 3_000_000:
        return False
    THUMBS_DIR.mkdir(exist_ok=True)
    raw = dest.with_suffix(".src")
    raw.write_bytes(data)
    try:   # normalise to a small 16:9 jpg like the YouTube thumbnails (center crop)
        ok = _ffmpeg_img(["-i", str(raw)], dest, crop=True)
    finally:
        raw.unlink(missing_ok=True)
    return ok


def _ffmpeg_bin(name="ffmpeg"):
    # PATH first; then the copies made after the antivirus removed the WinGet install (2026-10-31),
    # since a server started before that fix keeps the old PATH
    found = shutil.which(name)
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for cand in [Path.home() / "bin" / f"{name}.exe", *sorted(local.glob(f"ffmpeg-restored/*/bin/{name}.exe"))]:
        if cand.is_file():
            return str(cand)
    return None


def _ffmpeg_img(inputs, dest: Path, crop=True) -> bool:
    ff = _ffmpeg_bin()
    if not ff:
        return False
    vf = ("crop='min(iw,ih*16/9)':'min(ih,iw*9/16)',scale=320:180" if crop else "scale=320:-2")
    THUMBS_DIR.mkdir(exist_ok=True)
    tmp = dest.with_name(dest.stem + ".tmp.jpg")
    r = subprocess.run([ff, "-v", "error", "-y", *inputs, "-frames:v", "1", "-vf", vf, "-q:v", "4", str(tmp)],
                       capture_output=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        tmp.replace(dest)
        return True
    tmp.unlink(missing_ok=True)
    return False


def local_thumb(series_name: str):
    """thumbs/local_vN.jpg from vN/short.mp4 (frame at 1 s) or vN/thumbnail.png."""
    dest = THUMBS_DIR / f"local_{series_name}.jpg"
    if dest.exists():
        return dest.name
    d = SERIES / series_name
    try:
        if (d / "short.mp4").exists() and _ffmpeg_img(["-ss", "1", "-i", str(d / "short.mp4")], dest):
            return dest.name
        if (d / "thumbnail.png").exists() and _ffmpeg_img(["-i", str(d / "thumbnail.png")], dest):
            return dest.name
    except Exception:
        traceback.print_exc()
    return None


def short_duration(series_name: str):
    cache = kv_get("short_durations", {}) or {}
    if series_name in cache:
        return cache[series_name]
    f, probe = SERIES / series_name / "short.mp4", _ffmpeg_bin("ffprobe")
    val = None
    if f.exists() and probe:
        try:
            r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                               capture_output=True, text=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            val = int(round(float(r.stdout.strip())))
        except Exception:
            val = None
    if val:
        cache[series_name] = val
        kv_set("short_durations", cache)
    return val


def _posted_image(series_name: str, platform: str, url: str):
    """Local copy of what was posted: Reel cover, carousel slide 1, Facebook photo (scripts/social)."""
    ig, fb = SERIES / "social" / "ig" / series_name, SERIES / "social" / "fb"
    if "/reel" in url:
        cands = [ig / "reel_cover.jpg"]
    elif platform == "instagram":
        cands = [ig / "slide_1.jpg"]
    else:
        cands = [*sorted(fb.glob(f"{series_name}_*.*")), *sorted((fb / series_name).glob("*.*")), ig / "slide_1.jpg"]
        cands = [c for c in cands if c.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    return next((c for c in cands if c.is_file()), None)


def ensure_thumbs(series, images: dict):
    """images: {(platform, id): remote image url or None}. Downloads what is missing (once)."""
    for s in series:
        local_thumb(s["series"])
        short_duration(s["series"])
        posts = [("tiktok", s["tiktok"]["id"], s["tiktok"]["url"])] if (s["tiktok"] and s["tiktok"]["id"]) else []
        posts += [(pf, p["id"], p["url"]) for pf in ("facebook", "instagram") for p in s[pf]]
        for platform, vid, url in posts:
            dest = THUMBS_DIR / _safe_name(platform, vid)
            if dest.exists():
                continue
            # the image we posted ourselves, when the platform hides it (very new or photo posts)
            mine = _posted_image(s["series"], platform, url)
            try:
                if mine and _ffmpeg_img(["-i", str(mine)], dest):
                    continue
            except Exception:
                traceback.print_exc()
            candidates = []
            if platform == "tiktok":
                try:   # TikTok's public oEmbed (no login); thumbnail_url when TikTok provides it
                    q = "https://www.tiktok.com/oembed?" + urllib.parse.urlencode({"url": url})
                    with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": META_UA}), timeout=15) as r:
                        candidates.append(json.loads(r.read(200_000)).get("thumbnail_url"))
                except Exception:
                    pass
            candidates.append(images.get((platform, vid)))
            for c in candidates:
                try:
                    if c and download_image(c, dest):
                        break
                except Exception:
                    continue


def thumb_url(platform, vid, series_name):
    for name in (_safe_name(platform, vid), f"local_{series_name}.jpg" if series_name else None):
        if name and (THUMBS_DIR / name).exists():
            return "/thumbs/" + name
    return None


# ----------------------------------------------------------------------------- posting log (comics, pins, other posts)
# social/post_log.json lists every post the publishing tasks made, including the ones that are not in a
# vN/*_result.json (comics, Pinterest pins, the YouTube community post, the TikTok photo post). Those are
# added to the table here; anything already in the table (same url or post id) is skipped. Read-only.

SOCIAL = SERIES / "social"
POST_LOG = SOCIAL / "post_log.json"
COMIC_QUEUE = SOCIAL / "comics" / "queue.json"
COMICS_READY = SOCIAL / "comics" / "ready"
PINS_JSON = SOCIAL / "pinterest" / "pins.json"
PIN_STATS = SOCIAL / "pinterest" / "stats.json"     # written by the monitor task (Pinterest analytics)
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def _url_key(url) -> str:
    u = re.sub(r"^https?://(?:www\.|m\.)?", "", str(url or "").strip(), flags=re.I)
    host, _, rest = u.partition("/")
    return (host.lower() + "/" + rest).rstrip("/")


def _log_post_id(platform: str, url: str) -> str:
    if platform in ("facebook", "instagram"):
        return _post_id(platform, url)
    pats = {"tiktok": [r"/(?:video|photo)/(\d+)"],
            "pinterest": [r"/pin/(\d+)"],
            "youtube": [r"/post/([\w-]+)", r"(?:youtu\.be/|[?&]v=|/shorts/)([\w-]{11})"]}.get(platform, [])
    for p in pats:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return "u" + hashlib.sha1(url.encode()).hexdigest()[:12]


def _local_image(rel):
    """A logged image path (relative to the scripts folder) when it is a real image file inside it."""
    if not isinstance(rel, str) or not rel.strip() or "*" in rel or ".." in rel:
        return None
    try:
        f = (SERIES / rel.strip()).resolve()
        if f.is_file() and f.suffix.lower() in IMG_EXT and SERIES.resolve() in f.parents:
            return f
    except (OSError, ValueError):
        pass
    return None


def pinterest_stats():
    """social/pinterest/stats.json -> {"updated", "pins": {pin_id: {...}}}; None when missing or unreadable."""
    try:
        d = read_json(PIN_STATS) if PIN_STATS.exists() else None
        if not isinstance(d, dict):
            return None
        pins = {}
        for url, v in (d.get("pins") if isinstance(d.get("pins"), dict) else {}).items():
            if isinstance(v, dict):
                pins[_log_post_id("pinterest", str(url))] = {
                    k: to_int(v.get(k)) for k in ("impressions", "saves", "pin_clicks", "outbound_clicks")}
        upd = d.get("updated")
        return {"updated": upd if isinstance(upd, str) else None, "pins": pins}
    except Exception:
        return None


def pinterest_profile() -> str:
    try:
        for u in ((read_json(PINS_JSON) or {}).get("board_urls") or {}).values():
            m = re.match(r"(https://www\.pinterest\.com/[A-Za-z0-9_.-]+/)", str(u))
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def post_log_items(series, youtube_ids=()) -> list:
    """post_log.json entries that are not already in the table, normalised for the table."""
    log = read_json(POST_LOG)
    entries = log.get("posts") if isinstance(log, dict) else (log if isinstance(log, list) else [])
    known = set()
    for s in series:
        t = s["tiktok"]
        if t and t.get("url"):
            known.add(_url_key(t["url"]))
        if t and t.get("id"):
            known.add(("tiktok", t["id"]))
        for pf in ("facebook", "instagram"):
            for p in s[pf]:
                known.add(_url_key(p["url"]))
                known.add((pf, p["id"]))
        for vid in (s["long_id"], s["short_id"]):
            if vid:
                known.add(("youtube", vid))
    known.update(("youtube", v) for v in youtube_ids or [])

    queue = read_json(COMIC_QUEUE) or {}
    comics = {Path(str(c.get("file") or "")).stem: c for c in (queue.get("comics") or [])
              if isinstance(c, dict) and c.get("file")} if isinstance(queue, dict) else {}
    pins_doc = read_json(PINS_JSON) or {}
    pins = {_url_key(p["url"]): p for p in (pins_doc.get("pins") or [])
            if isinstance(p, dict) and p.get("url")} if isinstance(pins_doc, dict) else {}
    titles = {s["series"]: s["title"] for s in series}

    out = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        url, platform = str(e.get("url") or "").strip(), str(e.get("platform") or "").strip().lower()
        if not url.startswith("https://") or not re.fullmatch(r"[a-z]{2,20}", platform):
            continue
        pid = _log_post_id(platform, url)
        if _url_key(url) in known or (platform, pid) in known:
            continue
        known.update((_url_key(url), (platform, pid)))
        vn = str(e.get("vN") or "")
        typ = str(e.get("type") or "").strip().lower()
        is_comic = vn.startswith("comic") or str(e.get("format") or "").lower().startswith("comic")
        episode = e.get("episode") or (vn if re.fullmatch(r"v\d+", vn) else None)
        episode = str(episode) if episode else None
        comic = comics.get(vn) if is_comic else None
        topic = (comic or {}).get("topic")
        pin = pins.get(_url_key(url)) if platform == "pinterest" else None
        if platform == "pinterest":
            title = e.get("title") or (pin or {}).get("title") or \
                "Pin: " + str(topic or titles.get(episode) or vn or "Pinterest pin")
        elif is_comic:
            title = "Comic: " + str(topic or vn)
        else:
            title = e.get("title") or titles.get(episode) or vn or platform
        label = {"community_post": "post", "image_pin": "pin", "video_pin": "video pin"}.get(typ, typ) or "post"
        # local image: the one logged for the post / pin, else the comic png, else what was posted for the episode
        image = next(filter(None, (_local_image(x) for x in (e.get("image"), e.get("file"), e.get("source"),
                                                              (pin or {}).get("file")))), None)
        if not image and is_comic:
            for cand in ([_local_image("social/comics/" + comic["file"])] if comic else []) + \
                        [COMICS_READY / f"{vn}.png"]:
                if cand and cand.is_file():
                    image = cand
                    break
        if not image and episode and platform in ("facebook", "instagram"):
            image = _posted_image(episode, platform, url)
        out.append({
            "platform": platform, "id": pid, "url": url, "title": str(title),
            "kind": "community" if platform == "youtube" else platform,
            "format": "comic" if is_comic else label, "subtype": label if is_comic else None,
            "published": e.get("date") or e.get("posted_at"), "series": episode, "vn": vn,
            "board": e.get("board") or (pin or {}).get("board"), "image": str(image) if image else None,
        })
    return out


def log_fetch_series(items) -> list:
    """Series-shaped records so fetch_facebook / fetch_instagram / fetch_tiktok can read the logged posts too."""
    out = []
    for it in items:
        s = {"series": it["vn"] or it["id"], "tiktok": None, "facebook": [], "instagram": []}
        if it["platform"] in ("facebook", "instagram"):
            s[it["platform"]].append({"url": it["url"], "id": it["id"]})
        elif it["platform"] == "tiktok" and it["url"].startswith("https://www.tiktok.com/"):
            s["tiktok"] = {"posted": True, "url": it["url"], "id": it["id"], "handle": None}
        else:
            continue
        out.append(s)
    return out


def ensure_log_thumbs(items, images: dict):
    """thumbs/log_<platform>_<id>.jpg from the local image (comic / pin); else the platform image, once."""
    for it in items:
        dest = THUMBS_DIR / _safe_name("log_" + it["platform"], it["id"])
        if dest.exists():
            continue
        try:
            if it["image"] and _ffmpeg_img(["-i", it["image"]], dest):
                continue
        except Exception:
            traceback.print_exc()
        try:
            remote = images.get((it["platform"], it["id"]))
            if remote:
                download_image(remote, dest)
        except Exception:
            pass


def store_pinterest(ts, items):
    """Snapshot rows from social/pinterest/stats.json (Views = impressions, Likes = saves)."""
    pins = [it for it in items if it["platform"] == "pinterest"]
    st = pinterest_stats()
    if st is None:
        set_status("pinterest", False, f"Pinterest stats not available yet · {len(pins)} pins posted · "
                                       "Pinterest stats update every few hours")
        return
    got = {it["id"]: st["pins"][it["id"]] for it in pins if it["id"] in st["pins"]}

    def tot(k):
        vals = [v[k] for v in got.values() if v.get(k) is not None]
        return sum(vals) if vals else None
    with db() as con:
        for pid, v in got.items():
            con.execute("insert into video_snap values(?,?,?,?,?,?,?)",
                        (ts, "pinterest", pid, v.get("impressions"), v.get("saves"), None, None))
        if got:
            con.execute("insert into channel_snap values(?,?,?,?,?,?,?)",
                        (ts, "pinterest", None, tot("impressions"), tot("saves"), len(pins), None))
    set_status("pinterest", True, f"{len(got)}/{len(pins)} posts with stats · stats.json updated {st['updated'] or '?'}")


# ----------------------------------------------------------------------------- monetization

def load_monetization() -> dict:
    m = read_json(MON_PATH)
    return m if isinstance(m, dict) else {"programs": []}


def fetch_yt_monetization() -> dict:
    """Long-form watch hours (365 d) and Shorts views (90 d) from YouTube Analytics, split by content type."""
    end = date.today()
    out = {}
    for days, key in ((365, "y"), (90, "q")):
        url = YTA_API + "?" + urllib.parse.urlencode({
            "ids": "channel==MINE", "startDate": (end - timedelta(days=days)).isoformat(),
            "endDate": end.isoformat(), "metrics": "views,estimatedMinutesWatched",
            "dimensions": "creatorContentType"})
        res = authed_json(url)
        rows = {str(r[0]).lower(): (r[1] or 0, r[2] or 0) for r in res.get("rows") or []}
        out[key] = rows
    long_minutes = sum(m for t, (v, m) in out["y"].items() if t not in ("shorts", "story"))
    return {"watch_hours_365d": round(long_minutes / 60, 1),
            "shorts_views_90d": out["q"].get("shorts", (0, 0))[0], "ts": now()}


def _window_views(con, platform, ids_published, days):
    """Views gained in the last `days` days by the given posts; estimate flag when history is too short."""
    cutoff = now() - days * 86400
    total, estimate = 0, False
    for vid, published in ids_published:
        cur = _row(con, "select views, ts from video_snap where platform=? and video_id=? and views is not null "
                        "order by ts desc limit 1", (platform, vid))
        if not cur:
            continue
        pub_ts = None
        try:
            pub_ts = int(datetime.fromisoformat(str(published).replace("Z", "+00:00")).timestamp()) if published else None
        except ValueError:
            pass
        if pub_ts and pub_ts >= cutoff:
            total += cur["views"]
            continue
        base = _row(con, "select views from video_snap where platform=? and video_id=? and views is not null and ts<=? "
                         "order by ts desc limit 1", (platform, vid, cutoff))
        if base:
            total += cur["views"] - base["views"]
        else:
            first = _row(con, "select views from video_snap where platform=? and video_id=? and views is not null "
                              "order by ts asc limit 1", (platform, vid))
            total += cur["views"] - (first["views"] if first else 0) if pub_ts is None else cur["views"]
            estimate = True
    return total, estimate


def monetization_metrics(series) -> dict:
    M = {}
    with db() as con:
        ch = {p: _row(con, "select * from channel_snap where platform=? order by ts desc limit 1", (p,))
              for p in ("youtube", "tiktok", "facebook", "instagram")}
        M["yt_subscribers"] = {"value": (ch["youtube"] or {}).get("followers")}
        live = set(kv_get("youtube_ids", []) or [])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        n90 = sum(1 for r in con.execute("select video_id, published, privacy from video_meta where platform='youtube'")
                  if (not live or r["video_id"] in live) and r["privacy"] == "public" and (r["published"] or "") >= cutoff)
        M["yt_uploads_90d"] = {"value": n90 if ch["youtube"] else None}
        ym = kv_get("yt_monetization")
        if ym:
            M["yt_watch_hours_365d"] = {"value": ym["watch_hours_365d"],
                                        "note": "YouTube Analytics, long-form (non-Shorts) watch time; 2-3 days lag"}
            M["yt_shorts_views_90d"] = {"value": ym["shorts_views_90d"], "note": "YouTube Analytics; 2-3 days lag"}
        else:
            note = kv_get("yt_monetization_error") or "YouTube Analytics not available"
            M["yt_watch_hours_365d"] = {"value": None, "note": note}
            M["yt_shorts_views_90d"] = {"value": None, "note": note}
        M["tt_followers"] = {"value": (ch["tiktok"] or {}).get("followers")}
        tt_live = kv_get("tiktok_videos", {}) or {}
        tt_posts = [(s["tiktok"]["id"], (tt_live.get(s["tiktok"]["id"]) or {}).get("published"))
                    for s in series if s["tiktok"] and s["tiktok"]["id"]]
        v30, est = _window_views(con, "tiktok", tt_posts, 30)
        M["tt_views_30d"] = {"value": v30 if ch["tiktok"] else None,
                             "note": "series posts only" + ("; estimate (history < 30 days)" if est else "")}
        fb_rows = [dict(r) for r in con.execute(
            "select ts, followers from channel_snap where platform='facebook' and followers is not null and ts>=? order by ts",
            (now() - 30 * 86400,))]
        first_fb = _row(con, "select min(ts) as t from channel_snap where platform='facebook' and followers is not null", ())
        days_cov = int((now() - first_fb["t"]) / 86400) if first_fb and first_fb["t"] else 0
        M["fb_followers_30d"] = {"value": min(r["followers"] for r in fb_rows) if fb_rows else None,
                                 "history_days": days_cov,
                                 "note": "lowest follower count in the last 30 days"}
        M["ig_followers"] = {"value": (ch["instagram"] or {}).get("followers")}
    return M


def _eval_req(req, M):
    if "any_of" in req:
        alts = [_eval_req(r, M) for r in req["any_of"]]
        met = True if any(a["met"] for a in alts) else (None if all(a["met"] is None for a in alts) else False)
        best = max((a for a in alts if a.get("progress") is not None), key=lambda a: a["progress"], default=None)
        return {"any_of": alts, "met": met, "numeric": True, "progress": best["progress"] if best else None}
    if "manual" in req:
        return {"label": req["label"], "manual": True, "met": req["manual"], "note": req.get("note"), "numeric": False}
    m = M.get(req["metric"], {})
    val, target = m.get("value"), req["target"]
    need_days = req.get("history_days")
    met = None if val is None else val >= target
    note = m.get("note")
    if met and need_days and (m.get("history_days") or 0) < need_days:
        met = False
        note = f"needs {need_days} days of history (have {m.get('history_days') or 0})"
    return {"label": req["label"], "value": val, "target": target, "met": met, "numeric": True, "note": note,
            "progress": None if val is None else min(1.0, max(0.0, val / target))}


def evaluate_monetization(series) -> dict:
    mon = load_monetization()
    M = monetization_metrics(series)
    out = {"checked_on": mon.get("checked_on"), "country": mon.get("country"), "platforms": {}}
    for prog in mon.get("programs", []):
        reqs = [_eval_req(r, M) for r in prog.get("requirements", [])]
        numeric = [r for r in reqs if r["numeric"]]
        thresholds_met = bool(numeric) and all(r["met"] is True for r in numeric)
        eligible = all(r["met"] is True for r in reqs)
        blockers = [r["label"] for r in reqs if not r["numeric"] and r["met"] is False]
        if prog.get("invite_only"):
            status = "invite"
        elif eligible:
            status = "eligible"
        elif thresholds_met:
            status = "thresholds"
        else:
            status = "not_yet"
        p = {"id": prog["id"], "name": prog["name"], "short": prog.get("short") or prog["name"],
             "source": prog.get("source"), "checked_on": prog.get("checked_on"), "notes": prog.get("notes"),
             "invite_only": bool(prog.get("invite_only")), "requirements": reqs, "status": status,
             "thresholds_met": thresholds_met, "met_count": sum(1 for r in reqs if r["met"] is True),
             "total": len(reqs), "blockers": blockers}
        out["platforms"].setdefault(prog["platform"], {"programs": []})["programs"].append(p)
    for plat in out["platforms"].values():   # nearest milestone = unmet numeric requirement closest to done
        best = None
        for p in plat["programs"]:
            if p["invite_only"]:
                continue
            for r in p["requirements"]:
                for x in (r.get("any_of") or [r]):
                    if x.get("numeric") and x.get("met") is False and x.get("progress") is not None:
                        if best is None or x["progress"] > best[0]:
                            best = (x["progress"], x, p)
        if best:
            _, x, p = best
            plat["next"] = {"label": x["label"], "value": x["value"], "target": x["target"],
                            "remaining": max(0, x["target"] - (x["value"] or 0)), "program": p["short"]}
    return out


# ----------------------------------------------------------------------------- notifications

TOAST_PS = r"""
$title = $env:LEO_TOAST_TITLE; $text = $env:LEO_TOAST_TEXT
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
  $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $nodes = $xml.GetElementsByTagName('text')
  $nodes.Item(0).AppendChild($xml.CreateTextNode($title)) | Out-Null
  $nodes.Item(1).AppendChild($xml.CreateTextNode($text)) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
  $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
  'toast'
} catch {
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $n = New-Object System.Windows.Forms.NotifyIcon
  $n.Icon = [System.Drawing.SystemIcons]::Information
  $n.Visible = $true
  $n.ShowBalloonTip(10000, $title, $text, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Seconds 11
  $n.Dispose()
  'balloon'
}
"""


def desktop_notify(title: str, text: str) -> str:
    """Windows toast (balloon fallback) via Windows PowerShell; texts go through env vars, never the command line."""
    if os.name != "nt":
        return "not windows"
    ps = shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    env = {**os.environ, "LEO_TOAST_TITLE": title[:120], "LEO_TOAST_TEXT": text[:250]}
    enc = base64.b64encode(TOAST_PS.encode("utf-16-le")).decode()
    try:
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], env=env,
                           capture_output=True, text=True, timeout=25,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip().splitlines()
        return out[-1] if out else f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return "balloon"   # the balloon path sleeps while it is shown
    except Exception as e:
        return "failed: " + redact(e)


def log_alert(line: str):
    with open(ALERTS_LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")


def check_eligibility(series):
    """Fire once per program when its public thresholds go from not met to met."""
    ev = evaluate_monetization(series)
    fired = []
    with db() as con:
        for plat, block in ev["platforms"].items():
            for p in block["programs"]:
                if p["invite_only"]:
                    continue
                prev = con.execute("select met from mon_state where program=?", (p["id"],)).fetchone()
                met = 1 if p["thresholds_met"] else 0
                if (prev is None or prev["met"] == 0) and met == 1:
                    title = f"Leo Explains: {p['name']}"
                    msg = ("ELIGIBLE: all requirements met. Apply now." if p["status"] == "eligible" else
                           "Thresholds met." + (f" Still blocked by: {', '.join(p['blockers'])}." if p["blockers"] else
                                                " Confirm the manual checks and apply."))
                    con.execute("insert into alerts(ts, program, title, message) values(?,?,?,?)",
                                (now(), p["id"], title, msg))
                    fired.append((title, msg))
                if prev is None or prev["met"] != met:
                    con.execute("insert or replace into mon_state values(?,?,?)", (p["id"], met, now()))
    for title, msg in fired:
        log_alert(f"ELIGIBLE  {title} :: {msg}")
        threading.Thread(target=desktop_notify, args=(title, msg), daemon=True).start()
    return fired


# ----------------------------------------------------------------------------- refresh

_refresh_lock = threading.Lock()
_state = {"last_start": 0, "refreshing": False, "next_auto": 0}


def set_status(source, ok, msg=""):
    st = kv_get("status", {})
    st[source] = {"ok": ok, "msg": redact(msg) if msg else "", "ts": now()}
    kv_set("status", st)


def refresh():
    if not _refresh_lock.acquire(blocking=False):
        return False
    _state["refreshing"], _state["last_start"] = True, time.time()
    pool = ThreadPoolExecutor(max_workers=3)
    try:
        ts = now()
        series = local_series()
        # posts from social/post_log.json that are not in vN/*_result.json (comics, pins, ...)
        try:
            log_items = post_log_items(series, kv_get("youtube_ids", []) or [])
        except Exception:
            traceback.print_exc()
            log_items = []
        log_series = log_fetch_series(log_items)
        fetch_series = series + log_series
        try:
            ensure_log_thumbs(log_items, {})
        except Exception:
            traceback.print_exc()

        # TikTok / Facebook / Instagram public pages are slow (one page per post, 1 s apart per site):
        # fetch the three sites at the same time, in the background, while the YouTube APIs run.
        handle = tiktok_handle(series)
        social = {p: (ident, (pool.submit(fetch, ident, fetch_series)
                              if ident or sum(len(s[p]) for s in fetch_series) else None))
                  for p, ident, fetch in (("facebook", facebook_page(series), fetch_facebook),
                                          ("instagram", instagram_handle(series), fetch_instagram))}
        tt_future = pool.submit(fetch_tiktok, handle, fetch_series) if handle else None

        # YouTube Data API: 1 (channel) + ceil(n/50) (playlist) + ceil(n/50) (videos) quota units
        try:
            y = fetch_youtube(series)
            likes = sum(v["likes"] or 0 for v in y["videos"])
            comments = sum(v["comments"] or 0 for v in y["videos"])
            with db() as con:
                con.execute("insert into channel_snap values(?,?,?,?,?,?,?)",
                            (ts, "youtube", y["subscribers"], y["views"], likes, y["video_count"], comments))
                for v in y["videos"]:
                    con.execute("insert into video_snap values(?,?,?,?,?,?,?)",
                                (ts, "youtube", v["id"], v["views"], v["likes"], v["comments"], None))
                    con.execute("insert or replace into video_meta values(?,?,?,?,?,?,?,?,?)",
                                ("youtube", v["id"], v["title"], v["kind"], v["published"], v["duration"],
                                 v["privacy"], v["thumb"], v["url"]))
            kv_set("youtube_info", y["info"])
            kv_set("youtube_ids", [v["id"] for v in y["videos"]])
            set_status("youtube", True, f"{len(y['videos'])} videos read")
        except ApiError as e:
            set_status("youtube", False, f"YouTube: {e}")
        except Exception as e:
            set_status("youtube", False, f"YouTube: {redact(e)}")
            traceback.print_exc()

        # YouTube Analytics (separate API/quota). Skip for a while after a permission denial.
        prev = kv_get("status", {}).get("analytics", {})
        denied_recently = prev.get("denied") and ts - prev.get("ts", 0) < ANALYTICS_RETRY_AFTER_DENIED
        if not denied_recently:
            try:
                rows = fetch_analytics()
                with db() as con:
                    for r in rows:
                        con.execute("insert or replace into analytics_day values(?,?,?,?,?,?)",
                                    (r.get("day"), r.get("views"), r.get("estimatedMinutesWatched"),
                                     r.get("averageViewDuration"), r.get("subscribersGained"),
                                     r.get("subscribersLost")))
                set_status("analytics", True, f"{len(rows)} days")
            except ApiError as e:
                st = kv_get("status", {})
                denied = e.code in (401, 403)
                st["analytics"] = {"ok": False, "denied": denied, "ts": ts,
                                   "msg": "Analytics unavailable (missing permission)" if denied
                                   else f"Analytics: {redact(e)}"}
                kv_set("status", st)
            except Exception as e:
                set_status("analytics", False, f"Analytics: {redact(e)}")
            try:   # monetization inputs: long-form watch hours (365 d) + Shorts views (90 d)
                kv_set("yt_monetization", fetch_yt_monetization())
                kv_set("yt_monetization_error", None)
            except Exception as e:
                kv_set("yt_monetization_error", "YouTube Analytics unavailable: " + redact(e)[:120])

        # TikTok: public profile page only, no login, no cookies.
        if not handle:
            set_status("tiktok", False, "TikTok account not set (fill in tiktok_handle in dashboard/config.json)")
        else:
            t = tt_future.result()
            with db() as con:
                if t["user"]:
                    views = sum(v["views"] or 0 for v in t["videos"].values()) if t["videos"] else None
                    comments = sum(v["comments"] or 0 for v in t["videos"].values()) if t["videos"] else None
                    con.execute("insert into channel_snap values(?,?,?,?,?,?,?)",
                                (ts, "tiktok", t["user"]["followers"], views, t["user"]["likes"],
                                 t["user"]["videos"], comments))
                for vid, v in t["videos"].items():
                    con.execute("insert into video_snap values(?,?,?,?,?,?,?)",
                                (ts, "tiktok", vid, v["views"], v["likes"], v["comments"], v["shares"]))
            if t["user"]:
                kv_set("tiktok_info", {"nickname": t["user"]["nickname"], "avatar": t["user"]["avatar"],
                                       "handle": handle})
            kv_set("tiktok_videos", t["videos"])
            if t["user"] and not t["errors"]:
                set_status("tiktok", True, f"profile read, {len(t['videos'])} videos with stats")
            elif t["user"]:
                set_status("tiktok", True, "profile read; some videos without stats: " + "; ".join(t["errors"]))
            else:
                set_status("tiktok", False, "TikTok stats not available automatically (" + "; ".join(t["errors"]) + ")")

        # Facebook Page + Instagram: public pages only.
        images = {("tiktok", vid): v.get("thumb") for vid, v in (kv_get("tiktok_videos", {}) or {}).items()}
        for platform, missing_msg in (
                ("facebook", "Facebook Page not set (fill in facebook_page_url in dashboard/config.json)"),
                ("instagram", "Instagram account not set (fill in instagram_handle in dashboard/config.json)")):
            ident, future = social[platform]
            posted = sum(len(s[platform]) for s in fetch_series)
            name = platform.capitalize()
            try:
                if future is None:
                    set_status(platform, False, missing_msg)
                    continue
                res = future.result()
                store_social(ts, platform, res, posted)
                for pid, img in (res.get("images") or {}).items():
                    images[(platform, pid)] = img
                got_user = res["user"] and any(res["user"].get(k) is not None for k in ("followers", "likes", "posts"))
                parts = []
                if not ident:
                    parts.append(missing_msg)
                parts.append(("page read" if got_user else "page counters unavailable")
                             + f", {len(res['posts'])}/{posted} posts with stats")
                if res["errors"]:
                    parts.append("; ".join(res["errors"][:4]))
                ok = bool(got_user or res["posts"])
                set_status(platform, ok, (" · ".join(parts)) if ok else
                           f"{name} stats unavailable automatically (" + " · ".join(parts) + ")")
            except Exception as e:
                set_status(platform, False, f"{name} stats unavailable automatically ({redact(e)})")
        try:
            ensure_thumbs(series, images)
        except Exception:
            traceback.print_exc()
        try:
            ensure_log_thumbs(log_items, images)
        except Exception:
            traceback.print_exc()
        try:   # Pinterest: numbers come from social/pinterest/stats.json (monitor task), never fetched here
            store_pinterest(ts, log_items)
        except Exception as e:
            set_status("pinterest", False, f"Pinterest stats unavailable ({redact(e)})")
        try:
            check_eligibility(series)
        except Exception:
            traceback.print_exc()
        kv_set("last_refresh", ts)
        return True
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        _state["refreshing"] = False
        _refresh_lock.release()


def auto_loop():
    while True:
        try:
            refresh()
        except Exception:
            traceback.print_exc()
        _state["next_auto"] = now() + AUTO_INTERVAL
        time.sleep(AUTO_INTERVAL)


# ----------------------------------------------------------------------------- summary building

METRICS = ("followers", "views", "likes", "videos", "comments")


def _row(con, sql, args):
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def channel_block(con, platform):
    cur = _row(con, "select * from channel_snap where platform=? order by ts desc limit 1", (platform,))
    if not cur:
        return None
    prev = _row(con, "select * from channel_snap where platform=? and ts<? order by ts desc limit 1",
                (platform, cur["ts"]))
    oldest = _row(con, "select * from channel_snap where platform=? order by ts asc limit 1", (platform,))

    def base(seconds):
        b = _row(con, "select * from channel_snap where platform=? and ts<=? order by ts desc limit 1",
                 (platform, cur["ts"] - seconds))
        if b:
            return b, False
        return (oldest, True) if oldest and oldest["ts"] < cur["ts"] else (None, False)

    def diff(b):
        return {m: (cur[m] - b[m]) if (b and cur[m] is not None and b[m] is not None) else None
                for m in METRICS}

    b24, p24 = base(86400)
    b7, p7 = base(7 * 86400)
    return {
        "ts": cur["ts"], "current": {m: cur[m] for m in METRICS},
        "delta_prev": diff(prev) if prev else None, "prev_ts": prev["ts"] if prev else None,
        "delta_24h": diff(b24) if b24 else None, "since_24h": b24["ts"] if b24 else None, "partial_24h": p24,
        "delta_7d": diff(b7) if b7 else None, "since_7d": b7["ts"] if b7 else None, "partial_7d": p7,
        "snapshots": con.execute("select count(*) from channel_snap where platform=?", (platform,)).fetchone()[0],
    }


STALE_24H_HOURS = 30


def video_numbers(con, platform, vid):
    cur = _row(con, "select * from video_snap where platform=? and video_id=? order by ts desc limit 1",
               (platform, vid))
    if not cur:
        return None
    b = _row(con, "select * from video_snap where platform=? and video_id=? and ts<=? order by ts desc limit 1",
             (platform, vid, cur["ts"] - 86400))
    partial = False
    if not b:
        b = _row(con, "select * from video_snap where platform=? and video_id=? order by ts asc limit 1",
                 (platform, vid))
        partial = True
        if b and b["ts"] >= cur["ts"]:
            b = None
    v24 = (cur["views"] - b["views"]) if (b and cur["views"] is not None and b["views"] is not None) else None
    # 2026-11-12 (the town coordinator's request): a video that is no longer read (removed, private, "no public data")
    # kept showing the gain of its LAST read day as "views in the last 24 h" for days: 7704998707887869206 showed +112
    # on 12.11 with its last reading from 07.11. Without a reading in the last STALE_24H_HOURS there is no 24 h number.
    if time.time() - cur["ts"] > STALE_24H_HOURS * 3600:
        v24 = None
    return {"views": cur["views"], "likes": cur["likes"], "comments": cur["comments"],
            "shares": cur["shares"], "views_24h": v24, "partial_24h": partial and v24 is not None,
            "since_24h": b["ts"] if b else None, "ts": cur["ts"]}


def like_rate(likes, views):
    return round(likes / views, 4) if likes is not None and views else None


def _pinterest_block(videos, pst, channel) -> dict:
    pins = [v for v in videos if v["platform"] == "pinterest"]

    def tot(k):
        vals = [v.get(k) for v in pins if v.get(k) is not None]
        return sum(vals) if vals else None
    prof = pinterest_profile()
    m = re.match(r"https://www\.pinterest\.com/([^/]+)/", prof)
    return {"handle": m.group(1) if m else None, "profile_url": prof or None, "info": None,
            "channel": channel, "posted": len(pins), "stats_file": pst is not None,
            "stats_updated": (pst or {}).get("updated"),
            "totals": {"pins": len(pins), "impressions": tot("views"), "saves": tot("likes"),
                       "outbound_clicks": tot("outbound_clicks"), "pin_clicks": tot("pin_clicks"),
                       "with_stats": sum(1 for v in pins if v.get("stats"))},
            "note": None if pst is not None else "Pinterest stats update every few hours"}


def summary() -> dict:
    series = local_series()
    handle = tiktok_handle(series)
    ig = instagram_handle(series)
    durations = kv_get("short_durations", {}) or {}
    sid = {}
    for s in series:
        if s["long_id"]:
            sid[s["long_id"]] = s["series"]
        if s["short_id"]:
            sid[s["short_id"]] = s["series"]
    videos = []
    with db() as con:
        yt_block = channel_block(con, "youtube")
        tt_block = channel_block(con, "tiktok")
        live_ids = set(kv_get("youtube_ids", []) or [])
        for m in con.execute("select * from video_meta where platform='youtube' order by published desc"):
            m = dict(m)
            if live_ids and m["video_id"] not in live_ids:
                continue  # deleted from the channel since
            n = video_numbers(con, "youtube", m["video_id"]) or {}
            videos.append({
                "platform": "youtube", "kind": m["kind"], "id": m["video_id"], "title": m["title"],
                "published": m["published"], "duration": m["duration"], "privacy": m["privacy"],
                "thumb": m["thumb"], "url": m["url"], "series": sid.get(m["video_id"]),
                "views": n.get("views"), "likes": n.get("likes"), "comments": n.get("comments"),
                "like_rate": like_rate(n.get("likes"), n.get("views")),
                "views_24h": n.get("views_24h"), "partial_24h": n.get("partial_24h", False),
                "stats": bool(n),
            })
        tt_live = kv_get("tiktok_videos", {}) or {}
        for s in series:
            t = s["tiktok"]
            if not (t and t["posted"]):
                continue
            n = video_numbers(con, "tiktok", t["id"]) if t["id"] else None
            live = tt_live.get(t["id"] or "", {})
            pub = live.get("published") or (datetime.fromtimestamp(t["file_ts"], timezone.utc).isoformat()
                                              if t["file_ts"] else None)
            url = t["url"] or (f"https://www.tiktok.com/@{handle}" if handle else None)
            videos.append({
                "platform": "tiktok", "kind": "tiktok", "id": t["id"] or s["series"], "title": s["title"],
                "caption": t["caption"], "published": pub, "published_estimated": not live.get("published"),
                "duration": live.get("duration") or durations.get(s["series"]), "privacy": "public",
                "thumb": thumb_url("tiktok", t["id"], s["series"]), "url": url,
                "series": s["series"],
                "views": (n or {}).get("views"), "likes": (n or {}).get("likes"),
                "comments": (n or {}).get("comments"), "shares": (n or {}).get("shares"),
                "like_rate": like_rate((n or {}).get("likes"), (n or {}).get("views")),
                "views_24h": (n or {}).get("views_24h"), "partial_24h": (n or {}).get("partial_24h", False),
                "stats": bool(n),
            })
        social_blocks = {p: channel_block(con, p) for p in ("facebook", "instagram")}
        for platform in ("facebook", "instagram"):
            for s in series:
                for p in s[platform]:
                    n = video_numbers(con, platform, p["id"]) or {}
                    pub = p.get("posted_at") or (datetime.fromtimestamp(p["file_ts"], timezone.utc).isoformat()
                                                 if p["file_ts"] else None)
                    videos.append({
                        "platform": platform, "kind": platform, "id": p["id"], "title": s["title"],
                        "subtype": p.get("kind"), "caption": p["caption"], "published": pub,
                        "published_estimated": not p.get("posted_at"), "duration": durations.get(s["series"]),
                        "privacy": "public", "thumb": thumb_url(platform, p["id"], s["series"]),
                        "url": p["url"], "series": s["series"],
                        "views": n.get("views"), "likes": n.get("likes"), "comments": n.get("comments"),
                        "shares": n.get("shares"), "like_rate": like_rate(n.get("likes"), n.get("views")),
                        "views_24h": n.get("views_24h"), "partial_24h": n.get("partial_24h", False),
                        "stats": bool(n),
                    })
        # posting log: comics, Pinterest pins, YouTube community post, TikTok photo post (never breaks the page)
        pst = pinterest_stats()
        log_count = {}
        try:
            log_items = post_log_items(series, live_ids or [v["id"] for v in videos if v["platform"] == "youtube"])
        except Exception:
            traceback.print_exc()
            log_items = []
        for it in log_items:
            try:
                n = video_numbers(con, it["platform"], it["id"]) or {}
                row = {
                    "platform": it["platform"], "kind": it["kind"], "id": it["id"], "title": it["title"],
                    "format": it["format"], "subtype": it["subtype"], "caption": "", "published": it["published"],
                    "published_estimated": False, "duration": None, "privacy": "public",
                    "thumb": thumb_url("log_" + it["platform"], it["id"], it["series"]),
                    "url": it["url"], "series": it["series"], "board": it["board"], "source": "post_log",
                    "views": n.get("views"), "likes": n.get("likes"), "comments": n.get("comments"),
                    "shares": n.get("shares"), "views_24h": n.get("views_24h"),
                    "partial_24h": n.get("partial_24h", False), "stats": bool(n),
                }
                if it["platform"] == "pinterest":   # Views = impressions, Likes = saves (fresh from stats.json)
                    ps = (pst or {}).get("pins", {}).get(it["id"])
                    if ps:
                        row.update(views=ps.get("impressions"), likes=ps.get("saves"),
                                   outbound_clicks=ps.get("outbound_clicks"), pin_clicks=ps.get("pin_clicks"),
                                   stats=any(v is not None for v in ps.values()))
                    else:
                        row.update(stats=False, views=None, likes=None, views_24h=None)
                row["like_rate"] = like_rate(row["likes"], row["views"])
                videos.append(row)
                log_count[it["platform"]] = log_count.get(it["platform"], 0) + 1
            except Exception:
                traceback.print_exc()
        pin_block = channel_block(con, "pinterest")
        an_rows = [dict(r) for r in con.execute(
            "select * from analytics_day where day>=? order by day",
            ((date.today() - timedelta(days=28)).isoformat(),))]

    by_id = {(v["platform"], v["id"]): v for v in videos}
    series_out = []
    for s in series:
        def pick(platform, vid):
            v = by_id.get((platform, vid)) if vid else None
            return {"id": vid, "url": v["url"] if v else None, "views": v["views"] if v else None,
                    "likes": v["likes"] if v else None} if vid else None
        t = s["tiktok"]
        series_out.append({
            "series": s["series"], "title": s["title"],
            "long": pick("youtube", s["long_id"]),
            "short": pick("youtube", s["short_id"]),
            "tiktok": ({"posted": t["posted"], "url": t["url"],
                        "views": (by_id.get(("tiktok", t["id"])) or {}).get("views") if t["id"] else None}
                       if t else None),
            **{platform: [{"url": p["url"], "kind": p.get("kind"),
                           "views": (by_id.get((platform, p["id"])) or {}).get("views"),
                           "likes": (by_id.get((platform, p["id"])) or {}).get("likes")}
                          for p in s[platform]]
               for platform in ("facebook", "instagram")},
        })

    status = kv_get("status", {})
    an_status = status.get("analytics", {})
    try:
        monetization = evaluate_monetization(series)
    except Exception as e:
        monetization = {"error": redact(e), "platforms": {}}
    with db() as con:
        alerts = [dict(r) for r in con.execute(
            "select id, ts, program, title, message from alerts where dismissed=0 order by ts desc limit 10")]
    totals = None
    if an_rows:
        tv = sum(r["views"] or 0 for r in an_rows)
        tm = sum(r["minutes"] or 0 for r in an_rows)
        totals = {"views": tv, "minutes": tm,
                  "avg_dur": round(tm * 60 / tv) if tv else None,
                  "subs_gained": sum(r["subs_gained"] or 0 for r in an_rows),
                  "subs_lost": sum(r["subs_lost"] or 0 for r in an_rows)}
    return {
        "generated": now(),
        "last_refresh": kv_get("last_refresh"),
        "next_refresh": _state["next_auto"] or None,
        "refreshing": _state["refreshing"],
        "manual_wait": max(0, int(MANUAL_MIN_GAP - (time.time() - _state["last_start"]))),
        "status": {k: {"ok": v.get("ok"), "msg": v.get("msg"), "ts": v.get("ts")} for k, v in status.items()},
        "youtube": {"info": kv_get("youtube_info"), "channel": yt_block},
        "tiktok": {"handle": handle or None,
                   "profile_url": f"https://www.tiktok.com/@{handle}" if handle else None,
                   "info": kv_get("tiktok_info"), "channel": tt_block},
        "facebook": {"handle": None, "profile_url": facebook_page(series) or None,
                     "info": kv_get("facebook_info"), "channel": social_blocks["facebook"],
                     "posted": sum(len(s["facebook"]) for s in series) + log_count.get("facebook", 0)},
        "instagram": {"handle": ig or None,
                      "profile_url": f"https://www.instagram.com/{ig}/" if ig else None,
                      "info": kv_get("instagram_info"), "channel": social_blocks["instagram"],
                      "posted": sum(len(s["instagram"]) for s in series) + log_count.get("instagram", 0)},
        "pinterest": _pinterest_block(videos, pst, pin_block),
        "analytics": {"available": bool(an_rows),
                      "note": an_status.get("msg") if not an_status.get("ok") else None,
                      "rows": an_rows, "totals": totals},
        "series": series_out,
        "videos": videos,
        "monetization": monetization,
        "alerts": alerts,
    }


def _thin(rows, limit=1500):
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)] + [rows[-1]]


def history(platform) -> list:
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "select ts, followers, views, likes, videos from channel_snap where platform=? order by ts",
            (platform,))]
    return _thin(rows)


def video_history(platform, vid) -> list:
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "select ts, views, likes, comments from video_snap where platform=? and video_id=? order by ts",
            (platform, vid))]
    return _thin(rows)


# ----------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "LeoDashboard/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet; no URLs carry secrets anyway
        pass

    def _send(self, code, body: bytes, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                self._send(200, INDEX_PATH.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/summary":
                self._json(summary())
            elif u.path == "/api/history":
                self._json(history(q.get("platform", ["youtube"])[0]))
            elif u.path == "/api/video_history":
                self._json(video_history(q.get("platform", ["youtube"])[0], q.get("id", [""])[0]))
            elif u.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif re.fullmatch(r"/thumbs/[A-Za-z0-9_.-]+\.jpg", u.path):
                f = THUMBS_DIR / u.path.rsplit("/", 1)[1]
                if f.is_file() and f.resolve().parent == THUMBS_DIR.resolve():
                    body = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._json({"error": "not found"}, 404)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": redact(e)}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/api/test_notification", "/api/alerts/dismiss"):
            # custom header = only our own page (a cross-site form/fetch cannot send it without CORS)
            if self.headers.get("X-Leo-Dashboard") != "1":
                return self._json({"error": "forbidden"}, 403)
            if u.path == "/api/alerts/dismiss":
                with db() as con:
                    con.execute("update alerts set dismissed=1 where dismissed=0")
                return self._json({"ok": True})
            if time.time() - _state.get("last_test", 0) < 10:
                return self._json({"ok": False, "error": "wait a few seconds between tests"}, 429)
            _state["last_test"] = time.time()
            title, msg = "Leo Explains: test notification", "Notifications work. You will see this when a program becomes eligible."
            log_alert(f"TEST      {title} :: {msg}")
            how = desktop_notify(title, msg)
            return self._json({"ok": not how.startswith("failed"), "method": how, "title": title, "message": msg})
        if u.path != "/api/refresh":
            return self._json({"error": "not found"}, 404)
        wait = int(MANUAL_MIN_GAP - (time.time() - _state["last_start"]))
        if _state["refreshing"]:
            return self._json({"ok": False, "error": "refresh already in progress", "retry_after": 5}, 409)
        if wait > 0:
            return self._json({"ok": False, "error": f"wait {wait} s between refreshes",
                               "retry_after": wait}, 429)
        try:
            ran = refresh()
        except Exception as e:
            return self._json({"ok": False, "error": redact(e)}, 500)
        self._json({"ok": ran, **({} if ran else {"error": "refresh already in progress"})}, 200 if ran else 409)


def main():
    init_db()
    load_config()
    threading.Thread(target=auto_loop, daemon=True, name="auto-refresh").start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Leo Explains dashboard: http://{HOST}:{PORT}  (auto-refresh every {AUTO_INTERVAL // 60} min)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
