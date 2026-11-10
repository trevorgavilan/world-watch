"""Middle East live — official live cams and regional news channels, each on its owner's own YouTube channel.

The list is curated here (WORLD WATCH SOURCES § 2 holds who runs each and the terms); nothing is
discovered by scraping — YouTube's terms bar automated access to its pages. Two sources:
- `mideast-cams`: cams with a fixed video id, checked every few hours through YouTube's published
  oEmbed endpoint (https://www.youtube.com/oembed?format=json&url=…) — 200 while the video exists and
  its owner allows embedding; 401 (embedding off) or 404 (gone) skip it, and it leaves the viewer once
  its last good check is 2 days old. Each cam has its place: pins on the map.
- `mideast-news`: news channels, played as the channel's current live stream, so a restarted stream
  needs no new id. They are listed, not checked: YouTube's channel feeds (the one keyless way to ask
  about a channel) answered 404/500 to most requests on 2026-11-09, and the player itself shows
  when a channel is off-air. Their items say so ("inferred").
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
NOT_CHECKED = "Listed, not checked: the player shows if the channel is off-air."


@dataclass(frozen=True)
class Stream:
    key: str
    name: str
    owner: str
    home: str  # where it is, or where the broadcaster is based and who backs it
    video: str | None = None  # a cam: a fixed live video, checked by oEmbed
    channel: str | None = None  # a news channel: its current live stream
    lat: float | None = None
    lon: float | None = None

    def __post_init__(self) -> None:
        if (self.video is None) == (self.channel is None):
            raise ValueError(f"{self.key}: one of video or channel")
        if self.video is not None and not VIDEO_ID.fullmatch(self.video):
            raise ValueError(f"{self.key}: not a video id")
        if self.channel is not None and not CHANNEL_ID.fullmatch(self.channel):
            raise ValueError(f"{self.key}: not a channel id")
        if (self.video is not None) != (self.lat is not None and self.lon is not None):
            raise ValueError(f"{self.key}: a cam has a place, a news channel has none")

    @property
    def is_cam(self) -> bool:
        return self.video is not None

    @property
    def check_url(self) -> str:
        return OEMBED + quote(f"https://www.youtube.com/watch?v={self.video}", safe="")

    @property
    def watch_url(self) -> str:
        if self.video:
            return f"https://www.youtube.com/watch?v={self.video}"
        return f"https://www.youtube.com/channel/{self.channel}/live"


KOTEL = (31.77670, 35.23450)  # the Western Wall plaza, Jerusalem
WWHF = "Western Wall Heritage Foundation"
CAMS = (
    Stream("kotel-main", "Western Wall 1 · Main Plaza", WWHF, "Jerusalem", video="LMHUcDktP-w", lat=KOTEL[0], lon=KOTEL[1]),
    Stream("kotel-2", "Western Wall 2", WWHF, "Jerusalem", video="gJsZdfSyPrM", lat=KOTEL[0], lon=KOTEL[1]),
    Stream("kotel-3", "Western Wall 3", WWHF, "Jerusalem", video="Y3v2WGY-SDc", lat=KOTEL[0], lon=KOTEL[1]),
    Stream("earthcam-kotel", "Western Wall 4 · EarthCam", "EarthCam", "Jerusalem", video="77akujLn4k8",
           lat=KOTEL[0], lon=KOTEL[1]),
)
NEWS = (
    Stream("pbc", "Palestine TV", "Palestinian Broadcasting Corporation", "Ramallah, West Bank · Palestinian Authority",
           channel="UC1xAKR0vwwrHeorDesok6vw"),
    Stream("aljazeera-ar", "Al Jazeera Arabic", "Al Jazeera Media Network", "Doha · Qatar state-funded",
           channel="UCfiwzLy-8yKzIbsmZTzxDgw"),
    Stream("aljazeera-en", "Al Jazeera English", "Al Jazeera Media Network", "Doha · Qatar state-funded",
           channel="UCNye-wNBqNL5ZzHSJj3l8Bg"),
    Stream("i24-fr", "i24NEWS (French)", "i24NEWS", "Jaffa, Israel · private", channel="UCgPYsPyGhhQJQ9zOUQDWDMA"),
    Stream("alaraby", "Al Araby TV News", "Fadaat Media", "London · Qatari-backed", channel="UC65i3Fyq91uiUkIS0i5GLNQ"),
    Stream("alarabiya", "Al Arabiya", "MBC Group", "Dubai · Saudi-owned", channel="UCahpxixMCwoANAftn6IxkTg"),
    Stream("alhadath", "Al Hadath", "MBC Group", "Dubai · Saudi-owned", channel="UCrj5BGAhtWxDfqbza9T9hqA"),
    Stream("skynews-arabia", "Sky News Arabia", "Sky News Arabia", "Abu Dhabi · UAE-owned", channel="UCIJXOvggjKtCagMfxvcCzAA"),
    Stream("alqahera", "AlQahera News", "United Media Services", "Cairo · Egyptian state-linked",
           channel="UCktyejXTxWaKfrgp1Oq7CMQ"),
    Stream("trt-world", "TRT World", "Turkish Radio and Television", "Istanbul · Turkish state",
           channel="UC7fWeaHhqgM4Ry-RMpM2YYw"),
    Stream("trt-arabi", "TRT Arabi", "Turkish Radio and Television", "Istanbul · Turkish state",
           channel="UC5GvVahlgulCyo4cshSmbcg"),
    Stream("iran-intl", "Iran International", "Volant Media", "London · Persian-language, opposed to Tehran's government",
           channel="UCat6bC0Wrqq9Bcq7EkH_yQw"),
    Stream("france24-ar", "France 24 Arabic", "France Médias Monde", "Paris · French state", channel="UCdTyuXgmJkG_O8_75eqej-w"),
)


def _checked_list(cams: tuple[Stream, ...], news: tuple[Stream, ...]) -> tuple[tuple[Stream, ...], tuple[Stream, ...]]:
    if not all(s.is_cam for s in cams) or any(s.is_cam for s in news):
        raise ValueError("cams have a video id, news channels a channel id")
    every = cams + news
    for attr in ("key", "video", "channel"):
        values = [getattr(s, attr) for s in every if getattr(s, attr)]
        if len(values) != len(set(values)):
            raise ValueError(f"two streams share a {attr}")
    return cams, news


def _item(stream: Stream, at: datetime, *, source: str, note: str, basis: str) -> Item:
    return make_item(
        channel="world",
        source=source,
        native_id=stream.key,
        happened_at=at,  # a live stream has no moment: when it was last checked (cams) or listed (news)
        fetched_at=at,
        title=stream.name,
        url=stream.watch_url,
        summary=f"{stream.owner} · {stream.home}. {note}".strip(),
        lat=stream.lat,
        lon=stream.lon,
        severity="cam" if stream.is_cam else "news",
        licence=LICENCE,
        basis=basis,
        raw={"key": stream.key, "video": stream.video, "channel": stream.channel},
        lang="en",
    )


def parse_cam(data: object, fetched_at: datetime, cams: tuple[Stream, ...] = CAMS) -> list:
    """One oEmbed answer: which listed cam it is (by the thumbnail's video id) and YouTube's title for it."""
    if not isinstance(data, dict) or data.get("provider_name") != "YouTube":
        raise ParseError(f"{CAMS_SOURCE}: not YouTube's oEmbed")
    found = THUMB_ID.match(str(data.get("thumbnail_url") or ""))
    stream = next((s for s in cams if found and s.video == found.group(1)), None)
    if stream is None:
        raise ParseError(f"{CAMS_SOURCE}: an answer for a video that is not on the list")
    title = str(data.get("title") or "")
    note = f"On YouTube: {title}." if title else ""
    return [partial(_item, stream, fetched_at, source=CAMS_SOURCE, note=note, basis="reported")]


def check_urls(_last_ok: datetime | None, _now: datetime, cams: tuple[Stream, ...] = CAMS) -> list[str]:
    return [s.check_url for s in cams]


def list_news(_store: object, now: datetime, news: tuple[Stream, ...] = NEWS) -> list[Item]:
    return [_item(s, now, source=NEWS_SOURCE, note=NOT_CHECKED, basis="inferred") for s in news]


CAMS, NEWS = _checked_list(CAMS, NEWS)

CAMS_COLLECTOR = Collector(
    source=CAMS_SOURCE,
    channel="world",
    url=CAMS[0].check_url,
    url_for=check_urls,
    follow_optional=True,  # one cam gone or its embedding turned off: skipped, the rest still count
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
