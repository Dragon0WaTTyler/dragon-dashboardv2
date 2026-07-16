from app.mytv.services import ChannelEntry, classify_stream, parse_m3u, smart_theme


def test_mytv_parser_reads_metadata_and_stream_type():
    channels = list(
        parse_m3u(
            [
                "\ufeff#EXTM3U",
                '#EXTINF:-1 tvg-id="news.ma" tvg-name="News HD" '
                'tvg-logo="https://img.example/logo.png" group-title="Morocco",News HD',
                "https://stream.example/live/index.m3u8",
            ]
        )
    )
    assert len(channels) == 1
    assert channels[0].name == "News HD"
    assert channels[0].group == "Morocco"
    assert channels[0].kind == "hls"


def test_mytv_channel_key_survives_expiring_url_changes():
    first = ChannelEntry("Channel", "Group", "https://one.example/token/1.ts")
    second = ChannelEntry("Channel", "Group", "https://two.example/new-token/1.ts")
    assert first.external_key == second.external_key


def test_mytv_parser_ignores_orphans_and_classifies_formats():
    assert list(parse_m3u(["https://orphan.example/stream.ts"])) == []
    assert classify_stream("https://a.example/live.m3u8?token=x") == "hls"
    assert classify_stream("https://a.example/movie.mp4") == "file"
    assert classify_stream("https://a.example/live/1.ts") == "transport"
    assert classify_stream("https://a.example/live/1") == "stream"


def test_mytv_smart_theme_merges_equivalent_cross_package_bouquets():
    assert smart_theme("ARAB | MOROCCO").key == smart_theme("Morocco").key
    assert smart_theme("DE | DEUTSCHLAND").key == smart_theme("Germany").key
    assert smart_theme("VOD Germany").key != smart_theme("Germany").key


def test_mytv_channel_preference_key_survives_file_and_name_changes():
    first = ChannelEntry(
        "News HD", "Morocco", "https://one.example/live", tvg_id="ma.news"
    )
    replacement = ChannelEntry(
        "News HD New", "ARAB | MOROCCO", "https://two.example/live", tvg_id="ma.news"
    )
    assert first.preference_key("morocco") == replacement.preference_key("morocco")
