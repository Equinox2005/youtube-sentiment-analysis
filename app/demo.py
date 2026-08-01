"""Demo mode: runs the real analysis engine on bundled sample data.

Lets users try the app instantly without a YouTube API key.
"""

from __future__ import annotations

import random

from .analysis import build_report
from .youtube import Comment, VideoInfo

_SAMPLE_COMMENTS = [
    ("This is an absolute masterpiece, I've watched it five times already!", 2841, "2026-01-12T10:04:00Z"),
    ("The editing on this is insane. Instant subscribe.", 1932, "2026-01-13T14:21:00Z"),
    ("Finally someone explains this properly. Thank you so much!", 1518, "2026-01-15T09:12:00Z"),
    ("GOATED video, no notes 🔥🔥🔥", 1204, "2026-01-16T18:45:00Z"),
    ("I don't usually comment but this deserved it. Incredible work.", 977, "2026-02-01T11:30:00Z"),
    ("This changed how I think about the whole topic. Underrated channel.", 803, "2026-02-03T16:02:00Z"),
    ("Honestly one of the best videos on YouTube right now.", 654, "2026-02-07T08:44:00Z"),
    ("The production quality keeps getting better every upload!", 512, "2026-02-10T20:15:00Z"),
    ("Came from the shorts, staying for everything else. Amazing.", 431, "2026-02-14T12:38:00Z"),
    ("10:24 gave me actual goosebumps", 389, "2026-02-18T22:01:00Z"),
    ("Great video but the audio mixing was a little off in the middle section.", 244, "2026-03-02T10:11:00Z"),
    ("Good content, although I wish it was longer honestly.", 199, "2026-03-05T13:26:00Z"),
    ("Interesting take. Not sure I fully agree but well presented.", 157, "2026-03-09T17:53:00Z"),
    ("Watching this on my lunch break", 88, "2026-03-11T12:05:00Z"),
    ("Here before 1 million views", 76, "2026-03-12T19:20:00Z"),
    ("Who's watching in 2026?", 65, "2026-03-15T21:47:00Z"),
    ("The algorithm finally did something right", 51, "2026-03-18T07:32:00Z"),
    ("First half was solid, second half felt rushed to be honest.", 143, "2026-04-01T15:14:00Z"),
    ("Kind of mid compared to their older uploads, not gonna lie.", 121, "2026-04-04T09:41:00Z"),
    ("The thumbnail is pure clickbait, the video barely covers what it promises.", 310, "2026-04-08T18:29:00Z"),
    ("Disappointed. So much filler and barely any actual content.", 205, "2026-04-12T11:57:00Z"),
    ("This didn't age well...", 97, "2026-04-15T14:03:00Z"),
    ("Unsubscribed after this one. Quality has really dropped.", 178, "2026-04-19T20:36:00Z"),
    ("Terrible advice honestly, please do more research before posting.", 231, "2026-04-23T16:48:00Z"),
    ("Waste of 20 minutes. The title is misleading and the conclusion is wrong.", 164, "2026-04-27T10:22:00Z"),
    ("Absolutely loved the storytelling in this one, brilliant pacing!", 298, "2026-05-02T13:09:00Z"),
    ("This deserves way more views. Sharing with everyone I know.", 267, "2026-05-06T19:44:00Z"),
    ("W video, W creator, W everything", 189, "2026-05-10T08:17:00Z"),
    ("Bro really dropped the best video of the year and left", 356, "2026-05-14T22:53:00Z"),
    ("Not their best work but still enjoyable overall.", 84, "2026-05-18T15:31:00Z"),
]

_SAMPLE_TRANSCRIPT = (
    "Welcome back everyone, today we're diving into something truly exciting. "
    "I've spent months researching this and I genuinely believe it will change "
    "the way you think about the topic. The results were amazing, better than "
    "I ever expected, and I can't wait to share what I learned. There were some "
    "frustrating setbacks along the way, but overall this journey was incredible "
    "and I'm thrilled with how everything turned out. Let's get started."
)


def demo_report(max_comments: int = 30) -> dict:
    """Build a full report from bundled sample data using the real engine."""
    rng = random.Random(42)
    rows = _SAMPLE_COMMENTS[:]
    while len(rows) < min(max_comments, 120):
        text, likes, date = rng.choice(_SAMPLE_COMMENTS)
        rows.append((text, max(0, likes // rng.randint(2, 10)), date))

    comments = [
        Comment(
            text=text,
            author=f"@viewer{i + 1}",
            likes=likes,
            published_at=date,
            reply_count=likes // 50,
        )
        for i, (text, likes, date) in enumerate(rows[:max_comments])
    ]

    video = VideoInfo(
        video_id="demo00000000",
        title="[DEMO] Sample Video — no API key required",
        channel="Demo Channel",
        published_at="2026-01-10T00:00:00Z",
        thumbnail="",
        view_count=1_284_503,
        like_count=87_311,
        comment_count=len(comments),
        description="This is bundled sample data so you can explore the app without a YouTube API key.",
        tags=["demo", "sample"],
    )

    report = build_report(video, comments, _SAMPLE_TRANSCRIPT)
    report["demo"] = True
    return report
