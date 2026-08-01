"""YouTube Data API helpers: channels, videos, comments, and transcripts.

Quota notes (units per call; the free tier allows 10,000 units/day):

    search.list         100    <- avoided entirely, it is the trap
    channels.list         1    (up to 50 channel IDs per call)
    playlistItems.list    1    (50 videos per page)
    videos.list           1    (up to 50 video IDs per call)
    commentThreads.list   1    (100 comments per page)

A channel's whole catalogue is reachable without ever calling search:
channels.list returns the 'uploads' playlist ID, and playlistItems pages
through it at 1 unit per 50 videos. That is what makes a multi-channel study
affordable — a 12-channel, 96-video, ~48k-comment corpus costs ~495 units.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


class YouTubeError(Exception):
    """User-facing error while talking to YouTube."""


VIDEO_ID_PATTERNS = [
    r"(?:v=|/videos/|embed/|youtu\.be/|/v/|/e/|watch\?v=|shorts/|live/)([A-Za-z0-9_-]{11})",
    r"^([A-Za-z0-9_-]{11})$",
]

_CHANNEL_ID_RE = re.compile(r"(UC[A-Za-z0-9_-]{22})")
_HANDLE_RE = re.compile(r"@([A-Za-z0-9._\-]{3,30})")

# Quota costs, kept here so the meter and the docs cannot drift apart.
QUOTA_COSTS = {
    "channels.list": 1,
    "playlistItems.list": 1,
    "videos.list": 1,
    "commentThreads.list": 1,
    "search.list": 100,
}


@dataclass
class QuotaMeter:
    """Tracks YouTube API units spent so a study can report its own cost."""

    units: int = 0
    calls: dict[str, int] = field(default_factory=dict)

    def spend(self, endpoint: str, count: int = 1) -> None:
        self.units += QUOTA_COSTS.get(endpoint, 1) * count
        self.calls[endpoint] = self.calls.get(endpoint, 0) + count

    def as_dict(self) -> dict:
        return {"units": self.units, "calls": dict(self.calls), "daily_free_tier": 10_000}


def extract_video_id(url_or_id: str) -> str:
    """Extract an 11-character video ID from a URL or raw ID."""
    text = url_or_id.strip()
    for pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    raise YouTubeError(
        "Could not find a valid YouTube video ID in the input. "
        "Paste a full video URL or an 11-character video ID."
    )


def parse_channel_ref(ref: str) -> tuple[str, str]:
    """Classify a channel reference as ('id', UC...) or ('handle', name).

    Accepts channel URLs, /channel/UC... paths, @handles, and raw IDs.
    """
    text = ref.strip()
    if not text:
        raise YouTubeError("Empty channel reference.")

    match = _CHANNEL_ID_RE.search(text)
    if match:
        return "id", match.group(1)

    match = _HANDLE_RE.search(text)
    if match:
        return "handle", match.group(1)

    # A bare word is treated as a handle — youtube.com/c/Name style links land here.
    bare = text.rstrip("/").split("/")[-1]
    if bare and re.fullmatch(r"[A-Za-z0-9._\-]{3,30}", bare):
        return "handle", bare

    raise YouTubeError(
        f"Could not understand the channel reference {ref!r}. "
        "Use a channel URL, an @handle, or a UC... channel ID."
    )


@dataclass
class Comment:
    text: str
    comment_id: str = ""
    author: str = ""
    author_channel_id: str = ""
    likes: int = 0
    published_at: str = ""
    reply_count: int = 0
    video_id: str = ""

    @property
    def identity(self) -> str:
        """Stable-ish commenter key. Channel IDs beat display names, which collide."""
        return self.author_channel_id or self.author


@dataclass
class VideoInfo:
    video_id: str
    title: str = ""
    channel: str = ""
    channel_id: str = ""
    published_at: str = ""
    thumbnail: str = ""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ChannelInfo:
    channel_id: str
    title: str = ""
    uploads_playlist: str = ""
    subscriber_count: int = 0
    video_count: int = 0
    thumbnail: str = ""
    description: str = ""


@lru_cache(maxsize=4)
def _build_client(api_key: str):
    from googleapiclient.discovery import build

    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _translate_http_error(exc: Exception) -> YouTubeError:
    message = str(exc)
    if "quotaExceeded" in message:
        return YouTubeError("YouTube API quota exceeded. Try again later (quota resets daily).")
    if "commentsDisabled" in message:
        return YouTubeError("Comments are disabled for this video.")
    if "API key not valid" in message or "keyInvalid" in message:
        return YouTubeError("The configured YouTube API key is invalid.")
    if "videoNotFound" in message or "notFound" in message:
        return YouTubeError("Video not found. Check the URL and try again.")
    return YouTubeError(f"YouTube API error: {message}")


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------


def _channel_from_item(item: dict) -> ChannelInfo:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {}).get("relatedPlaylists", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
    return ChannelInfo(
        channel_id=item.get("id", ""),
        title=snippet.get("title", ""),
        uploads_playlist=content.get("uploads", ""),
        subscriber_count=int(stats.get("subscriberCount", 0) or 0),
        video_count=int(stats.get("videoCount", 0) or 0),
        thumbnail=thumb,
        description=snippet.get("description", "")[:300],
    )


def resolve_channels(
    api_key: str,
    refs: list[str],
    meter: QuotaMeter | None = None,
) -> list[ChannelInfo]:
    """Resolve channel URLs/@handles/IDs to ChannelInfo, batching where possible.

    ID lookups batch 50 per call; handle lookups cost 1 unit each because
    `forHandle` accepts only one value. Neither uses search.list.
    """
    meter = meter or QuotaMeter()
    youtube = _build_client(api_key)
    parts = "snippet,contentDetails,statistics"

    ids: list[str] = []
    handles: list[str] = []
    for ref in refs:
        kind, value = parse_channel_ref(ref)
        (ids if kind == "id" else handles).append(value)

    resolved: dict[str, ChannelInfo] = {}
    try:
        for chunk in _chunks(ids, 50):
            response = youtube.channels().list(part=parts, id=",".join(chunk), maxResults=50).execute()
            meter.spend("channels.list")
            for item in response.get("items", []):
                info = _channel_from_item(item)
                resolved[info.channel_id] = info

        for handle in handles:
            response = youtube.channels().list(part=parts, forHandle=handle).execute()
            meter.spend("channels.list")
            items = response.get("items", [])
            if not items:
                raise YouTubeError(f"No channel found for handle @{handle}.")
            info = _channel_from_item(items[0])
            resolved[info.channel_id] = info
    except YouTubeError:
        raise
    except Exception as exc:
        raise _translate_http_error(exc) from exc

    if not resolved:
        raise YouTubeError("None of the supplied channel references could be resolved.")
    return list(resolved.values())


def fetch_channel_video_ids(
    api_key: str,
    channel: ChannelInfo,
    limit: int = 25,
    meter: QuotaMeter | None = None,
) -> list[str]:
    """List a channel's most recent video IDs via its uploads playlist (1 unit/50)."""
    if not channel.uploads_playlist:
        return []
    meter = meter or QuotaMeter()
    youtube = _build_client(api_key)
    video_ids: list[str] = []
    try:
        request = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=channel.uploads_playlist,
            maxResults=50,
        )
        while request is not None and len(video_ids) < limit:
            response = request.execute()
            meter.spend("playlistItems.list")
            for item in response.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            request = youtube.playlistItems().list_next(request, response)
    except Exception as exc:
        if video_ids:
            return video_ids[:limit]
        raise _translate_http_error(exc) from exc
    return video_ids[:limit]


# --------------------------------------------------------------------------
# Videos
# --------------------------------------------------------------------------


def _video_from_item(item: dict) -> VideoInfo:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
    return VideoInfo(
        video_id=item.get("id", ""),
        title=snippet.get("title", ""),
        channel=snippet.get("channelTitle", ""),
        channel_id=snippet.get("channelId", ""),
        published_at=snippet.get("publishedAt", ""),
        thumbnail=thumb,
        view_count=int(stats.get("viewCount", 0) or 0),
        like_count=int(stats.get("likeCount", 0) or 0),
        comment_count=int(stats.get("commentCount", 0) or 0),
        description=snippet.get("description", "")[:500],
        tags=snippet.get("tags", [])[:15],
    )


def fetch_videos_info(
    api_key: str,
    video_ids: list[str],
    meter: QuotaMeter | None = None,
) -> list[VideoInfo]:
    """Fetch metadata for many videos, batching 50 IDs per call (1 unit each)."""
    if not video_ids:
        return []
    meter = meter or QuotaMeter()
    youtube = _build_client(api_key)
    videos: list[VideoInfo] = []
    try:
        for chunk in _chunks(list(video_ids), 50):
            response = (
                youtube.videos()
                .list(part="snippet,statistics", id=",".join(chunk), maxResults=50)
                .execute()
            )
            meter.spend("videos.list")
            videos.extend(_video_from_item(item) for item in response.get("items", []))
    except Exception as exc:
        raise _translate_http_error(exc) from exc
    return videos


def fetch_video_info(api_key: str, video_id: str, meter: QuotaMeter | None = None) -> VideoInfo:
    """Fetch title, channel, stats and thumbnail for a single video."""
    videos = fetch_videos_info(api_key, [video_id], meter=meter)
    if not videos:
        raise YouTubeError("Video not found. Check the URL and try again.")
    return videos[0]


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------


def fetch_comments(
    api_key: str,
    video_id: str,
    max_comments: int = 500,
    sort_by: str = "relevance",
    meter: QuotaMeter | None = None,
) -> list[Comment]:
    """Fetch up to max_comments top-level comments with author/like/date metadata.

    `sort_by="relevance"` surfaces high-engagement comments and is right for a
    highlight reel; research sampling should pass "time" for a less biased draw.
    """
    meter = meter or QuotaMeter()
    youtube = _build_client(api_key)
    comments: list[Comment] = []
    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText",
            order=sort_by,
        )
        while request is not None and len(comments) < max_comments:
            response = request.execute()
            meter.spend("commentThreads.list")
            for item in response.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append(
                    Comment(
                        text=top.get("textDisplay", ""),
                        comment_id=item["snippet"]["topLevelComment"].get("id", ""),
                        author=top.get("authorDisplayName", ""),
                        author_channel_id=(top.get("authorChannelId") or {}).get("value", ""),
                        likes=int(top.get("likeCount", 0) or 0),
                        published_at=top.get("publishedAt", ""),
                        reply_count=int(item["snippet"].get("totalReplyCount", 0) or 0),
                        video_id=video_id,
                    )
                )
            request = youtube.commentThreads().list_next(request, response)
    except Exception as exc:
        if comments:
            return comments[:max_comments]  # partial results beat a hard failure
        raise _translate_http_error(exc) from exc

    return comments[:max_comments]


def fetch_transcript(video_id: str) -> str | None:
    """Return the video transcript as plain text, or None if unavailable."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        try:  # v1.x API
            fetched = YouTubeTranscriptApi().fetch(video_id)
            return " ".join(snippet.text for snippet in fetched)
        except AttributeError:  # v0.6.x API
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            return " ".join(entry["text"] for entry in transcript)
    except Exception:
        return None


def estimate_quota(channels: int, videos_per_channel: int, comments_per_video: int) -> dict:
    """Predict the quota cost of a study before spending any of it."""
    videos = channels * videos_per_channel
    channel_calls = max(1, (channels + 49) // 50)
    playlist_calls = channels * max(1, (videos_per_channel + 49) // 50)
    video_calls = max(1, (videos + 49) // 50) if videos else 0
    comment_calls = videos * max(1, (comments_per_video + 99) // 100)
    units = channel_calls + playlist_calls + video_calls + comment_calls
    return {
        "videos": videos,
        "estimated_units": units,
        "daily_free_tier": 10_000,
        "studies_per_day": (10_000 // units) if units else 0,
        "breakdown": {
            "channels.list": channel_calls,
            "playlistItems.list": playlist_calls,
            "videos.list": video_calls,
            "commentThreads.list": comment_calls,
        },
    }
