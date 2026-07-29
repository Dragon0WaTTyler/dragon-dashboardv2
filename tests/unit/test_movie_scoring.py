from app.movies.scoring import notion_score_options, score_option_for_input, score_option_for_value


def test_score_options_follow_notion_order():
    options = notion_score_options(["god mode", "masterpiece", "good"])

    assert [option.label for option in options] == ["god mode", "masterpiece", "good"]
    assert [option.value for option in options] == [5.0, 4.5, 4.0]


def test_score_input_maps_notion_labels_and_legacy_values():
    labels = [
        "god mode",
        "close to god mode",
        "masterpiece",
        "Sweet",
        "good",
        "acceptable",
        "naah",
        "i don't like it",
    ]

    assert score_option_for_input("masterpiece", labels=labels).value == 4.0
    assert score_option_for_value(7.0, labels=labels).label == "masterpiece"
    assert score_option_for_input(2.5, labels=labels).label == "acceptable"
