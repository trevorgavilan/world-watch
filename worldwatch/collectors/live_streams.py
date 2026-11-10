"""Middle East live — live cams and regional news channels on YouTube, each labelled with who runs it.

The list is curated here (WORLD WATCH SOURCES § 2 holds who runs each and the terms); nothing is
discovered by scraping — YouTube's terms bar automated access to its pages. Two sources:
- `mideast-cams`: streams with a fixed video id (cams, and re-streams of several cams), checked every
  few hours through YouTube's published oEmbed endpoint (https://www.youtube.com/oembed?format=json&url=…)
  — 200 while the video exists and its owner allows embedding; 401 (embedding off) or 404 (gone) skip
  that one, and it leaves the viewer once its last good check is 2 days old. A cam with a place is a pin.
- `mideast-news`: channels, played as the channel's current live stream, so a restarted stream needs no
  new id. They are listed, not checked: YouTube's channel feeds (the one keyless way to ask about a
  channel) answered 404/500 to most requests on 2026-11-09, and the player itself shows when a channel
  is off-air. Their items say so ("inferred").
Official streams come first. The rest carry a caution, shown with them: local stations whose operator
we couldn't verify, and anonymous re-streams whose pictures' origin is unknown (Trevor, 2026-11-09:
"no matter the source", labelled not verified). Nothing here is presented as verified footage.
The Board plays a stream with YouTube's privacy-enhanced player (youtube-nocookie.com) only after a
click (D-24); the link always opens it on YouTube. Each owner holds the rights to its stream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from urllib.parse import quote

from ..item import Item, make_item
from ..views import Layer, Panel
from . import Collector, ParseError

CAMS_SOURCE = "mideast-cams"
NEWS_SOURCE = "mideast-news"
LICENCE = "© each stream's owner; shown with YouTube's embedded player (YouTube API Terms of Service)"
OEMBED = "https://www.youtube.com/oembed?format=json&url="
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
THUMB_ID = re.compile(r"^https://i\.ytimg\.com/vi/([A-Za-z0-9_-]{11})/")
WINDOW = timedelta(days=2)
KINDS = ("cam", "news")
NOT_VERIFIED = " · not verified"  # appended to the kind (the item's severity) of a stream with a caution
NOT_CHECKED = "Listed, not checked: the player shows if the channel is off-air."
LOCAL = "Not verified: a local station; we could not confirm who runs it."
ANONYMOUS = "Not verified: an anonymous re-stream; where its pictures come from is unknown."


@dataclass(frozen=True)
class Stream:
    key: str
    name: str
    owner: str
    home: str  # where it is, or where the broadcaster is based and who backs it
    kind: str  # "cam" (pictures of a place, or several) or "news" (a channel's programme)
    video: str | None = None  # a fixed live video, checked by oEmbed
    channel: str | None = None  # a channel's current live stream, listed
    lat: float | None = None  # a cam's place: a pin on the map
    lon: float | None = None
    caution: str = ""  # empty: an official stream, run by who it says; else why it is not verified

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.key}: kind must be one of {KINDS}")
        if (self.video is None) == (self.channel is None):
            raise ValueError(f"{self.key}: one of video or channel")
        if self.video is not None and not VIDEO_ID.fullmatch(self.video):
            raise ValueError(f"{self.key}: not a video id")
        if self.channel is not None and not CHANNEL_ID.fullmatch(self.channel):
            raise ValueError(f"{self.key}: not a channel id")
        placed = self.lat is not None and self.lon is not None
        if (self.lat is None) != (self.lon is None) or (placed and not (self.kind == "cam" and self.video)):
            raise ValueError(f"{self.key}: only a cam with a fixed video has a place")
        if self.kind == "cam" and not self.video:
            raise ValueError(f"{self.key}: a cam is a fixed video")
        if self.kind == "cam" and not self.caution and not placed:
            raise ValueError(f"{self.key}: an official cam has its place")

    @property
    def checked(self) -> bool:
        return self.video is not None

    @property
    def severity(self) -> str:
        return self.kind + (NOT_VERIFIED if self.caution else "")

    @property
    def check_url(self) -> str:
        return OEMBED + quote(f"https://www.youtube.com/watch?v={self.video}", safe="")

    @property
    def watch_url(self) -> str:
        if self.video:
            return f"https://www.youtube.com/watch?v={self.video}"
        return f"https://www.youtube.com/channel/{self.channel}/live"


KOTEL = (31.77670, 35.23450)  # the Western Wall plaza, Jerusalem
OLIVES = (31.77850, 35.24450)  # the Mount of Olives, facing the Old City
NABLUS = (32.22110, 35.25440)
WWHF = "Western Wall Heritage Foundation"
VIDEOS = (  # checked by oEmbed
    Stream("kotel-main", "Western Wall 1 · Main Plaza", WWHF, "Jerusalem", "cam", video="LMHUcDktP-w",
           lat=KOTEL[0], lon=KOTEL[1]),
    Stream("kotel-2", "Western Wall 2", WWHF, "Jerusalem", "cam", video="gJsZdfSyPrM", lat=KOTEL[0], lon=KOTEL[1]),
    Stream("kotel-3", "Western Wall 3", WWHF, "Jerusalem", "cam", video="Y3v2WGY-SDc", lat=KOTEL[0], lon=KOTEL[1]),
    Stream("earthcam-kotel", "Western Wall 4 · EarthCam", "EarthCam", "Jerusalem", "cam", video="77akujLn4k8",
           lat=KOTEL[0], lon=KOTEL[1]),
    # Not verified: cams of a place, from channels we can't vouch for.
    Stream("nablus-live", "Nablus Live", "Nablus Live (a local channel)", "Nablus, West Bank", "cam",
           video="8e0Rnxtxwqg", lat=NABLUS[0], lon=NABLUS[1], caution=LOCAL),
    Stream("olives-1", "Mount of Olives · Temple Archaeological Park", "Mt. of Olives Prayer Bridge",
           "Jerusalem, from the Mount of Olives", "cam", video="zp6LNSoq000", lat=OLIVES[0], lon=OLIVES[1],
           caution=LOCAL),
    Stream("olives-2", "Mount of Olives · the Western Wall", "Mt. of Olives Prayer Bridge",
           "Jerusalem, from the Mount of Olives", "cam", video="AKGqd20ik_A", lat=OLIVES[0], lon=OLIVES[1],
           caution=LOCAL),
    Stream("daystar-jerusalem", "Jerusalem (Daystar)", "Daystar, a US Christian network", "Jerusalem, camera place not stated",
           "cam", video="LdS7TXNmQgQ", caution=LOCAL),
    Stream("near-haifa", "Near Haifa (DD Cyprus1Click)", "DD Cyprus1Click", "near Haifa, Israel, as titled", "cam",
           video="NJFjTpDZZXY", caution=ANONYMOUS),
    Stream("north-israel", "Northern Israel skyline (StereoImage_IL)", "StereoImage_IL", "northern Israel, as titled",
           "cam", video="cJZpk10xyJA", caution=ANONYMOUS),
    # Not verified: anonymous grids of many cams.
    Stream("intelcams", "Middle East multi-cam (Intel Cams | OSINT)", "Intel Cams | OSINT", "Iran, Israel, Qatar…, as titled",
           "cam", video="q1NR5q9tZd0", caution=ANONYMOUS),
    Stream("inquizex", "Middle East multi-cam (InquizeX)", "InquizeX", "Israel, Iran…, as titled", "cam",
           video="fn_ZWTr0Tb8", caution=ANONYMOUS),
    Stream("source-global", "Middle East multi-cam (Source Global News)", "Source Global News", "Israel, Iran…, as titled",
           "cam", video="jC8_C4yGHas", caution=ANONYMOUS),
    Stream("osint-collective", "Iran–Israel multi-cam (OSINT Collective)", "OSINT Collective", "Iran, Israel, as titled",
           "cam", video="j_IhDFlxjho", caution=ANONYMOUS),
    Stream("nypan", "Middle East & Ukraine multi-cam (Nypan)", "Nypan", "the Middle East and Russia/Ukraine, as titled",
           "cam", video="MXuHTFXbA6Q", caution=ANONYMOUS),
)
CHANNELS = (  # listed
    Stream("pbc", "Palestine TV", "Palestinian Broadcasting Corporation", "Ramallah, West Bank · Palestinian Authority",
           "news", channel="UC1xAKR0vwwrHeorDesok6vw"),
    Stream("aljazeera-ar", "Al Jazeera Arabic", "Al Jazeera Media Network", "Doha · Qatar state-funded", "news",
           channel="UCfiwzLy-8yKzIbsmZTzxDgw"),
    Stream("aljazeera-en", "Al Jazeera English", "Al Jazeera Media Network", "Doha · Qatar state-funded", "news",
           channel="UCNye-wNBqNL5ZzHSJj3l8Bg"),
    Stream("i24-fr", "i24NEWS (French)", "i24NEWS", "Jaffa, Israel · private", "news", channel="UCgPYsPyGhhQJQ9zOUQDWDMA"),
    Stream("alaraby", "Al Araby TV News", "Fadaat Media", "London · Qatari-backed", "news", channel="UC65i3Fyq91uiUkIS0i5GLNQ"),
    Stream("alarabiya", "Al Arabiya", "MBC Group", "Dubai · Saudi-owned", "news", channel="UCahpxixMCwoANAftn6IxkTg"),
    Stream("alhadath", "Al Hadath", "MBC Group", "Dubai · Saudi-owned", "news", channel="UCrj5BGAhtWxDfqbza9T9hqA"),
    Stream("skynews-arabia", "Sky News Arabia", "Sky News Arabia", "Abu Dhabi · UAE-owned", "news",
           channel="UCIJXOvggjKtCagMfxvcCzAA"),
    Stream("alqahera", "AlQahera News", "United Media Services", "Cairo · Egyptian state-linked", "news",
           channel="UCktyejXTxWaKfrgp1Oq7CMQ"),
    Stream("trt-world", "TRT World", "Turkish Radio and Television", "Istanbul · Turkish state", "news",
           channel="UC7fWeaHhqgM4Ry-RMpM2YYw"),
    Stream("trt-arabi", "TRT Arabi", "Turkish Radio and Television", "Istanbul · Turkish state", "news",
           channel="UC5GvVahlgulCyo4cshSmbcg"),
    Stream("iran-intl", "Iran International", "Volant Media", "London · Persian-language, opposed to Tehran's government",
           "news", channel="UCat6bC0Wrqq9Bcq7EkH_yQw"),
    Stream("france24-ar", "France 24 Arabic", "France Médias Monde", "Paris · French state", "news",
           channel="UCdTyuXgmJkG_O8_75eqej-w"),
    # Not verified: local stations in the West Bank, and a Cairo channel covering Gaza.
    Stream("hala-bethlehem", "Hala Bethlehem TV", "Hala Bethlehem TV", "Bethlehem, West Bank", "news",
           channel="UC-Fu4-zkUT7eEr6r-qXghLQ", caution=LOCAL),
    Stream("shabab-nablus", "Shabab TV (Nablus)", "Shabab FM Radio and TV", "Nablus, West Bank", "news",
           channel="UC7xfj-jkzSbL6GWd5Y3Btig", caution=LOCAL),
    Stream("alghad", "Al Ghad", "Alghad Extra", "Cairo, covering Gaza", "news", channel="UCJxL0pXBwT0uodwUx9U2Fvg",
           caution=LOCAL),
)


def _checked_list(videos: tuple[Stream, ...], channels: tuple[Stream, ...]) -> tuple[tuple[Stream, ...], tuple[Stream, ...]]:
    if not all(s.checked for s in videos) or any(s.checked for s in channels):
        raise ValueError("the checked list holds fixed videos, the listed one channels")
    every = videos + channels
    for attr in ("key", "video", "channel"):
        values = [getattr(s, attr) for s in every if getattr(s, attr)]
        if len(values) != len(set(values)):
            raise ValueError(f"two streams share a {attr}")
    return videos, channels


def _item(stream: Stream, at: datetime, *, source: str, note: str, basis: str) -> Item:
    parts = [f"{stream.owner} · {stream.home}.", stream.caution, note]
    return make_item(
        channel="world",
        source=source,
        native_id=stream.key,
        happened_at=at,  # a live stream has no moment: when it was last checked (videos) or listed (channels)
        fetched_at=at,
        title=stream.name,
        url=stream.watch_url,
        summary=" ".join(p for p in parts if p),
        lat=stream.lat,
        lon=stream.lon,
        severity=stream.severity,
        licence=LICENCE,
        basis=basis,
        raw={"key": stream.key, "video": stream.video, "channel": stream.channel},
        lang="en",
    )


def parse_cam(data: object, fetched_at: datetime, cams: tuple[Stream, ...] = VIDEOS) -> list:
    """One oEmbed answer: which listed video it is (by the thumbnail's video id) and YouTube's title for it."""
    if not isinstance(data, dict) or data.get("provider_name") != "YouTube":
        raise ParseError(f"{CAMS_SOURCE}: not YouTube's oEmbed")
    found = THUMB_ID.match(str(data.get("thumbnail_url") or ""))
    stream = next((s for s in cams if found and s.video == found.group(1)), None)
    if stream is None:
        raise ParseError(f"{CAMS_SOURCE}: an answer for a video that is not on the list")
    title = str(data.get("title") or "")
    note = f"On YouTube: {title}." if title else ""
    return [partial(_item, stream, fetched_at, source=CAMS_SOURCE, note=note, basis="reported")]


def check_urls(_last_ok: datetime | None, _now: datetime, cams: tuple[Stream, ...] = VIDEOS) -> list[str]:
    return [s.check_url for s in cams]


def list_news(_store: object, now: datetime, news: tuple[Stream, ...] = CHANNELS) -> list[Item]:
    return [_item(s, now, source=NEWS_SOURCE, note=NOT_CHECKED, basis="inferred") for s in news]


VIDEOS, CHANNELS = _checked_list(VIDEOS, CHANNELS)

CAMS_COLLECTOR = Collector(
    source=CAMS_SOURCE,
    channel="world",
    url=VIDEOS[0].check_url,
    url_for=check_urls,
    follow_optional=True,  # one cam gone or its embedding turned off: skipped, the rest still count
    each_optional=True,  # the first one too: the run fails only when no video answers
    interval_s=6 * 60 * 60,
    licence=LICENCE,
    parse_records=parse_cam,
    layer=Layer(id="live-cams", en="Live cams (Middle East)", es="Cámaras en vivo (Medio Oriente)",
                window=WINDOW, limit=100),
    panel=Panel(id="live-cams", en="Middle East live cams", es="Cámaras en vivo, Medio Oriente", window=WINDOW, limit=100),
)

NEWS_COLLECTOR = Collector(
    source=NEWS_SOURCE,
    channel="world",
    url="",  # nothing is fetched
    interval_s=6 * 60 * 60,
    licence=LICENCE,
    parse_records=lambda data, fetched_at: [],
    derive=list_news,
    panel=Panel(id="live-news", en="Middle East live news", es="Noticias en vivo, Medio Oriente", window=WINDOW, limit=100),
)

COLLECTORS = (CAMS_COLLECTOR, NEWS_COLLECTOR)
