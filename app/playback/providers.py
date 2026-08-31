from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.playback.identity import PlaybackIdentity

# This is the browser boundary for every indexed/authorized embed. Keep the
# token set deliberately small: a provider must work inside this boundary and
# cannot ask Dragon for popup or top-level navigation permissions.
SAFE_EMBED_SANDBOX = "allow-scripts allow-same-origin allow-forms allow-presentation"
SAFE_EMBED_SANDBOX_TOKENS = frozenset(SAFE_EMBED_SANDBOX.split())
FORBIDDEN_EMBED_SANDBOX_TOKENS = frozenset(
    {
        "allow-popups",
        "allow-popups-to-escape-sandbox",
        "allow-top-navigation",
        "allow-top-navigation-by-user-activation",
        "allow-top-navigation-to-custom-protocols",
    }
)


def validate_embed_sandbox(value: str, *, display_name: str = "Embed") -> str:
    """Return a canonical sandbox policy or reject an unsafe one."""
    tokens = str(value or "").split()
    if not tokens:
        return SAFE_EMBED_SANDBOX
    if FORBIDDEN_EMBED_SANDBOX_TOKENS.intersection(tokens):
        raise ValueError(f"{display_name} embed sandbox cannot allow popups or top navigation.")
    if set(tokens) != SAFE_EMBED_SANDBOX_TOKENS:
        raise ValueError(
            f"{display_name} embed sandbox must use the Dragon safe playback policy."
        )
    return SAFE_EMBED_SANDBOX


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Static capabilities used by source selection and playback UI."""

    supported_content: frozenset[str]
    supports_internal_servers: bool = False
    supports_fullscreen: bool = True
    supports_subtitles: bool | None = None
    supports_lifecycle_messages: bool = False
    supports_server_identity: bool = False
    supports_language_metadata: bool = False
    supports_quality_metadata: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "supported_content": sorted(self.supported_content),
            "supports_internal_servers": self.supports_internal_servers,
            "supports_fullscreen": self.supports_fullscreen,
            "supports_subtitles": self.supports_subtitles,
            "supports_lifecycle_messages": self.supports_lifecycle_messages,
            "supports_server_identity": self.supports_server_identity,
            "supports_language_metadata": self.supports_language_metadata,
            "supports_quality_metadata": self.supports_quality_metadata,
        }

    def sanitize_attempt_metadata(
        self,
        *,
        server_id: object = "",
        language: object = "",
        quality: object = "",
    ) -> dict[str, str]:
        """Keep only metadata covered by this provider's explicit contract."""
        return {
            "server_id": str(server_id or "").strip() if self.supports_server_identity else "",
            "language": str(language or "").strip() if self.supports_language_metadata else "",
            "quality": str(quality or "").strip() if self.supports_quality_metadata else "",
        }


SUPPORTED_EMBED_CONTENT = frozenset({"movie", "tv"})


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
    supports_internal_servers: bool = False
    supports_fullscreen: bool = True
    supports_subtitles: bool | None = None
    supports_lifecycle_messages: bool = False
    supports_server_identity: bool = False
    supports_language_metadata: bool = False
    supports_quality_metadata: bool = False


@dataclass(frozen=True, slots=True)
class IdCatalogEmbedProviderSpec:
    """An iframe provider that resolves canonical TMDb identity directly."""

    key: str
    display_name: str
    allowed_domains: frozenset[str]
    movie_url_template: str
    tv_url_template: str
    default_priority: int
    sandbox: str = SAFE_EMBED_SANDBOX
    supports_internal_servers: bool = False
    supports_fullscreen: bool = True
    supports_subtitles: bool | None = None
    supports_lifecycle_messages: bool = False
    supports_server_identity: bool = False
    supports_language_metadata: bool = False
    supports_quality_metadata: bool = False


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
        key="mixdrop",
        display_name="MixDrop",
        aliases=frozenset(),
        allowed_domains=frozenset({"mixdrop.ag"}),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://mixdrop.ag/e/{asset_id}",
        default_priority=35,
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
    IndexedEmbedProviderSpec(
        key="uqload",
        display_name="Uqload",
        aliases=frozenset(),
        allowed_domains=frozenset({"uqload.cx", "uqload.io", "uqload.com"}),
        asset_id_pattern=r"^[A-Za-z0-9_-]{1,300}$",
        default_embed_url_template="https://uqload.cx/embed-{asset_id}.html",
        default_priority=90,
    ),
)
ID_CATALOG_EMBED_PROVIDER_SPECS = (
    IdCatalogEmbedProviderSpec(
        key="vidlove",
        display_name="VidLove",
        allowed_domains=frozenset({"player.vidlove.cc"}),
        movie_url_template="https://player.vidlove.cc/embed/movie/{tmdb_id}",
        tv_url_template="https://player.vidlove.cc/embed/tv/{tmdb_id}/{season}/{episode}",
        default_priority=14,
        sandbox=SAFE_EMBED_SANDBOX,
        supports_internal_servers=True,
        supports_lifecycle_messages=True,
    ),
    IdCatalogEmbedProviderSpec(
        key="cinesrc",
        display_name="CineSrc",
        allowed_domains=frozenset({"cinesrc.st"}),
        movie_url_template="https://cinesrc.st/embed/movie/{tmdb_id}",
        tv_url_template="https://cinesrc.st/embed/tv/{tmdb_id}?s={season}&e={episode}",
        default_priority=15,
    ),
    IdCatalogEmbedProviderSpec(
        key="vidcore",
        display_name="VidCore",
        allowed_domains=frozenset({"vidcore.org", "www.vidcore.org"}),
        movie_url_template="https://vidcore.org/embed/movie/{tmdb_id}",
        tv_url_template="https://vidcore.org/embed/tv/{tmdb_id}/{season}/{episode}",
        default_priority=16,
    ),
    IdCatalogEmbedProviderSpec(
        key="vidzee",
        display_name="VidZee",
        allowed_domains=frozenset({"player.vidzee.wtf"}),
        movie_url_template="https://player.vidzee.wtf/embed/movie/{tmdb_id}",
        tv_url_template="https://player.vidzee.wtf/embed/tv/{tmdb_id}/{season}/{episode}",
        default_priority=17,
    ),
    IdCatalogEmbedProviderSpec(
        key="videm",
        display_name="VIDEM",
        allowed_domains=frozenset({"videm.xyz"}),
        movie_url_template="https://videm.xyz/embed/movie/{tmdb_id}",
        tv_url_template="https://videm.xyz/embed/tv/{tmdb_id}/{season}/{episode}",
        default_priority=18,
    ),
    IdCatalogEmbedProviderSpec(
        key="multiembed",
        display_name="MultiEmbed",
        allowed_domains=frozenset({"multiembed.mov"}),
        movie_url_template="https://multiembed.mov/?video_id={tmdb_id}&tmdb=1",
        tv_url_template="https://multiembed.mov/?video_id={tmdb_id}&tmdb=1&s={season}&e={episode}",
        default_priority=19,
    ),
    IdCatalogEmbedProviderSpec(
        key="multiembed_vip",
        display_name="MultiEmbed VIP",
        allowed_domains=frozenset({"multiembed.mov"}),
        movie_url_template="https://multiembed.mov/directstream.php?video_id={tmdb_id}&tmdb=1",
        tv_url_template="https://multiembed.mov/directstream.php?video_id={tmdb_id}&tmdb=1&s={season}&e={episode}",
        default_priority=20,
    ),
)
ID_CATALOG_EMBED_PROVIDER_BY_KEY = {spec.key: spec for spec in ID_CATALOG_EMBED_PROVIDER_SPECS}
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


def id_catalog_embed_provider_spec(key: str) -> IdCatalogEmbedProviderSpec | None:
    return ID_CATALOG_EMBED_PROVIDER_BY_KEY.get(str(key or "").strip().lower())


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
    sandbox: str = SAFE_EMBED_SANDBOX

    def __post_init__(self) -> None:
        # Keep the safety invariant at the resolved-playback boundary too;
        # callers cannot accidentally bypass provider constructor validation.
        object.__setattr__(
            self,
            "sandbox",
            validate_embed_sandbox(self.sandbox, display_name=self.label or "Embed"),
        )

    def response_item(self) -> dict[str, str]:
        item = {
            "provider": self.provider,
            "label": self.label,
            "url": self.url,
            "match": self.match,
        }
        item["sandbox"] = self.sandbox
        return item


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    status: str
    probe_level: str = ""
    failure_reason: str = ""
    latency_ms: int | None = None


class _PlaybackProviderContract:
    """Shared public contract for registered playback providers.

    ``resolve`` remains the compatibility-level implementation name used by
    older Dragon call sites.  ``build_embed`` is the provider-facing contract
    name from the playback architecture and deliberately delegates to it so
    both paths preserve the same identity, source, and server-preference
    boundary.
    """

    key: str
    capabilities: ProviderCapabilities

    @property
    def id(self) -> str:
        return self.key

    @property
    def supported_content(self) -> frozenset[str]:
        return self.capabilities.supported_content

    def build_embed(
        self,
        identity: PlaybackIdentity,
        *,
        source=None,
        preferred_server_id: str = "",
    ) -> ResolvedPlayback:
        return self.resolve(
            identity,
            source=source,
            preferred_server_id=preferred_server_id,
        )


class PlaybackProvider(Protocol):
    id: str
    key: str
    display_name: str
    sandbox: str
    supported_content: frozenset[str]
    capabilities: ProviderCapabilities

    def build_embed(
        self,
        identity: PlaybackIdentity,
        *,
        source=None,
        preferred_server_id: str = "",
    ) -> ResolvedPlayback: ...

    def resolve(
        self,
        identity: PlaybackIdentity,
        *,
        source=None,
        preferred_server_id: str = "",
    ) -> ResolvedPlayback: ...

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult: ...

    def health(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult: ...


class ProviderRegistry:
    def __init__(self, providers: tuple[PlaybackProvider, ...] = ()) -> None:
        self._providers = {provider.id: provider for provider in providers}

    def get(self, key: str) -> PlaybackProvider | None:
        return self._providers.get(key)

    def require(self, key: str) -> PlaybackProvider:
        provider = self.get(key)
        if provider is None:
            raise ValueError(f"Playback provider is not registered: {key}")
        return provider

    def keys(self) -> frozenset[str]:
        return frozenset(self._providers)

    def describe(self) -> tuple[dict[str, object], ...]:
        """Return static provider metadata without contacting any provider."""
        return tuple(
            {
                "id": provider.id,
                "display_name": provider.display_name,
                "capabilities": provider.capabilities.as_dict(),
            }
            for provider in self._providers.values()
        )


class VidSrcProvider(_PlaybackProviderContract):
    key = "vidsrc"
    display_name = "VidSrc"
    sandbox = SAFE_EMBED_SANDBOX
    capabilities = ProviderCapabilities(
        supported_content=SUPPORTED_EMBED_CONTENT,
        supports_fullscreen=True,
        supports_subtitles=None,
    )

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

    def resolve(
        self, identity: PlaybackIdentity, *, source=None, preferred_server_id: str = ""
    ) -> ResolvedPlayback:
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
            sandbox=SAFE_EMBED_SANDBOX,
        )

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        # V0 deliberately performs no third-party request before the user asks to watch.
        self.resolve(identity)
        return ProviderProbeResult(status="UNKNOWN")

    def health(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        return self.probe(identity, source=source)


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


def _validate_id_catalog_template(
    spec: IdCatalogEmbedProviderSpec, value: str, *, tv: bool
) -> str:
    required = {"{tmdb_id}"}
    if tv:
        required |= {"{season}", "{episode}"}
    normalized = str(value or "").strip()
    if any(normalized.count(placeholder) != 1 for placeholder in required):
        raise ValueError(f"{spec.display_name} identity template is invalid.")
    remainder = normalized
    for placeholder in required:
        remainder = remainder.replace(placeholder, "")
    if "{" in remainder or "}" in remainder:
        raise ValueError(f"{spec.display_name} identity template has an unsupported placeholder.")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname not in spec.allowed_domains
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError(f"{spec.display_name} identity template is not allowlisted.")
    return normalized


@dataclass(frozen=True, slots=True)
class IndexedEmbedProviderConfig:
    key: str
    embed_url_template: str
    sandbox: str = SAFE_EMBED_SANDBOX


class IndexedEmbedProvider(_PlaybackProviderContract):
    """A provider with authorized, Dragon-owned source mappings only."""

    def __init__(self, config: IndexedEmbedProviderConfig) -> None:
        spec = indexed_embed_provider_spec(config.key)
        if spec is None or spec.key != config.key:
            raise ValueError("Indexed embed provider must use a canonical provider key.")
        self.key = spec.key
        self.config = config
        self.display_name = spec.display_name
        self.capabilities = ProviderCapabilities(
            supported_content=SUPPORTED_EMBED_CONTENT,
            supports_internal_servers=spec.supports_internal_servers,
            supports_fullscreen=spec.supports_fullscreen,
            supports_subtitles=spec.supports_subtitles,
            supports_lifecycle_messages=spec.supports_lifecycle_messages,
            supports_server_identity=spec.supports_server_identity,
            supports_language_metadata=spec.supports_language_metadata,
            supports_quality_metadata=spec.supports_quality_metadata,
        )
        self.sandbox = validate_embed_sandbox(config.sandbox, display_name=self.display_name)
        self.embed_url_template = validate_indexed_embed_url_template(
            spec.key, config.embed_url_template
        )
        self._asset_id_pattern = re.compile(spec.asset_id_pattern)

    def resolve(
        self, identity: PlaybackIdentity, *, source=None, preferred_server_id: str = ""
    ) -> ResolvedPlayback:
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
            sandbox=self.sandbox,
        )

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        if source is not None:
            self.resolve(identity, source=source)
        return ProviderProbeResult(status="UNKNOWN")

    def health(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        return self.probe(identity, source=source)


class IdCatalogEmbedProvider(_PlaybackProviderContract):
    """Direct TMDb movie/episode iframe provider with no per-title mapping."""

    def __init__(self, key: str) -> None:
        spec = id_catalog_embed_provider_spec(key)
        if spec is None:
            raise ValueError("ID catalog provider is not supported.")
        self.key = spec.key
        self.display_name = spec.display_name
        self.capabilities = ProviderCapabilities(
            supported_content=SUPPORTED_EMBED_CONTENT,
            supports_internal_servers=spec.supports_internal_servers,
            supports_fullscreen=spec.supports_fullscreen,
            supports_subtitles=spec.supports_subtitles,
            supports_lifecycle_messages=spec.supports_lifecycle_messages,
            supports_server_identity=spec.supports_server_identity,
            supports_language_metadata=spec.supports_language_metadata,
            supports_quality_metadata=spec.supports_quality_metadata,
        )
        self.sandbox = validate_embed_sandbox(spec.sandbox, display_name=self.display_name)
        self._movie_template = _validate_id_catalog_template(
            spec, spec.movie_url_template, tv=False
        )
        self._tv_template = _validate_id_catalog_template(spec, spec.tv_url_template, tv=True)

    def resolve(
        self, identity: PlaybackIdentity, *, source=None, preferred_server_id: str = ""
    ) -> ResolvedPlayback:
        if not identity.tmdb_id:
            raise ValueError(f"{self.display_name} requires a TMDb ID.")
        if identity.is_tv:
            if identity.season is None or identity.episode is None:
                raise ValueError("TV playback requires a season and an episode.")
            url = self._tv_template.format(
                tmdb_id=identity.tmdb_id, season=identity.season, episode=identity.episode
            )
        else:
            url = self._movie_template.format(tmdb_id=identity.tmdb_id)
        return ResolvedPlayback(
            provider=self.key,
            label=self.display_name,
            url=url,
            provider_asset_id=identity.tmdb_id,
            source_type="id_catalog",
            playback_mode="embed",
            match="tmdb",
            sandbox=self.sandbox,
        )

    def probe(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        self.resolve(identity)
        return ProviderProbeResult(status="UNKNOWN")

    def health(self, identity: PlaybackIdentity, *, source=None) -> ProviderProbeResult:
        return self.probe(identity, source=source)


def build_provider_registry(
    *,
    vidsrc_embed_url: str,
    videotube_enabled: bool = False,
    videotube_embed_url: str = "",
    updown_enabled: bool = False,
    updown_embed_url: str = "",
    streamwish_enabled: bool = False,
    streamwish_embed_url: str = "",
    mixdrop_enabled: bool = False,
    mixdrop_embed_url: str = "",
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
    uqload_enabled: bool = False,
    uqload_embed_url: str = "",
    vidlove_enabled: bool = False,
    cinesrc_enabled: bool = False,
    vidcore_enabled: bool = False,
    vidzee_enabled: bool = False,
    videm_enabled: bool = False,
    multiembed_enabled: bool = False,
    multiembed_vip_enabled: bool = False,
) -> ProviderRegistry:
    providers: list[PlaybackProvider] = [VidSrcProvider(base_url=vidsrc_embed_url)]
    provider_options = {
        "videotube": (videotube_enabled, videotube_embed_url),
        "updown": (updown_enabled, updown_embed_url),
        "streamwish": (streamwish_enabled, streamwish_embed_url),
        "mixdrop": (mixdrop_enabled, mixdrop_embed_url),
        "doodstream": (doodstream_enabled, doodstream_embed_url),
        "filelions": (filelions_enabled, filelions_embed_url),
        "ok": (ok_enabled, ok_embed_url),
        "streamtape": (streamtape_enabled, streamtape_embed_url),
        "lulustream": (lulustream_enabled, lulustream_embed_url),
        "uqload": (uqload_enabled, uqload_embed_url),
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
    direct_provider_options = {
        "vidlove": vidlove_enabled,
        "cinesrc": cinesrc_enabled,
        "vidcore": vidcore_enabled,
        "vidzee": vidzee_enabled,
        "videm": videm_enabled,
        "multiembed": multiembed_enabled,
        "multiembed_vip": multiembed_vip_enabled,
    }
    providers.extend(
        IdCatalogEmbedProvider(spec.key)
        for spec in ID_CATALOG_EMBED_PROVIDER_SPECS
        if direct_provider_options[spec.key]
    )
    return ProviderRegistry(tuple(providers))


def build_provider_registry_from_config(config) -> ProviderRegistry:
    providers: list[PlaybackProvider] = [
        VidSrcProvider(base_url=str(config["DRAGON_VIDSRC_EMBED_URL"]))
    ]
    for spec in INDEXED_EMBED_PROVIDER_SPECS:
        config_key = spec.key.upper()
        if not config.get(f"DRAGON_{config_key}_ENABLED", False):
            continue
        template = str(config.get(f"DRAGON_{config_key}_EMBED_URL", ""))
        try:
            providers.append(
                IndexedEmbedProvider(
                    IndexedEmbedProviderConfig(
                        key=spec.key,
                        embed_url_template=template,
                    )
                )
            )
        except ValueError:
            # A stale or malformed optional provider must never take down the
            # selector or a separately configured provider. The local-only
            # activation report exposes this configuration failure.
            continue
    for spec in ID_CATALOG_EMBED_PROVIDER_SPECS:
        if config.get(f"DRAGON_{spec.key.upper()}_ENABLED", False):
            providers.append(IdCatalogEmbedProvider(spec.key))
    return ProviderRegistry(tuple(providers))
