"""Single-video comment intelligence.

Same engine as a niche study, scoped to one video. The output is deliberately
not a sentiment breakdown: a positive/negative split on YouTube comments lands
in the same narrow band for almost every video and cannot separate two videos
that are nothing alike. What a creator can act on is the specific stuff —
what was requested, what confused people, what got disputed, which moments
people rewound to.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .extraction import UsageMeter
from .niche import (
    CAVEATS,
    Corpus,
    build_themes,
    extract_records,
    fold_candidates,
    product_report,
    strip_internals,
    trust_report,
    vocabulary_report,
)
from .textutil import format_timestamp, timestamp_seconds
from .youtube import (
    Comment,
    QuotaMeter,
    VideoInfo,
    extract_video_id,
    fetch_comments,
    fetch_video_info,
)

# Comment timestamps cluster loosely around a moment, so bucket before counting.
_BUCKET_SECONDS = 30


def timestamp_heatmap(comments: list[Comment], limit: int = 12) -> list[dict]:
    """Which moments the audience actually reacted to.

    The old engine stripped timestamps as noise before scoring. They are one of
    the few genuinely precise signals in a comment section.
    """
    buckets: dict[int, dict] = defaultdict(
        lambda: {"count": 0, "likes": 0, "examples": [], "exact": Counter()}
    )
    for comment in comments:
        seen: set[int] = set()
        for seconds in timestamp_seconds(comment.text):
            bucket = seconds // _BUCKET_SECONDS
            if bucket in seen:
                continue
            seen.add(bucket)
            entry = buckets[bucket]
            entry["count"] += 1
            entry["likes"] += comment.likes
            entry["exact"][seconds] += 1
            if len(entry["examples"]) < 3:
                entry["examples"].append(
                    {
                        "quote": comment.text[:200],
                        "author": comment.author,
                        "likes": comment.likes,
                    }
                )

    moments = []
    for bucket, entry in buckets.items():
        if entry["count"] < 2:
            continue
        # Report the moment people actually cited, not the bucket boundary — the
        # bucket exists only to group near-misses, and a creator needs a real
        # timestamp they can seek to.
        seconds = entry["exact"].most_common(1)[0][0]
        moments.append(
            {
                "seconds": seconds,
                "timestamp": format_timestamp(seconds),
                "window": [bucket * _BUCKET_SECONDS, (bucket + 1) * _BUCKET_SECONDS],
                "count": entry["count"],
                "likes": entry["likes"],
                "examples": entry["examples"],
            }
        )
    moments.sort(key=lambda moment: (moment["count"], moment["likes"]), reverse=True)
    return moments[:limit]


def _flatten_questions(themes: dict[str, list[dict]], limit: int = 15) -> list[dict]:
    """Top unanswered questions — the cheapest reply a creator can make."""
    rows = []
    for theme in themes.get("question", []):
        example = theme["examples"][0] if theme["examples"] else {}
        rows.append(
            {
                "question": theme["title"],
                "detail": theme["description"],
                "asked_by": theme["count"],
                "likes": theme["likes"],
                "example": example.get("quote", ""),
                "author": example.get("author", ""),
            }
        )
    rows.sort(key=lambda row: (row["asked_by"], row["likes"]), reverse=True)
    return rows[:limit]


def build_report(
    video: VideoInfo,
    comments: list[Comment],
    quota: QuotaMeter | None = None,
    usage: UsageMeter | None = None,
    progress=None,
) -> dict:
    """Compute the full comment-intelligence report from already-fetched data."""
    usage = usage or UsageMeter()
    quota = quota or QuotaMeter()

    corpus = Corpus(channels=[], videos=[video], comments=comments, quota=quota)
    records, spam_keys, vocabulary, signals = extract_records(corpus, usage, progress=progress)
    candidates = fold_candidates(records)
    clean_themes = strip_internals(build_themes(candidates, usage, progress=progress))

    counts = {kind: sum(theme["count"] for theme in v) for kind, v in clean_themes.items()}

    return {
        "video": {
            "video_id": video.video_id,
            "title": video.title,
            "channel": video.channel,
            "channel_id": video.channel_id,
            "published_at": video.published_at,
            "thumbnail": video.thumbnail,
            "view_count": video.view_count,
            "like_count": video.like_count,
            "comment_count": video.comment_count,
            "description": video.description,
            "tags": video.tags,
        },
        "summary": {
            "comments_analyzed": len(comments),
            "spam_filtered": len(spam_keys),
            "items_extracted": len(records),
            "distinct_statements": sum(len(v) for v in candidates.values()),
            "counts_by_kind": counts,
        },
        "themes": clean_themes,
        "questions": _flatten_questions(clean_themes),
        "timestamps": timestamp_heatmap(comments),
        "products": product_report(records),
        "vocabulary": vocabulary_report(vocabulary, [video]),
        "trust": trust_report(signals),
        "quota": quota.as_dict(),
        "usage": usage.as_dict(),
        "caveats": CAVEATS,
    }


def analyze_video(
    api_key: str,
    url_or_id: str,
    max_comments: int = 500,
    sort_by: str = "relevance",
    progress=None,
) -> dict:
    """Fetch a video's comments and build the comment-intelligence report.

    `progress`, if given, is called as progress(stage, done, total) with stage
    one of "comments", "extract" or "themes".
    """
    quota = QuotaMeter()
    video_id = extract_video_id(url_or_id)
    video = fetch_video_info(api_key, video_id, meter=quota)
    if progress:
        progress("comments", 0, 1)
    comments = fetch_comments(
        api_key, video_id, max_comments=max_comments, sort_by=sort_by, meter=quota
    )
    if progress:
        progress("comments", 1, 1)
    return build_report(video, comments, quota=quota, progress=progress)
