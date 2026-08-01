"""Command-line interface for YouTube Sentiment Insights.

Usage:
    python cli.py <video-url-or-id> [--comments N] [--sort top|latest] [--json out.json] [--csv out.csv]
    python cli.py demo
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

# Windows consoles often default to cp1252, which can't print emoji/box chars.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import get_api_key
from app.demo import demo_report
from app.youtube import YouTubeError

BAR_WIDTH = 30


def bar(pct: float) -> str:
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze YouTube comment sentiment.")
    parser.add_argument("url", help="YouTube video URL/ID, or 'demo' for sample data")
    parser.add_argument("--comments", type=int, default=500, help="Max comments to fetch (default 500)")
    parser.add_argument("--sort", choices=["top", "latest"], default="top")
    parser.add_argument("--no-transcript", action="store_true", help="Skip transcript analysis")
    parser.add_argument("--json", metavar="FILE", help="Write full report as JSON")
    parser.add_argument("--csv", metavar="FILE", help="Write scored comments as CSV")
    args = parser.parse_args()

    if args.url.strip().lower() == "demo":
        report = demo_report(max_comments=min(args.comments, 120))
    else:
        api_key = get_api_key()
        if not api_key:
            print("Error: set the YOUTUBE_API_KEY environment variable (or use a .env file).")
            print("Tip: run `python cli.py demo` to try the tool with sample data.")
            return 1
        from app.analysis import analyze_video

        try:
            report = analyze_video(
                api_key,
                args.url,
                max_comments=args.comments,
                sort_by="relevance" if args.sort == "top" else "time",
                include_transcript=not args.no_transcript,
            )
        except YouTubeError as exc:
            print(f"Error: {exc}")
            return 1

    v, s = report["video"], report["summary"]
    print()
    print(f"🎬 {v['title']}  —  {v['channel']}")
    print(f"   {v['view_count']:,} views · {v['like_count']:,} likes · {v['comment_count']:,} comments")
    print()
    print(f"📊 Sentiment across {s['total_comments']} comments:")
    print(f"   Positive {bar(s['positive_pct'])} {s['positive_pct']:6.2f}%  ({s['positive']})")
    print(f"   Negative {bar(s['negative_pct'])} {s['negative_pct']:6.2f}%  ({s['negative']})")
    print(f"   Neutral  {bar(s['neutral_pct'])} {s['neutral_pct']:6.2f}%  ({s['neutral']})")
    print()
    print(f"   Avg sentiment score:        {s['avg_compound']:+.4f}   (-1 … +1)")
    print(f"   Like-weighted sentiment:    {s['weighted_compound']:+.4f}")
    print(f"   Community health score:     {s['health_score']}/100")
    print(f"   Verdict: {s['verdict']}")

    vs = report["video_sentiment"]
    print()
    print(f"🎥 Video (transcript) tone: {vs['label']} ({vs.get('compound', 0):+.4f})")
    if report["agreement"]:
        a = report["agreement"]
        print(
            f"   Agreement: {a['agree']} agree / {a['disagree']} disagree / {a['neutral']} neutral"
            f"  →  {a['agree_pct']}% of opinionated comments agree with the video"
        )

    if report["keywords"]:
        words = ", ".join(k["word"] for k in report["keywords"][:10])
        print()
        print(f"🔑 Top keywords: {words}")

    if report["top_positive"]:
        c = report["top_positive"][0]
        print()
        print(f"💚 Most positive: \"{c['text'][:110]}\" ({c['compound']:+.2f}, 👍{c['likes']})")
    if report["top_negative"]:
        c = report["top_negative"][0]
        print(f"💔 Most negative: \"{c['text'][:110]}\" ({c['compound']:+.2f}, 👍{c['likes']})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"\n💾 Full report written to {args.json}")
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["author", "text", "likes", "reply_count", "published_at", "label", "compound"]
            )
            writer.writeheader()
            writer.writerows(
                {key: c[key] for key in writer.fieldnames} for c in report["comments"]
            )
        print(f"💾 Scored comments written to {args.csv}")

    print()
    print("🌐 Prefer a dashboard? Run:  uvicorn app.main:app  →  http://127.0.0.1:8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
