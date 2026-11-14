import pytest

from app.schemas import MapResult, ReduceResult, strict_schema
from app.youtube import YouTubeError, estimate_quota, extract_video_id, parse_channel_ref


@pytest.mark.parametrize(
    "text",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "  dQw4w9WgXcQ  ",
    ],
)
def test_extract_video_id(text):
    assert extract_video_id(text) == "dQw4w9WgXcQ"


def test_extract_video_id_rejects_garbage():
    with pytest.raises(YouTubeError):
        extract_video_id("https://example.com/not-a-video")


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("UCabcdefghijklmnopqrstuv", ("id", "UCabcdefghijklmnopqrstuv")),
        ("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv", ("id", "UCabcdefghijklmnopqrstuv")),
        ("@coffeebench", ("handle", "coffeebench")),
        ("https://www.youtube.com/@coffeebench/videos", ("handle", "coffeebench")),
        ("https://www.youtube.com/c/CoffeeBench", ("handle", "CoffeeBench")),
        ("@café_bench", ("handle", "café_bench")),
        ("@カフェチャンネル", ("handle", "カフェチャンネル")),
        ("https://www.youtube.com/@%E3%82%AB%E3%83%95%E3%82%A7/videos", ("handle", "カフェ")),
        ("@UCSanDiegoHealthSciences", ("handle", "UCSanDiegoHealthSciences")),
        ("@नमस्ते", ("handle", "नमस्ते")),
        ("@cafébench", ("handle", "cafébench")),
        ("https://www.youtube.com/@coffeebench?si=abc", ("handle", "coffeebench")),
    ],
)
def test_parse_channel_ref(ref, expected):
    assert parse_channel_ref(ref) == expected


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("(@coffeebench)", "coffeebench"),
        ("@coffeebench.", "coffeebench"),
        ("@coffeebench!", "coffeebench"),
        ("@coffeebench?", "coffeebench"),
        ("(@coffee.bench).", "coffee.bench"),
        ("@coffee-bench!", "coffee-bench"),
        ("(@カフェチャンネル)", "カフェチャンネル"),
        ("@" + "a" * 30 + ".", "a" * 30),
    ],
)
def test_parse_channel_ref_drops_punctuation_after_a_handle(ref, expected):
    assert parse_channel_ref(ref) == ("handle", expected)


@pytest.mark.parametrize("handle", ["a" * 31, "ab"])
def test_a_handle_of_impossible_length_in_a_url_is_refused(handle):
    with pytest.raises(YouTubeError):
        parse_channel_ref(f"https://www.youtube.com/@{handle}/videos")


def test_a_comma_after_a_handle_goes_when_the_list_is_split():
    from app.main import _split_channels

    refs = _split_channels("(@coffeebench), @teatable.")
    assert [parse_channel_ref(ref) for ref in refs] == [("handle", "coffeebench"), ("handle", "teatable")]


def test_parse_channel_ref_refuses_a_handle_too_long_to_exist():
    with pytest.raises(YouTubeError):
        parse_channel_ref("@" + "a" * 31)


def test_parse_channel_ref_rejects_garbage():
    with pytest.raises(YouTubeError):
        parse_channel_ref("not a channel!")


@pytest.mark.parametrize(
    "ref",
    [
        "@channel1 @channel2",
        "@channel1;@channel2",
        "@channel1,@channel2",
        "https://youtube.com/@one https://youtube.com/@two",
        "The Coffee Bench",
    ],
)
def test_parse_channel_ref_refuses_several_channels_at_once(ref):
    with pytest.raises(YouTubeError, match="separate channels"):
        parse_channel_ref(ref)


def test_estimate_quota_for_a_twelve_channel_study():
    result = estimate_quota(channels=12, videos_per_channel=8, comments_per_video=500)
    assert result["breakdown"] == {
        "channels.list": 12,
        "playlistItems.list": 12,
        "videos.list": 2,
        "commentThreads.list": 480,
    }
    assert result["estimated_units"] == 506
    assert result["studies_per_day"] == 19


@pytest.mark.parametrize("model", [MapResult, ReduceResult])
def test_strict_schema_meets_structured_output_rules(model):
    def walk(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for banned in ("default", "minLength", "maxLength", "minimum", "maximum"):
                assert banned not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(strict_schema(model))
