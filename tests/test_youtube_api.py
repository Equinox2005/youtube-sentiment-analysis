"""The YouTube calls, run against canned HTTP replies instead of the network."""

import json

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from app import youtube
from app.niche import build_corpus
from app.youtube import QuotaMeter, YouTubeError, estimate_quota, fetch_comments, resolve_channels

KEY = "key-that-must-never-be-shown"
CHANNEL_ID = "UC" + "a" * 22


def _ok(body):
    return ({"status": "200"}, json.dumps(body))


def _error(status, reason, message):
    body = {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message}]}}
    return ({"status": str(status), "content-type": "application/json"}, json.dumps(body))


def _channel(channel_id=CHANNEL_ID, title="Bench"):
    return {"id": channel_id, "snippet": {"title": title},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + channel_id[2:]}}}


def _uploads(*video_ids):
    return {"items": [{"contentDetails": {"videoId": video_id}} for video_id in video_ids]}


def _videos(*video_ids, channel_id=CHANNEL_ID):
    return {"items": [{"id": video_id, "snippet": {"title": video_id, "channelId": channel_id,
                                                    "channelTitle": "Bench"}} for video_id in video_ids]}


def _comment_page(count, next_page=True):
    items = [{"snippet": {"topLevelComment": {"id": f"c{i}", "snippet": {
        "textDisplay": f"comment {i}", "authorDisplayName": f"@viewer{i}", "likeCount": i,
        "publishedAt": "2026-05-01T00:00:00Z"}}}} for i in range(count)]
    return {"items": items, **({"nextPageToken": "more"} if next_page else {})}


@pytest.fixture
def replies(monkeypatch):
    """`replies([...])` queues the HTTP replies the next YouTube calls will get."""

    def install(sequence):
        client = build("youtube", "v3", developerKey=KEY, http=HttpMockSequence(sequence),
                       cache_discovery=False)
        monkeypatch.setattr(youtube, "_build_client", lambda api_key: client)

    return install


def test_fetch_comments_stops_at_the_cap_and_meters_each_page(replies):
    replies([_ok(_comment_page(100)) for _ in range(5)])
    meter = QuotaMeter()
    comments = fetch_comments(KEY, "video000001", max_comments=250, meter=meter)
    assert len(comments) == 250
    assert comments[0].author == "@viewer0"
    assert meter.calls == {"commentThreads.list": 3}
    assert meter.units == estimate_quota(1, 1, 250)["breakdown"]["commentThreads.list"]


def test_a_study_spends_what_the_estimate_says(replies):
    channels, per_channel, per_video = 12, 8, 500
    ids = [f"UC{n:022d}" for n in range(channels)]
    video_ids = [[f"v{n:02d}{i:08d}" for i in range(per_channel)] for n in range(channels)]
    flat = [video_id for group in video_ids for video_id in group]
    sequence = [_ok({"items": [_channel(channel_id)]}) for channel_id in ids]
    sequence += [_ok(_uploads(*group)) for group in video_ids]
    sequence += [_ok(_videos(*flat[:50])), _ok(_videos(*flat[50:]))]
    sequence += [_ok(_comment_page(100)) for _ in range(len(flat) * 5)]
    replies(sequence)

    corpus = build_corpus(KEY, [f"@channel{n}" for n in range(channels)],
                          videos_per_channel=per_channel, comments_per_video=per_video)
    assert len(corpus.comments) == channels * per_channel * per_video
    assert corpus.quota.calls == estimate_quota(channels, per_channel, per_video)["breakdown"]
    assert corpus.quota.units == 506


def test_errors_never_show_the_api_key(replies):
    replies([_error(403, "accessNotConfigured", "YouTube Data API v3 has not been used in project 1.")])
    with pytest.raises(YouTubeError) as raised:
        fetch_comments(KEY, "video000001")
    assert "has not been used in project" in str(raised.value)
    assert KEY not in str(raised.value)


def test_a_channel_id_that_does_not_exist_is_reported(replies):
    replies([_ok({"items": [_channel()]})])
    with pytest.raises(YouTubeError, match="UC" + "b" * 22):
        resolve_channels(KEY, [CHANNEL_ID, "UC" + "b" * 22])


def test_build_corpus_skips_a_video_with_comments_disabled(replies):
    replies([
        _ok({"items": [_channel()]}),
        _ok(_uploads("video000001", "video000002")),
        _ok(_videos("video000001", "video000002")),
        _error(403, "commentsDisabled", "The video has disabled comments."),
        _ok(_comment_page(30, next_page=False)),
    ])
    corpus = build_corpus(KEY, [CHANNEL_ID], videos_per_channel=2, comments_per_video=100)
    assert {comment.video_id for comment in corpus.comments} == {"video000002"}
    assert len(corpus.videos) == 2  # still counts as an existing video for gap detection


def test_build_corpus_stops_when_the_quota_runs_out(replies):
    out_of_quota = _error(403, "quotaExceeded", "The request cannot be completed because you have exceeded your quota.")
    replies([
        _ok({"items": [_channel()]}),
        _ok(_uploads("video000001", "video000002", "video000003")),
        _ok(_videos("video000001", "video000002", "video000003")),
        _ok(_comment_page(30, next_page=False)),
        out_of_quota,
        out_of_quota,
    ])
    with pytest.raises(YouTubeError, match="quota"):
        build_corpus(KEY, [CHANNEL_ID], videos_per_channel=3, comments_per_video=100)
