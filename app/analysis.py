"""Orchestrates a full sentiment report for a YouTube video."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from .sentiment import extract_keywords, score_long_text, score_text
from .youtube import (
    Comment,
    VideoInfo,
    extract_video_id,
    fetch_comments,
    fetch_transcript,
    fetch_video_info,
)


def _health_score(avg_compound: float, pos_pct: float, neg_pct: float) -> int:
    """0-100 'community health' score blending average tone and balance."""
    base = (avg_compound + 1) / 2 * 100  # map [-1,1] -> [0,100]
    balance_bonus = (pos_pct - neg_pct) * 0.15
    return max(0, min(100, round(base + balance_bonus)))


def _timeline(scored: list[dict]) -> list[dict]:
    """Bucket average sentiment by month of comment publication."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for item in scored:
        date = item.get("published_at", "")
        if len(date) >= 7:
            buckets[date[:7]].append(item["compound"])
    return [
        {
            "period": period,
            "avg_compound": round(sum(vals) / len(vals), 4),
            "count": len(vals),
        }
        for period, vals in sorted(buckets.items())
    ]


def build_report(
    video: VideoInfo,
    comments: list[Comment],
    transcript: str | None,
) -> dict:
    """Compute the full analysis report from already-fetched data."""
    scored: list[dict] = []
    for comment in comments:
        result = score_text(comment.text)
        scored.append(
            {
                "text": comment.text,
                "author": comment.author,
                "likes": comment.likes,
                "published_at": comment.published_at,
                "reply_count": comment.reply_count,
                "label": result["label"],
                "compound": round(result["compound"], 4),
            }
        )

    total = len(scored)
    pos = [s for s in scored if s["label"] == "positive"]
    neg = [s for s in scored if s["label"] == "negative"]
    neu = [s for s in scored if s["label"] == "neutral"]

    avg_compound = sum(s["compound"] for s in scored) / total if total else 0.0

    # Like-weighted average: what the community endorses, not just what it says.
    weight_sum = sum(s["likes"] + 1 for s in scored)
    weighted_compound = (
        sum(s["compound"] * (s["likes"] + 1) for s in scored) / weight_sum if total else 0.0
    )

    pos_pct = len(pos) / total * 100 if total else 0.0
    neg_pct = len(neg) / total * 100 if total else 0.0
    neu_pct = len(neu) / total * 100 if total else 0.0

    # Transcript / video sentiment and agreement.
    video_sentiment = score_long_text(transcript) if transcript else {
        "label": "unknown",
        "compound": 0.0,
    }
    agreement = None
    if video_sentiment["label"] not in ("unknown", "neutral") and total:
        agreeing = [
            s
            for s in scored
            if s["label"] == video_sentiment["label"] and s["label"] != "neutral"
        ]
        opposing = [
            s
            for s in scored
            if s["label"] not in ("neutral", video_sentiment["label"])
        ]
        judged = len(agreeing) + len(opposing)
        agreement = {
            "agree": len(agreeing),
            "disagree": len(opposing),
            "neutral": total - judged,
            "agree_pct": round(len(agreeing) / judged * 100, 2) if judged else 0.0,
        }

    top_positive = sorted(pos, key=lambda s: (s["compound"], s["likes"]), reverse=True)[:5]
    top_negative = sorted(neg, key=lambda s: (s["compound"], -s["likes"]))[:5]
    most_liked = sorted(scored, key=lambda s: s["likes"], reverse=True)[:5]

    return {
        "video": asdict(video),
        "summary": {
            "total_comments": total,
            "positive": len(pos),
            "negative": len(neg),
            "neutral": len(neu),
            "positive_pct": round(pos_pct, 2),
            "negative_pct": round(neg_pct, 2),
            "neutral_pct": round(neu_pct, 2),
            "avg_compound": round(avg_compound, 4),
            "weighted_compound": round(weighted_compound, 4),
            "health_score": _health_score(avg_compound, pos_pct, neg_pct),
            "verdict": _verdict(avg_compound, pos_pct, neg_pct),
        },
        "video_sentiment": video_sentiment,
        "agreement": agreement,
        "timeline": _timeline(scored),
        "keywords": extract_keywords([s["text"] for s in scored]),
        "top_positive": top_positive,
        "top_negative": top_negative,
        "most_liked": most_liked,
        "comments": scored,
    }


def _verdict(avg: float, pos_pct: float, neg_pct: float) -> str:
    if avg >= 0.35 and pos_pct >= 60:
        return "Overwhelmingly positive — the audience loves this video."
    if avg >= 0.15:
        return "Mostly positive — the community response is favorable."
    if avg <= -0.35 and neg_pct >= 60:
        return "Overwhelmingly negative — the audience strongly dislikes this video."
    if avg <= -0.15:
        return "Mostly negative — the community response leans critical."
    if abs(pos_pct - neg_pct) < 10 and pos_pct > 20:
        return "Divisive — the audience is split between praise and criticism."
    return "Mixed/neutral — no strong sentiment either way."


def analyze_video(
    api_key: str,
    url_or_id: str,
    max_comments: int = 500,
    sort_by: str = "relevance",
    include_transcript: bool = True,
) -> dict:
    """Fetch everything for a video and build the full report."""
    video_id = extract_video_id(url_or_id)
    video = fetch_video_info(api_key, video_id)
    comments = fetch_comments(api_key, video_id, max_comments=max_comments, sort_by=sort_by)
    transcript = fetch_transcript(video_id) if include_transcript else None
    return build_report(video, comments, transcript)
