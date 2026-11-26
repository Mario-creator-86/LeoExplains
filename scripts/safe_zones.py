"""Per-platform safe areas for 1080x1920 vertical video (owner 2026-11-03: "Tot contentul trebuie adaptat
platformei"). Each value is the strip, in pixels, that the platform's own interface covers on a phone:
nothing we need people to read (captions, hook, end line, comic text) may sit inside it.

None of the platforms publishes organic pixel margins; the numbers below take the cautious end of the
third-party measurements found on 2026-11-03 and the owner's own phone screenshot of a comic Short
(YouTube title row from y ~1400, chips and "Share" below, buttons on the right from y ~750):
  YouTube Shorts  top 180-380, bottom 350-560, right 120-194  (exemplary.ai, imagevideofit.com,
                  postlinkapp.com, shortsafezone.com)
  TikTok          top 130-220, bottom 422-528, right 140-185, left 60-65  (kreatli.com, revid.ai,
                  imagevideofit.com, postplanify.com, rightblogger.com)
  IG/FB Reels     top 220-270, bottom 400-672, sides 35-65, right buttons ~130  (Meta ad guide as
                  quoted by lilachbullock.com and adchecklab.com; fileflippers.com, zeely.ai)
Platforms change their interface a few times a year: re-check against a phone screenshot when one shows
covered text, and update the numbers here (every tool reads them from this file).
"""

SW, SH = 1080, 1920

PROFILES = {
    # YouTube Shorts: short.mp4, comic Shorts
    "youtube_shorts": {"top": 240, "bottom": 560, "left": 60, "right": 170},
    # TikTok: short_tiktok.mp4, comic TikTok videos
    "tiktok": {"top": 220, "bottom": 520, "left": 60, "right": 185},
    # Instagram + Facebook Reels: short_reels.mp4
    "reels": {"top": 270, "bottom": 600, "left": 65, "right": 150},
}
# the full-length TikTok story (shorts.py --tiktok --long): same interface as any TikTok
PROFILES["tiktok_long"] = PROFILES["tiktok"]


def zone(profile):
    """(x0, y0, x1, y1) of the area that stays visible on that platform."""
    p = PROFILES[profile]
    return p["left"], p["top"], SW - p["right"], SH - p["bottom"]


def caption_style(profile, size=84):
    """ASS caption style, bottom-anchored: the lowest caption line ends 20 px above the covered strip and
    a second line grows upwards."""
    p = PROFILES[profile]
    return ("Style: Cap,Arial Black,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,"
            "100,100,1,0,1,7,3,2,%d,%d,%d,1" % (size, p["left"] + 30, p["right"], p["bottom"] + 20))


def top_text_margin(profile):
    """MarginV for top-anchored hook / end lines: 40 px below the covered top strip."""
    return PROFILES[profile]["top"] + 40
