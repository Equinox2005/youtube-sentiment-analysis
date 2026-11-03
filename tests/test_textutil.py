from app.analysis import timestamp_heatmap
from app.textutil import format_timestamp, month_of, normalize_summary, timestamp_seconds, tokens
from app.youtube import Comment


def test_timestamp_seconds_reads_minutes_and_hours():
    assert timestamp_seconds("the bit at 4:12 and again at 1:02:03") == [252, 3723]


def test_timestamp_seconds_ignores_impossible_times():
    assert timestamp_seconds("score was 10:75, not a timestamp") == []


def test_format_timestamp_round_trips():
    assert format_timestamp(252) == "4:12"
    assert format_timestamp(3723) == "1:02:03"


def test_normalize_summary_collapses_case_space_and_trailing_punctuation():
    assert normalize_summary("  Grinder  matters more. ") == normalize_summary("grinder matters more")


def test_normalize_summary_keeps_word_order():
    # "A over B" and "B over A" are opposite findings and must not merge.
    assert normalize_summary("prefers manual over automatic") != normalize_summary(
        "prefers automatic over manual"
    )


def test_tokens_drop_stopwords_and_short_words():
    assert tokens("I really want a video on the grinder and the burr") == ["grinder", "burr"]


def test_month_of():
    assert month_of("2026-04-12T09:00:00Z") == "2026-04"
    assert month_of("") == ""


def test_timestamp_heatmap_groups_nearby_mentions():
    comments = [
        Comment(text="4:12 is the moment", likes=5),
        Comment(text="that crema at 4:12", likes=3),
        Comment(text="4:20 too", likes=1),
        Comment(text="18:06 wait what", likes=9),  # mentioned once, so dropped
    ]
    moments = timestamp_heatmap(comments)
    assert len(moments) == 1
    assert moments[0]["timestamp"] == "4:12"  # the most-cited second, not the bucket edge
    assert moments[0]["count"] == 3
    assert moments[0]["likes"] == 9
