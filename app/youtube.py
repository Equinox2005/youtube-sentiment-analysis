"""YouTube Data API helpers: video metadata, comments, and transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class YouTubeError(Exception):
    """User-facing error while talking to YouTube."""


VIDEO_ID_PATTERNS = [
    r"(?:v=|/videos/|embed/|youtu\.be/|/v/|/e/|watch\?v=|shorts/|live/)([A-Za-z0-9_-]{11})",
    r"^([A-Za-z0-9_-]{11})$",
]


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


@dataclass
class Comment:
    text: str
    author: str = ""
    likes: int = 0
    published_at: str = ""
    reply_count: int = 0


@dataclass
class VideoInfo:
    video_id: str
    title: str = ""
    channel: str = ""
    published_at: str = ""
    thumbnail: str = ""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    description: str = ""
    tags: list[str] = field(default_factory=list)


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


def fetch_video_info(api_key: str, video_id: str) -> VideoInfo:
    """Fetch title, channel, stats and thumbnail for a video."""
    try:
        response = (
            _build_client(api_key)
            .videos()
            .list(part="snippet,statistics", id=video_id)
            .execute()
        )
    except Exception as exc:  # googleapiclient raises HttpError
        raise _translate_http_error(exc) from exc

    items = response.get("items", [])
    if not items:
        raise YouTubeError("Video not found. Check the URL and try again.")

    snippet = items[0].get("snippet", {})
    stats = items[0].get("statistics", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")

    return VideoInfo(
        video_id=video_id,
        title=snippet.get("title", ""),
        channel=snippet.get("channelTitle", ""),
        published_at=snippet.get("publishedAt", ""),
        thumbnail=thumb,
        view_count=int(stats.get("viewCount", 0)),
        like_count=int(stats.get("likeCount", 0)),
        comment_count=int(stats.get("commentCount", 0)),
        description=snippet.get("description", "")[:500],
        tags=snippet.get("tags", [])[:15],
    )


def fetch_comments(
    api_key: str,
    video_id: str,
    max_comments: int = 500,
    sort_by: str = "relevance",
) -> list[Comment]:
    """Fetch up to max_comments top-level comments with author/like/date metadata."""
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
        while request and len(comments) < max_comments:
            response = request.execute()
            for item in response.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append(
                    Comment(
                        text=top.get("textDisplay", ""),
                        author=top.get("authorDisplayName", ""),
                        likes=int(top.get("likeCount", 0)),
                        published_at=top.get("publishedAt", ""),
                        reply_count=int(item["snippet"].get("totalReplyCount", 0)),
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
