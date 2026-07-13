from scripts.check_tracked_secrets import SECRET_PATTERN


def test_secret_pattern_does_not_cross_lines():
    example = "DRAGON_SECRET_KEY=\nDRAGON_EXTERNAL_SYNC_ENABLED=false\n"
    assert SECRET_PATTERN.search(example) is None
    assert SECRET_PATTERN.search("DRAGON_SECRET_KEY=not-a-real-secret\n") is not None
