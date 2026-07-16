from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse


ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')


@dataclass(slots=True)
class ChannelEntry:
    name: str
    group: str
    url: str
    tvg_id: str = ""
    tvg_name: str = ""
    logo_url: str = ""
    kind: str = "stream"

    @property
    def external_key(self) -> str:
        identity = "\x1f".join(
            (
                self.tvg_id.strip().casefold(),
                self.tvg_name.strip().casefold(),
                self.name.strip().casefold(),
                self.group.strip().casefold(),
            )
        )
        return hashlib.sha256(identity.encode("utf-8", "ignore")).hexdigest()


def classify_stream(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return "hls"
    if path.endswith((".mp4", ".webm", ".mov")):
        return "file"
    if path.endswith((".ts", ".mpegts")):
        return "transport"
    return "stream"


def parse_m3u(lines):
    pending: dict[str, str] | None = None

    for raw_line in lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8-sig", "replace")
        else:
            line = str(raw_line).lstrip("\ufeff")
        line = line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            attrs = {key.lower(): value.strip() for key, value in ATTRIBUTE_RE.findall(line)}
            name = line.rsplit(",", 1)[-1].strip() if "," in line else "Unknown channel"
            pending = {
                "name": name or attrs.get("tvg-name", "Unknown channel"),
                "group": attrs.get("group-title", "Ungrouped") or "Ungrouped",
                "tvg_id": attrs.get("tvg-id", ""),
                "tvg_name": attrs.get("tvg-name", ""),
                "logo_url": attrs.get("tvg-logo", ""),
            }
            continue

        if line.startswith("#"):
            continue

        if pending and line.lower().startswith(("http://", "https://")):
            yield ChannelEntry(
                **pending,
                url=line,
                kind=classify_stream(line),
            )
            pending = None
