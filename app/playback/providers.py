from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.playback.identity import PlaybackIdentity


@dataclass(frozen=True, slots=True)
class IndexedEmbedProviderSpec:
    """Static provider metadata; it never enables or authorizes a provider."""

    key: str
    display_name: str
    aliases: frozenset[str]
    allowed_domains: frozenset[str]
    asset_id_pattern: str
    default_embed_url_template: str
    default_priority: int


# These are provider identification and rendering rules only. A provider still
# requires its own local, authorized template and enabled preference to play.
INDEXED_EMBED_PROVIDER_SPECS = (
    IndexedEmbedProviderSpec(
        key="videotube",
        display_name="VideoTube",
        aliases=frozenset(),
        allowed_domains=frozenset({"vidtube.one", "down.vidtube.one"}),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://down.vidtube.one/embed-{asset_id}.html",
        default_priority=10,
    ),
    IndexedEmbedProviderSpec(
        key="updown",
        display_name="UpDown",
        aliases=frozenset(),
        allowed_domains=frozenset({"updown.cam", "updown.sbs", "updown.icu"}),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://updown.icu/embed-{asset_id}-1280x640.html",
        default_priority=20,
    ),
    IndexedEmbedProviderSpec(
        key="streamwish",
        display_name="StreamWish",
        aliases=frozenset(),
        allowed_domains=frozenset(
            {
                "streamwish.com", "streamwish.to", "awish.pro", "embedwish.com",
                "wishembed.pro", "dwish.pro", "wishonly.site", "cloudwish.xyz",
                "jwplayerhls.com",
            }
        ),
        asset_id_pattern=r"^[a-z0-9]{12}$",
        default_embed_url_template="https://streamwish.com/e/{asset_id}",
        default_priority=30,
    ),
    IndexedEmbedProviderSpec(
        key="doodstream",
        display_name="DoodStream",
        aliases=frozenset(),
        allowed_domains=frozenset(
            {
                "doodstream.com", "dood.to", "dood.re", "dood.wf", "dood.pm", "dood.yt",
                "dood.sh", "dood.so", "dood.la", "dood.cx", "dood.watch", "dooood.com",
            }
        ),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://dood.to/e/{asset_id}",
        default_priority=40,
    ),
    IndexedEmbedProviderSpec(
        key="filelions",
        display_name="FileLions / EarnVids",
        aliases=frozenset(),
        allowed_domains=frozenset(
            {
                "filelions.com", "filelions.to", "filelions.co", "filelions.live",
                "filelions.xyz", "filelions.online", "filelions.site", "fviplions.com",
                "mlions.pro", "alions.pro", "dlions.pro", "vidhide.com", "vidhidepro.com",
                "vidhidevip.com", "vidhideplus.com", "vidhidefast.com", "earnvids.xyz",
            }
        ),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://filelions.to/v/{asset_id}",
        default_priority=50,
    ),
    IndexedEmbedProviderSpec(
        key="ok",
        display_name="OK.ru",
        aliases=frozenset({"okru"}),
        allowed_domains=frozenset({"ok.ru", "odnoklassniki.ru"}),
        asset_id_pattern=r"^[0-9-]{1,300}$",
        default_embed_url_template="https://ok.ru/videoembed/{asset_id}",
        default_priority=60,
    ),
    IndexedEmbedProviderSpec(
        key="streamtape",
        display_name="StreamTape",
        aliases=frozenset(),
        allowed_domains=frozenset(
            {
                "streamtape.com", "streamtape.net", "streamta.pe", "streamtape.site",
                "streamtape.cc", "streamtape.to", "streamtape.xyz", "strtape.cloud",
                "strcloud.link", "strcloud.club", "strtpe.link", "scloud.online", "stape.fun",
            }
        ),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://streamtape.com/e/{asset_id}",
        default_priority=70,
    ),
    IndexedEmbedProviderSpec(
        key="lulustream",
        display_name="LuluStream",
        aliases=frozenset(),
        allowed_domains=frozenset(
            {"lulustream.com", "luluvid.com", "lulu.st", "lulu0.ovh", "luluvdoo.com", "cdn1.site"}
        ),
        asset_id_pattern=r"^[a-z0-9]{12}$",
        default_embed_url_template="https://lulustream.com/e/{asset_id}",
        default_priority=80,
    ),
)
INDEXED_EMBED_PROVIDER_BY_KEY = {spec.key: spec for spec in INDEXED_EMBED_PROVIDER_SPECS}
INDEXED_EMBED_PROVIDER_ALIAS_KEYS = {
    alias: spec.key for spec in INDEXED_EMBED_PROVIDER_SPECS for alias in spec.aliases
}


def indexed_embed_provider_spec(key: str) -> IndexedEmbedProviderSpec | None:
    normalized_key = str(key or "").strip().lower()
    canonical_key = INDEXED_EMBED_PROVIDER_ALIAS_KEYS.get(normalized_key, normalized_key)
    return INDEXED_EMBED_PROVIDER_BY_KEY.get(canonical_key)


def canonical_indexed_embed_provider_key(key: str) -> str | None:
    spec = indexed_embed_provider_spec(key)
    return spec.key if spec else None


def catalog_provider_for_host(host: str) -> str | None:
    normalized_host = host.strip().lower().rstrip(".")
    for spec in INDEXED_EMBED_PROVIDER_SPECS:
        if normalized_host in spec.allowed_domains:
            return spec.key
    return None


def catalog_asset_id_from_url(provider_key: str, url: str) -> str | None:
    """Extract only an asset ID from the canonical path shape for a provider."""
    spec = indexed_embed_provider_spec(provider_key)
    if spec is None:
        return None
    template_path = urlsplit(spec.default_embed_url_template).path
    prefix, suffix = template_path.split("{asset_id}", maxsplit=1)
    pattern_body = spec.asset_id_pattern.removeprefix("^").removesuffix("$")
    match = re.fullmatch(
        f"{re.escape(prefix)}(?P<asset_id>{pattern_body}){re.escape(suffix)}",
        urlsplit(url).path,
    )
    return match.group("asset_id") if match else None


@dataclass(frozen=True, slots=True)
class ResolvedPlayback:
    provider: str
    label: str
    url: str
    provider_asset_id: str
    source_type: str
    playback_mode: str
    match: str
    sandbox: str = ""

    def response_item(self) -> dict[str, str]:
        item = {
            "provider": self.provider,
            "label": self.label,
            "url": self.url,
            "match": self.match,
        }
        if self.sandbox:
            item["sandbox"] = self.sandbox
        return item


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    status: str
    probe_level: str = ""
    failure_reason: str = ""
    latency_ms: int | None = None


class PlaybackProvider(Protocol):
    key: str

    def resolve(self, identity: PlaybackIdentity, *, source=None) -> ResolvedPlayback: ...

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult: ...


class ProviderRegistry:
    def __init__(self, providers: tuple[PlaybackProvider, ...] = ()) -> None:
        self._providers = {provider.key: provider for provider in providers}

    def get(self, key: str) -> PlaybackProvider | None:
        return self._providers.get(key)

    def require(self, key: str) -> PlaybackProvider:
        provider = self.get(key)
        if provider is None:
            raise ValueError(f"Playback provider is not registered: {key}")
        return provider

    def keys(self) -> frozenset[str]:
        return frozenset(self._providers)


class VidSrcProvider:
    key = "vidsrc"

    def __init__(self, *, base_url: str) -> None:
        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        try:
            port = parsed.port
        except ValueError:
            port = None
            invalid_port = True
        else:
            invalid_port = False
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or invalid_port
            or port == 0
        ):
            raise ValueError("VidSrc must use a plain HTTPS embed base URL.")
        self.base_url = normalized

    def resolve(self, identity: PlaybackIdentity, *, source=None) -> ResolvedPlayback:
        match, provider_asset_id = identity.provider_id()
        if identity.is_tv:
            if identity.season is None or identity.episode is None:
                raise ValueError("TV playback requires a season and an episode.")
            url = f"{self.base_url}/tv/{provider_asset_id}/{identity.season}-{identity.episode}"
        else:
            url = f"{self.base_url}/{provider_asset_id}"
        return ResolvedPlayback(
            provider=self.key,
            label="VidSrc",
            url=url,
            provider_asset_id=provider_asset_id,
            source_type="id_catalog",
            playback_mode="embed",
            match=match,
        )

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        # V0 deliberately performs no third-party request before the user asks to watch.
        self.resolve(identity)
        return ProviderProbeResult(status="UNKNOWN")


def _validated_embed_url_template(value: str, *, display_name: str) -> tuple[str, object]:
    normalized = str(value or "").strip()
    if normalized.count("{asset_id}") != 1:
        raise ValueError(
            f"{display_name} embed URL template must contain exactly one {{asset_id}} placeholder."
        )
    if "{" in normalized.replace("{asset_id}", "") or "}" in normalized.replace(
        "{asset_id}", ""
    ):
        raise ValueError(f"{display_name} embed URL template has an unsupported placeholder.")
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError:
        port = None
        invalid_port = True
    else:
        invalid_port = False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or invalid_port
        or port == 0
    ):
        raise ValueError(f"{display_name} must use a plain HTTPS embed URL template.")
    return normalized, parsed


def validate_indexed_embed_url_template(provider_key: str, value: str) -> str:
    """Validate a local template against the canonical provider allowlist."""
    spec = indexed_embed_provider_spec(provider_key)
    if spec is None:
        raise ValueError("Playback provider is not supported.")
    normalized, parsed = _validated_embed_url_template(value, display_name=spec.display_name)
    if parsed.hostname not in spec.allowed_domains:
        raise ValueError(f"{spec.display_name} embed template domain is not allowlisted.")
    return normalized


@dataclass(frozen=True, slots=True)
class IndexedEmbedProviderConfig:
    key: str
    embed_url_template: str
    sandbox: str = "allow-scripts allow-forms allow-popups allow-presentation"


class IndexedEmbedProvider:
    """A provider with authorized, Dragon-owned source mappings only."""

    def __init__(self, config: IndexedEmbedProviderConfig) -> None:
        spec = indexed_embed_provider_spec(config.key)
        if spec is None or spec.key != config.key:
            raise ValueError("Indexed embed provider must use a canonical provider key.")
        self.key = spec.key
        self.config = config
        self.display_name = spec.display_name
        self.embed_url_template = validate_indexed_embed_url_template(
            spec.key, config.embed_url_template
        )
        self._asset_id_pattern = re.compile(spec.asset_id_pattern)

    def resolve(self, identity: PlaybackIdentity, *, source=None) -> ResolvedPlayback:
        if source is None:
            raise ValueError(f"{self.display_name} requires an indexed source mapping.")
        asset_id = str(getattr(source, "provider_asset_id", "") or "").strip()
        if not self._asset_id_pattern.fullmatch(asset_id):
            raise ValueError(f"{self.display_name} source asset ID is invalid.")
        return ResolvedPlayback(
            provider=self.key,
            label=self.display_name,
            url=self.embed_url_template.replace("{asset_id}", asset_id),
            provider_asset_id=asset_id,
            source_type="known_embed",
            playback_mode="embed",
            match="indexed",
            sandbox=self.config.sandbox,
        )

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        if source is not None:
            self.resolve(identity, source=source)
        return ProviderProbeResult(status="UNKNOWN")


def build_provider_registry(
    *,
    vidsrc_embed_url: str,
    videotube_enabled: bool = False,
    videotube_embed_url: str = "",
    updown_enabled: bool = False,
    updown_embed_url: str = "",
    streamwish_enabled: bool = False,
    streamwish_embed_url: str = "",
    doodstream_enabled: bool = False,
    doodstream_embed_url: str = "",
    filelions_enabled: bool = False,
    filelions_embed_url: str = "",
    ok_enabled: bool = False,
    ok_embed_url: str = "",
    streamtape_enabled: bool = False,
    streamtape_embed_url: str = "",
    lulustream_enabled: bool = False,
    lulustream_embed_url: str = "",
) -> ProviderRegistry:
    providers: list[PlaybackProvider] = [VidSrcProvider(base_url=vidsrc_embed_url)]
    provider_options = {
        "videotube": (videotube_enabled, videotube_embed_url),
        "updown": (updown_enabled, updown_embed_url),
        "streamwish": (streamwish_enabled, streamwish_embed_url),
        "doodstream": (doodstream_enabled, doodstream_embed_url),
        "filelions": (filelions_enabled, filelions_embed_url),
        "ok": (ok_enabled, ok_embed_url),
        "streamtape": (streamtape_enabled, streamtape_embed_url),
        "lulustream": (lulustream_enabled, lulustream_embed_url),
    }
    for spec in INDEXED_EMBED_PROVIDER_SPECS:
        enabled, embed_url = provider_options[spec.key]
        if not enabled:
            continue
        if not embed_url:
            raise ValueError(
                f"{spec.display_name} embed URL template is required "
                f"when {spec.display_name} is enabled."
            )
        providers.append(
            IndexedEmbedProvider(
                IndexedEmbedProviderConfig(
                    key=spec.key,
                    embed_url_template=embed_url,
                )
            )
        )
    return ProviderRegistry(tuple(providers))


def build_provider_registry_from_config(config) -> ProviderRegistry:
    options = {"vidsrc_embed_url": str(config["DRAGON_VIDSRC_EMBED_URL"])}
    for spec in INDEXED_EMBED_PROVIDER_SPECS:
        config_key = spec.key.upper()
        options[f"{spec.key}_enabled"] = bool(
            config.get(f"DRAGON_{config_key}_ENABLED", False)
        )
        options[f"{spec.key}_embed_url"] = str(config.get(f"DRAGON_{config_key}_EMBED_URL", ""))
    return build_provider_registry(**options)
