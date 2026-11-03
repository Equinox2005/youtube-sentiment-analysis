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
    ],
)
def test_parse_channel_ref(ref, expected):
    assert parse_channel_ref(ref) == expected


def test_parse_channel_ref_rejects_garbage():
    with pytest.raises(YouTubeError):
        parse_channel_ref("not a channel!")


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
