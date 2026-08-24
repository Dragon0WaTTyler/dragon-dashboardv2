from __future__ import annotations

import gzip
import html
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import BinaryIO
from urllib.parse import urljoin

import requests
from defusedxml import ElementTree
from flask import Flask, current_app
from sqlalchemy import delete, func, select

from app.extensions import db
from app.services.streaming import validate_stream_url
from app.shared.time import utc_now

from .cache import query_cache
from .models import TVChannelPreference, TVEPGState, TVProgramme

EPG_REFRESH_MINUTES = 360
EPG_WINDOW_HOURS = 48
EPG_STALE_HOURS = 12
EPG_FAILURE_RETRY_MINUTES = 30
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MIN_DUPLICATE_SCHEDULE_SLOTS = 4


@dataclass(frozen=True, slots=True)
class EPGSource:
    name: str
    url: str
    countries: frozenset[str] = frozenset()
    kind: str = "xmltv"
    match_by_name: bool = True


@dataclass(frozen=True, slots=True)
class FavoriteChannel:
    tvg_id: str
    name: str


@dataclass(frozen=True, slots=True)
class ParsedProgramme:
    tvg_id: str
    title: str
    subtitle: str
    description: str
    starts_at: datetime
    ends_at: datetime
    source: str


DEFAULT_SOURCES = (
    EPGSource(
        "EPGshare Arabia",
        "https://epgshare01.online/epgshare01/epg_ripper_AE1.xml.gz",
        frozenset({"ae", "qa", "sa"}),
        match_by_name=False,
    ),
    EPGSource(
        "EPGshare Belgium",
        "https://epgshare01.online/epgshare01/epg_ripper_BE2.xml.gz",
        frozenset({"be"}),
        match_by_name=False,
    ),
    EPGSource(
        "EPGshare Czechia",
        "https://epgshare01.online/epgshare01/epg_ripper_CZ1.xml.gz",
        frozenset({"cz", "czechia"}),
        match_by_name=False,
    ),
    EPGSource(
        "EPGshare United Kingdom",
        "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
        frozenset({"uk"}),
        match_by_name=False,
    ),
    EPGSource(
        "EPGshare United States",
        "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
        frozenset({"us"}),
        match_by_name=False,
    ),
    EPGSource(
        "EPGshare Germany",
        "https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz",
        frozenset({"de", "dach"}),
        match_by_name=False,
    ),
    EPGSource(
        "Plex guide", "https://i.mjh.nz/Plex/us.xml", frozenset({"plex.us"})
    ),
    EPGSource(
        "Pluto TV Germany guide",
        "https://i.mjh.nz/PlutoTV/de.xml",
        frozenset({"plutotv.de"}),
    ),
    EPGSource(
        "Samsung TV Plus guide",
        "https://i.mjh.nz/SamsungTVPlus/us.xml",
        frozenset({"samsungtvplus.us"}),
    ),
    EPGSource(
        "Samsung TV Plus United Kingdom guide",
        "https://i.mjh.nz/SamsungTVPlus/gb.xml",
        frozenset({"samsungtvplus.gb"}),
    ),
    EPGSource(
        "Pluto TV United Kingdom guide",
        "https://i.mjh.nz/PlutoTV/gb.xml",
        frozenset({"plutotv.gb"}),
    ),
    EPGSource(
        "Pluto TV United States guide",
        "https://i.mjh.nz/PlutoTV/us.xml",
        frozenset({"plutotv.us"}),
    ),
    # These providers expose an authoritative JSON schedule rather than a
    # public XMLTV file.  They are intentionally narrow: only IDs that have
    # been verified against the provider are requested below.
    EPGSource("Distro TV guide", "", frozenset({"distro.tv"}), "distro"),
    EPGSource("MTS guide", "", frozenset({"mts.rs"}), "mts"),
)

DISTRO_CHANNEL_IDS = {
    "discoveringchina@distro.tv": "143733",
}
MTS_CHANNEL_IDS = {
    "rtdocumentary@mts.rs": "rt_documentary",
}
DISTRO_HEADERS = {
    "User-Agent": "Dragon-EPG/1.0",
    "Referer": "https://distro.tv/",
    "Origin": "https://distro.tv",
}

_QUALITY_TOKENS = {
    "1080p",
    "1080i",
    "720p",
    "576p",
    "4k",
    "fhd",
    "uhd",
    "hd",
    "sd",
    "east",
    "west",
    "hdeast",
    "hdwest",
    "geo",
    "blocked",
}
_REGION_TOKENS = {"cz", "czech", "czechia", "dach"}
# Some aggregators use a provider suffix such as ``.us2``. It still denotes
# the country source family and should select the US guide.
_COUNTRY_RE = re.compile(r"\.([a-z]{2})(?:\d+)?(?:@|$)", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


class EPGSyncError(RuntimeError):
    pass


def _coverage_for_channels(
    programmes: Iterable[ParsedProgramme | TVProgramme],
    channels: Iterable[FavoriteChannel],
    *,
    now: datetime,
) -> dict[str, dict[str, object]]:
    """Describe whether each channel has a usable present and future guide."""

    by_channel: dict[str, list[ParsedProgramme | TVProgramme]] = {}
    for programme in programmes:
        by_channel.setdefault(programme.tvg_id, []).append(programme)

    result: dict[str, dict[str, object]] = {}
    for channel in channels:
        rows = by_channel.get(channel.tvg_id, [])
        if not rows:
            result[channel.tvg_id] = {
                "state": "missing",
                "programme_count": 0,
                "coverage_hours": 0,
                "first_program_start": None,
                "last_program_stop": None,
                "downloaded_at": None,
                "source": "",
            }
            continue

        starts = [_aware(row.starts_at) for row in rows]
        stops = [_aware(row.ends_at) for row in rows]
        fetched = [_aware(row.fetched_at) for row in rows if hasattr(row, "fetched_at")]
        active = any(start <= now < stop for start, stop in zip(starts, stops, strict=True))
        last_stop = max(stops)
        coverage_hours = max(0, round((last_stop - now).total_seconds() / 3600, 1))
        state = "healthy" if active and coverage_hours >= 24 else "degraded" if active else "stale"
        result[channel.tvg_id] = {
            "state": state,
            "programme_count": len(rows),
            "coverage_hours": coverage_hours,
            "first_program_start": min(starts),
            "last_program_stop": last_stop,
            "downloaded_at": max(fetched) if fetched else None,
            "source": str(rows[0].source),
        }
    return result


def _ambiguous_schedule_ids(
    programmes: Iterable[ParsedProgramme | TVProgramme],
) -> set[str]:
    """Find distinct channels that a provider gave the exact same schedule."""

    schedules: dict[tuple[str, str], list[tuple[datetime, datetime, str]]] = {}
    for programme in programmes:
        key = (programme.tvg_id, programme.source.casefold())
        schedules.setdefault(key, []).append(
            (
                programme.starts_at,
                programme.ends_at,
                programme.title.casefold(),
            )
        )

    fingerprints: dict[
        tuple[str, tuple[tuple[datetime, datetime, str], ...]], set[str]
    ] = {}
    for (tvg_id, source), slots in schedules.items():
        if len(slots) < MIN_DUPLICATE_SCHEDULE_SLOTS:
            continue
        fingerprint = (source, tuple(sorted(slots)))
        fingerprints.setdefault(fingerprint, set()).add(tvg_id)

    ambiguous: set[str] = set()
    for tvg_ids in fingerprints.values():
        families = {tvg_id.split("@", 1)[0].casefold() for tvg_id in tvg_ids}
        if len(families) > 1:
            ambiguous.update(tvg_ids)
    return ambiguous


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _text(element, tag: str) -> str:
    child = element.find(tag)
    return _SPACE_RE.sub(" ", "".join(child.itertext())).strip() if child is not None else ""


def _normalise_label(value: str) -> str:
    cleaned = html.unescape(value).casefold()
    cleaned = re.sub(r"\[[^]]+]", " ", cleaned)
    cleaned = re.sub(r"\((?:[^)]*?(?:\d{3,4}[pi]|geo.?blocked)[^)]*)\)", " ", cleaned)
    cleaned = cleaned.replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", cleaned)
    tokens = [
        token
        for token in tokens
        if token not in _QUALITY_TOKENS and token not in _REGION_TOKENS
    ]
    if tokens[:1] == ["the"]:
        tokens = tokens[1:]
    return " ".join(tokens)


def _favorite_aliases(channel: FavoriteChannel) -> set[str]:
    base_id = channel.tvg_id.split("@", 1)[0]
    id_without_country = re.sub(r"\.[a-z]{2}$", "", base_id, flags=re.IGNORECASE)
    return {
        alias
        for alias in {
            _normalise_label(channel.name),
            _normalise_label(base_id.replace(".", " ")),
            _normalise_label(id_without_country.replace(".", " ")),
        }
        if alias
    }


def _xmltv_datetime(value: str) -> datetime:
    candidate = value.strip()
    match = re.match(r"^(\d{12}(?:\d{2})?)\s*([+-]\d{4}|Z)?", candidate)
    if not match:
        raise ValueError(f"Invalid XMLTV date: {value!r}")
    digits, offset = match.groups()
    if len(digits) == 12:
        digits += "00"
    parsed = datetime.strptime(digits, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if not offset or offset == "Z":
        return parsed
    sign = 1 if offset[0] == "+" else -1
    delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
    return (parsed - sign * delta).astimezone(timezone.utc)


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _build_alias_map(favorites: list[FavoriteChannel]) -> dict[str, FavoriteChannel | None]:
    aliases: dict[str, FavoriteChannel | None] = {}
    for favorite in favorites:
        for alias in _favorite_aliases(favorite):
            aliases[alias] = favorite if alias not in aliases else None
    return aliases


def parse_xmltv(
    stream: BinaryIO,
    favorites: list[FavoriteChannel],
    *,
    source: str,
    now: datetime | None = None,
    match_by_name: bool = True,
) -> tuple[list[ParsedProgramme], set[str]]:
    """Stream an XMLTV document and retain only a favorite channel's useful window."""

    current_time = now or utc_now()
    lower_bound = current_time - timedelta(hours=6)
    upper_bound = current_time + timedelta(hours=EPG_WINDOW_HOURS)
    exact_ids = {favorite.tvg_id.casefold(): favorite for favorite in favorites}
    base_ids = {favorite.tvg_id.split("@", 1)[0].casefold(): favorite for favorite in favorites}
    aliases = _build_alias_map(favorites)
    channel_map: dict[str, FavoriteChannel] = {}
    programmes: list[ParsedProgramme] = []

    for _event, element in ElementTree.iterparse(stream, events=("end",)):
        tag = _local_tag(element.tag)
        if tag == "channel":
            source_id = str(element.attrib.get("id") or "").strip()
            favorite = exact_ids.get(source_id.casefold()) or base_ids.get(source_id.casefold())
            if favorite is None and match_by_name:
                labels = [source_id]
                labels.extend(
                    _SPACE_RE.sub(" ", "".join(child.itertext())).strip()
                    for child in list(element)
                    if _local_tag(child.tag) == "display-name"
                )
                for label in labels:
                    candidate = aliases.get(_normalise_label(label))
                    if candidate is not None:
                        favorite = candidate
                        break
            if favorite is not None and source_id:
                channel_map[source_id] = favorite
            element.clear()
        elif tag == "programme":
            favorite = channel_map.get(str(element.attrib.get("channel") or ""))
            if favorite is not None:
                try:
                    starts_at = _xmltv_datetime(str(element.attrib.get("start") or ""))
                    ends_at = _xmltv_datetime(str(element.attrib.get("stop") or ""))
                except ValueError:
                    element.clear()
                    continue
                if ends_at >= lower_bound and starts_at <= upper_bound:
                    title = _text(element, "title") or "Untitled programme"
                    programmes.append(
                        ParsedProgramme(
                            tvg_id=favorite.tvg_id,
                            title=title[:600],
                            subtitle=_text(element, "sub-title")[:600],
                            description=_text(element, "desc")[:4000],
                            starts_at=starts_at,
                            ends_at=ends_at,
                            source=source[:500],
                        )
                    )
            element.clear()

    return programmes, {favorite.tvg_id for favorite in channel_map.values()}


def _parse_iso_datetime(value: object) -> datetime:
    """Parse the ISO-8601 timestamps returned by a live guide provider."""

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _aware(parsed) or parsed.replace(tzinfo=timezone.utc)


def _provider_json(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    params: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    """Fetch a fixed, public provider endpoint without accepting redirects."""

    validate_stream_url(url)
    response = session.get(
        url,
        params=params,
        headers=headers,
        allow_redirects=False,
        timeout=(timeout, max(60, timeout * 6)),
    )
    try:
        if response.status_code != 200:
            raise EPGSyncError(f"Live guide returned HTTP {response.status_code}.")
        payload = response.json()
    finally:
        response.close()
    if not isinstance(payload, dict):
        raise EPGSyncError("Live guide returned an invalid response.")
    return payload


def _distro_programmes(
    session: requests.Session,
    favorites: list[FavoriteChannel],
    *,
    source: str,
    now: datetime,
    timeout: int,
) -> tuple[list[ParsedProgramme], set[str]]:
    programmes: list[ParsedProgramme] = []
    matched: set[str] = set()
    for favorite in favorites:
        channel_id = DISTRO_CHANNEL_IDS.get(favorite.tvg_id.casefold())
        if not channel_id:
            continue
        matched.add(favorite.tvg_id)
        payload = _provider_json(
            session,
            "https://tv.jsrdn.com/epg/query.php",
            timeout=timeout,
            params={"range": "now,48h", "id": f"{channel_id},"},
            headers=DISTRO_HEADERS,
        )
        epg = payload.get("epg")
        slots = epg.get(channel_id, {}).get("slots", []) if isinstance(epg, dict) else []
        if not isinstance(slots, list):
            continue
        for item in slots:
            if not isinstance(item, dict):
                continue
            try:
                starts_at = datetime.strptime(
                    str(item.get("start") or ""), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                ends_at = datetime.strptime(
                    str(item.get("end") or ""), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if (
                ends_at < now - timedelta(hours=6)
                or starts_at > now + timedelta(hours=EPG_WINDOW_HOURS)
            ):
                continue
            title = str(item.get("title") or "").strip()
            if title:
                programmes.append(
                    ParsedProgramme(
                        tvg_id=favorite.tvg_id,
                        title=title[:600],
                        subtitle="",
                        description=str(item.get("description") or "")[:4000],
                        starts_at=starts_at,
                        ends_at=ends_at,
                        source=source,
                    )
                )
    return programmes, matched


def _mts_programmes(
    session: requests.Session,
    favorites: list[FavoriteChannel],
    *,
    source: str,
    now: datetime,
    timeout: int,
) -> tuple[list[ParsedProgramme], set[str]]:
    programmes: list[ParsedProgramme] = []
    matched: set[str] = set()
    endpoint = "https://mts.rs/hybris/ecommerce/b2c/v1/products/search"
    for favorite in favorites:
        channel_id = MTS_CHANNEL_IDS.get(favorite.tvg_id.casefold())
        if not channel_id:
            continue
        matched.add(favorite.tvg_id)
        # MTS's guide begins at 02:00 UTC. Include yesterday so the current
        # slot is not falsely marked stale during the early-morning gap.
        for offset in (-1, 0, 1):
            day = (now + timedelta(days=offset)).date().isoformat()
            payload = _provider_json(
                session,
                endpoint,
                timeout=timeout,
                params={
                    "sort": "pozicija-rastuce",
                    "searchQueryContext": "CHANNEL_PROGRAM",
                    "query": (
                        ":pozicija-rastuce:tip-kanala-radio:TV kanali:"
                        f"channelProgramDates:{day}:code:{channel_id}"
                    ),
                    "pageSize": 50,
                },
            )
            products = payload.get("products")
            if not isinstance(products, list):
                continue
            for product in products:
                if not isinstance(product, dict) or product.get("code") != channel_id:
                    continue
                entries = product.get("programs")
                if not isinstance(entries, list):
                    continue
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    try:
                        starts_at = _parse_iso_datetime(item.get("start"))
                        ends_at = _parse_iso_datetime(item.get("end"))
                    except (TypeError, ValueError):
                        continue
                    if (
                        ends_at < now - timedelta(hours=6)
                        or starts_at > now + timedelta(hours=EPG_WINDOW_HOURS)
                    ):
                        continue
                    title = str(item.get("title") or "").strip()
                    if title:
                        programmes.append(
                            ParsedProgramme(
                                tvg_id=favorite.tvg_id,
                                title=title[:600],
                                subtitle="",
                                description=str(item.get("description") or "")[:4000],
                                starts_at=starts_at,
                                ends_at=ends_at,
                                source=source,
                            )
                        )
    return programmes, matched


def _provider_programmes(
    session: requests.Session,
    source: EPGSource,
    favorites: list[FavoriteChannel],
    *,
    now: datetime,
    timeout: int,
) -> tuple[list[ParsedProgramme], set[str]]:
    if source.kind == "distro":
        return _distro_programmes(
            session, favorites, source=source.name, now=now, timeout=timeout
        )
    if source.kind == "mts":
        return _mts_programmes(session, favorites, source=source.name, now=now, timeout=timeout)
    raise EPGSyncError(f"Unknown live guide provider: {source.name}.")


def _selected_sources(favorites: list[FavoriteChannel]) -> tuple[EPGSource, ...]:
    configured = str(current_app.config.get("DRAGON_TV_EPG_URLS") or "").strip()
    if configured:
        urls = [item.strip() for item in re.split(r"[,\n]", configured) if item.strip()]
        return tuple(EPGSource(f"Custom guide {index}", url) for index, url in enumerate(urls, 1))

    countries = {
        match.group(1).casefold()
        for favorite in favorites
        if (match := _COUNTRY_RE.search(favorite.tvg_id))
    }
    feeds = {
        favorite.tvg_id.split("@", 1)[1].casefold()
        for favorite in favorites
        if "@" in favorite.tvg_id
    }
    favorite_ids = " ".join(favorite.tvg_id.casefold() for favorite in favorites)
    selected = [
        source
        for source in DEFAULT_SOURCES
        if source.countries.intersection(countries | feeds)
        or (source.name == "Plex guide" and "plex" in favorite_ids)
        or (source.name.startswith("Pluto TV") and "plutotv" in favorite_ids)
        or (source.name.startswith("Samsung TV Plus") and "samsungtvplus" in favorite_ids)
    ]
    return tuple(selected)


def _favorites_for_source(
    source: EPGSource, favorites: list[FavoriteChannel]
) -> list[FavoriteChannel]:
    """Keep same-named Pluto regional feeds from competing for one alias."""

    pluto_regions = {
        "Pluto TV Germany guide": {"dach", "de"},
        "Pluto TV United Kingdom guide": {"gb", "uk"},
        "Pluto TV United States guide": {"us"},
    }
    regions = pluto_regions.get(source.name)
    if regions is None:
        return favorites
    return [
        favorite
        for favorite in favorites
        if "plutotv" in favorite.tvg_id.casefold()
        and any(favorite.tvg_id.casefold().endswith(f"@{region}") for region in regions)
    ]


def _public_response(session: requests.Session, url: str, *, timeout: int):
    current_url = url
    for _ in range(4):
        validate_stream_url(current_url)
        response = session.get(
            current_url,
            stream=True,
            allow_redirects=False,
            timeout=(timeout, max(60, timeout * 6)),
            headers={"User-Agent": "Dragon-EPG/1.0", "Accept-Encoding": "identity"},
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise EPGSyncError("The guide redirected without a destination.")
        current_url = urljoin(current_url, location)
    raise EPGSyncError("The guide redirected too many times.")


class EPGSyncService:
    def __init__(self, session: requests.Session | None = None, timeout_seconds: int = 20):
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def favorites(tvg_ids: set[str] | None = None) -> list[FavoriteChannel]:
        statement = (
            select(TVChannelPreference)
            .where(
                TVChannelPreference.favorite.is_(True),
                TVChannelPreference.tvg_id != "",
            )
            .order_by(TVChannelPreference.name)
        )
        if tvg_ids is not None:
            statement = statement.where(TVChannelPreference.tvg_id.in_(tvg_ids))
        return [
            FavoriteChannel(tvg_id=row.tvg_id.strip(), name=row.name)
            for row in db.session.scalars(statement)
            if row.tvg_id.strip()
        ]

    @staticmethod
    def is_due(*, refresh_minutes: int | None = None) -> bool:
        if not current_app.config.get("DRAGON_TV_EPG_ENABLED", True):
            return False
        if not db.session.scalar(
            select(TVChannelPreference.preference_key).where(
                TVChannelPreference.favorite.is_(True), TVChannelPreference.tvg_id != ""
            )
        ):
            return False
        state = db.session.get(TVEPGState, 1)
        last_success = _aware(state.last_success_at) if state else None
        last_attempt = _aware(state.last_attempt_at) if state else None
        if (
            state is not None
            and state.status == "error"
            and last_attempt is not None
            and utc_now() - last_attempt < timedelta(minutes=EPG_FAILURE_RETRY_MINUTES)
        ):
            return False
        interval = refresh_minutes or int(
            current_app.config.get("DRAGON_TV_EPG_REFRESH_MINUTES", EPG_REFRESH_MINUTES)
        )
        return last_success is None or utc_now() - last_success >= timedelta(minutes=interval)

    def sync(self, *, tvg_ids: set[str] | None = None) -> dict[str, int | str]:
        favorites = self.favorites(tvg_ids)
        targeted = tvg_ids is not None
        now = utc_now()
        state = db.session.get(TVEPGState, 1) or TVEPGState(id=1)
        db.session.add(state)
        state.status = "running"
        state.message = "Refreshing favorite channel schedules…"
        state.last_attempt_at = utc_now()
        state.last_error = ""
        db.session.commit()

        if not favorites:
            if not targeted:
                db.session.execute(delete(TVProgramme))
                state.status = "idle"
                state.message = "Favorite a channel to load its schedule."
                state.matched_channels = 0
                state.programme_count = 0
                state.source_count = 0
            else:
                state.status = "ready"
                state.message = "Schedules unchanged."
            db.session.commit()
            query_cache.invalidate()
            return {"favorites": 0, "matched": 0, "programmes": 0, "sources": 0}

        sources = _selected_sources(favorites)
        unique_programmes: dict[tuple[str, datetime, str], ParsedProgramme] = {}
        matched: set[str] = set()
        successful_sources = 0
        errors: list[str] = []

        for source in sources:
            source_error: Exception | None = None
            source_favorites = _favorites_for_source(source, favorites)
            if not source_favorites:
                continue
            for _attempt in range(2):
                response = None
                try:
                    if source.kind == "xmltv":
                        response = _public_response(
                            self.session, source.url, timeout=self.timeout_seconds
                        )
                        if response.status_code != 200:
                            raise EPGSyncError(
                                f"{source.name} returned HTTP {response.status_code}."
                            )
                        length = int(response.headers.get("Content-Length") or 0)
                        if length > MAX_SOURCE_BYTES:
                            raise EPGSyncError(f"{source.name} exceeds the guide size limit.")
                        raw = response.raw
                        raw.decode_content = False
                        stream = (
                            gzip.GzipFile(fileobj=raw)
                            if source.url.endswith(".gz")
                            else raw
                        )
                        parsed, source_matches = parse_xmltv(
                            stream,
                            source_favorites,
                            source=source.name,
                            now=now,
                            match_by_name=source.match_by_name,
                        )
                    else:
                        parsed, source_matches = _provider_programmes(
                            self.session,
                            source,
                            source_favorites,
                            now=now,
                            timeout=self.timeout_seconds,
                        )
                    successful_sources += 1
                    coverage = _coverage_for_channels(
                        parsed,
                        [
                            favorite
                            for favorite in source_favorites
                            if favorite.tvg_id in source_matches
                        ],
                        now=now,
                    )
                    stale_ids = {
                        tvg_id
                        for tvg_id, details in coverage.items()
                        # A recognised channel without a current programme is
                        # just as unsafe as one whose last programme expired.
                        if details["state"] in {"stale", "missing"}
                    }
                    if stale_ids:
                        errors.append(
                            f"{source.name}: rejected stale schedules for "
                            f"{len(stale_ids)} channel(s)."
                        )
                    matched.update(source_matches - stale_ids)
                    for programme in parsed:
                        if programme.tvg_id in stale_ids:
                            continue
                        key = (
                            programme.tvg_id,
                            programme.starts_at,
                            programme.title.casefold(),
                        )
                        unique_programmes.setdefault(key, programme)
                    source_error = None
                    break
                except Exception as error:  # retry truncated provider responses once
                    source_error = error
                finally:
                    if response is not None:
                        response.close()
            if source_error is not None:  # providers remain independent best-effort sources
                errors.append(f"{source.name}: {str(source_error)[:180]}")

        if successful_sources == 0:
            state.status = "error"
            state.message = "Schedule refresh failed; showing the last saved guide."
            state.last_error = "; ".join(errors)[:500]
            db.session.commit()
            raise EPGSyncError(state.last_error or state.message)

        rejected_ids = _ambiguous_schedule_ids(unique_programmes.values())
        if rejected_ids:
            unique_programmes = {
                key: programme
                for key, programme in unique_programmes.items()
                if programme.tvg_id not in rejected_ids
            }
            matched.difference_update(rejected_ids)
            errors.append(
                "Guide quality check ignored duplicated schedules for "
                f"{len(rejected_ids)} channels."
            )

        favorite_ids = {favorite.tvg_id for favorite in favorites}
        updated_ids = {programme.tvg_id for programme in unique_programmes.values()}
        if targeted:
            db.session.execute(delete(TVProgramme).where(TVProgramme.ends_at < now))
        else:
            db.session.execute(
                delete(TVProgramme).where(
                    (TVProgramme.tvg_id.not_in(favorite_ids))
                    | (TVProgramme.ends_at < now)
                )
            )
        if rejected_ids:
            db.session.execute(
                delete(TVProgramme).where(TVProgramme.tvg_id.in_(rejected_ids))
            )
        if updated_ids:
            db.session.execute(delete(TVProgramme).where(TVProgramme.tvg_id.in_(updated_ids)))
            db.session.add_all(
                TVProgramme(
                    tvg_id=item.tvg_id,
                    title=item.title,
                    subtitle=item.subtitle,
                    description=item.description,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    source=item.source,
                    fetched_at=now,
                )
                for item in unique_programmes.values()
            )

        all_favorite_ids = set(
            db.session.scalars(
                select(TVChannelPreference.tvg_id).where(
                    TVChannelPreference.favorite.is_(True),
                    TVChannelPreference.tvg_id != "",
                )
            )
        )
        matched_channels = int(
            db.session.scalar(
                select(func.count(func.distinct(TVProgramme.tvg_id))).where(
                    TVProgramme.tvg_id.in_(all_favorite_ids), TVProgramme.ends_at > now
                )
            )
            or 0
        )
        programme_count = int(
            db.session.scalar(
                select(func.count(TVProgramme.id)).where(TVProgramme.ends_at > now)
            )
            or 0
        )
        state.status = "partial" if errors or matched_channels < len(all_favorite_ids) else "ready"
        state.message = (
            f"Schedules ready for {matched_channels} of "
            f"{len(all_favorite_ids)} favorite channels."
        )
        state.last_error = "; ".join(errors)[:500]
        if not targeted:
            state.last_success_at = now
        state.matched_channels = matched_channels
        state.programme_count = programme_count
        if not targeted:
            state.source_count = successful_sources
        db.session.commit()
        query_cache.invalidate()
        return {
            "favorites": len(favorites),
            "matched": len(matched),
            "programmes": len(unique_programmes),
            "sources": successful_sources,
            "status": state.status,
        }


def status_payload() -> dict[str, object]:
    state = db.session.get(TVEPGState, 1)
    running = epg_coordinator.status().get("state") == "running"
    if state is None:
        return {
            "state": "running" if running else "idle",
            "message": "Favorite a channel to load its schedule.",
            "stale": False,
            "last_success_at": None,
            "matched_channels": 0,
            "programme_count": 0,
            "source_count": 0,
            "audit": {"summary": {}, "channels": []},
        }
    last_success = _aware(state.last_success_at)
    favorites = EPGSyncService.favorites()
    rows = list(
        db.session.scalars(
            select(TVProgramme).where(
                TVProgramme.tvg_id.in_([favorite.tvg_id for favorite in favorites])
            )
        )
    ) if favorites else []
    coverage = _coverage_for_channels(rows, favorites, now=utc_now())
    channels = [
        {
            "channel_id": favorite.tvg_id,
            "name": favorite.name,
            "state": details["state"],
            "source": details["source"],
            "downloaded_at": details["downloaded_at"].isoformat()
            if details["downloaded_at"] else None,
            "first_program_start": details["first_program_start"].isoformat()
            if details["first_program_start"] else None,
            "last_program_stop": details["last_program_stop"].isoformat()
            if details["last_program_stop"] else None,
            "programme_count": details["programme_count"],
            "coverage_hours": details["coverage_hours"],
        }
        for favorite, details in ((favorite, coverage[favorite.tvg_id]) for favorite in favorites)
    ]
    summary = {
        state_name: sum(channel["state"] == state_name for channel in channels)
        for state_name in ("healthy", "degraded", "stale", "missing")
    }
    return {
        "state": "running" if running else state.status,
        "message": state.message,
        "error": state.last_error,
        "stale": bool(
            last_success is not None
            and utc_now() - last_success >= timedelta(hours=EPG_STALE_HOURS)
        ),
        "last_success_at": last_success.isoformat() if last_success else None,
        "matched_channels": state.matched_channels,
        "programme_count": state.programme_count,
        "source_count": state.source_count,
        "audit": {"summary": summary, "channels": channels},
    }


def now_next_for_ids(tvg_ids: set[str], *, now: datetime | None = None) -> dict[str, dict]:
    if not tvg_ids:
        return {}
    current_time = now or utc_now()
    favorite_ids = set(
        db.session.scalars(
            select(TVChannelPreference.tvg_id).where(
                TVChannelPreference.favorite.is_(True),
                TVChannelPreference.tvg_id != "",
            )
        )
    )
    rows = list(
        db.session.scalars(
            select(TVProgramme)
            .where(
                TVProgramme.tvg_id.in_(favorite_ids | tvg_ids),
                TVProgramme.ends_at > current_time,
                TVProgramme.starts_at < current_time + timedelta(hours=EPG_WINDOW_HOURS),
            )
            .order_by(TVProgramme.tvg_id, TVProgramme.starts_at)
        )
    )
    ambiguous_ids = _ambiguous_schedule_ids(rows)
    result: dict[str, dict] = {}
    for programme in rows:
        if programme.tvg_id not in tvg_ids or programme.tvg_id in ambiguous_ids:
            continue
        slot = result.setdefault(programme.tvg_id, {"now": None, "next": None})
        payload = {
            "title": programme.title,
            "subtitle": programme.subtitle,
            "starts_at": _aware(programme.starts_at).isoformat(),
            "ends_at": _aware(programme.ends_at).isoformat(),
        }
        starts_at = _aware(programme.starts_at)
        ends_at = _aware(programme.ends_at)
        if starts_at <= current_time < ends_at and slot["now"] is None:
            slot["now"] = payload
        elif starts_at > current_time and slot["next"] is None:
            slot["next"] = payload
    return result


class EPGSyncCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, object] = {"state": "idle", "message": ""}

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)

    def start(
        self,
        app: Flask,
        *,
        force: bool = False,
        tvg_ids: set[str] | None = None,
    ) -> bool:
        with self._lock:
            if self._state.get("state") == "running":
                return False
            self._state = {"state": "running", "message": "Refreshing schedules…"}

        def worker() -> None:
            try:
                with app.app_context():
                    if force or EPGSyncService.is_due():
                        result = EPGSyncService().sync(tvg_ids=tvg_ids)
                        message = f"Loaded {result['programmes']} programme slots."
                    else:
                        message = "Schedules are already current."
                final = {"state": "complete", "message": message}
            except Exception as error:
                final = {"state": "error", "message": str(error)}
            with self._lock:
                self._state = final

        threading.Thread(target=worker, daemon=True, name="dragon-tv-epg").start()
        return True


epg_coordinator = EPGSyncCoordinator()
