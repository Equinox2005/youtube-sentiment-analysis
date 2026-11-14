"""Command-line interface for YouTube Audience Research.

    python cli.py study "@channel1" "@channel2" --videos 8 --comments 300
    python cli.py study demo
    python cli.py video "https://youtube.com/watch?v=..." --comments 500
    python cli.py estimate --channels 12 --videos 8 --comments 500
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap

# Windows consoles often default to cp1252, which cannot print box characters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import get_anthropic_key, get_api_key
from app.extraction import ExtractionError
from app.youtube import YouTubeError, estimate_quota

RULE = "─" * 78


def _header(text: str) -> None:
    print(f"\n{text}\n{RULE}")


def _wrap(text: str, width: int = 74, indent: str = "   ") -> str:
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _progress(stage: str, done: int, total: int) -> None:
    label = {"channels": "Resolving channels", "comments": "Fetching comments",
             "extract": "Extracting", "themes": "Clustering themes"}.get(stage, stage)
    print(f"\r   {label}: {done}/{total}   ", end="", flush=True)
    if done >= total:
        print()


def _need_key() -> str:
    api_key = get_api_key()
    if not api_key:
        print("Error: set YOUTUBE_API_KEY (or put it in a .env file).")
        print("Tip: `python cli.py study demo` needs no keys at all.")
        raise SystemExit(1)
    if not get_anthropic_key():
        print("Note: ANTHROPIC_API_KEY is not set. Extraction will try an `ant auth login`")
        print("      profile instead; if that is missing too, the run will fail.\n")
    return api_key


def _print_cost(report: dict) -> None:
    quota, usage = report["quota"], report["usage"]
    print(f"   Quota: {quota['units']} / {quota['daily_free_tier']:,} units · "
          f"Model: {usage['requests']} requests, ~${usage['estimated_cost_usd']:.2f}")
    if usage.get("failed_requests"):
        print(f"   {usage['failed_requests']} request(s) came back unusable and were skipped.")


def _sample_note(report: dict) -> str:
    return "  (sample data)" if report.get("demo") else ""


def print_study(report: dict) -> None:
    study = report["study"]
    _header(study["label"] + _sample_note(report))
    print(f"   {len(study['channels'])} channels · {study['videos_sampled']} videos · "
          f"{study['comments_sampled']:,} comments sampled")
    print(f"   {study['items_extracted']:,} items extracted → "
          f"{study['distinct_statements']:,} distinct statements · "
          f"{study['spam_filtered']:,} spam filtered")
    _print_cost(report)

    _header("Content gaps")
    if not report["content_gaps"]:
        print("   No gaps surfaced.")
    for index, gap in enumerate(report["content_gaps"][:10], start=1):
        flag = {"none": "UNSERVED", "partial": "PARTIAL ", "covered": "COVERED "}[gap["coverage"]]
        print(f"\n{index:2}. [{flag}] {gap['title']}")
        print(f"    {gap['count']} comments · {gap['likes']:,} likes · "
              f"{gap['channel_spread']} channels · gap score {gap['gap_score']}")
        print(_wrap(gap["description"], indent="    "))
        if gap["closest_video"]:
            print(f"    Closest existing: \"{gap['closest_video']['title']}\"")
        if gap["examples"]:
            print(f"    “{gap['examples'][0]['quote'][:150]}”")

    if report.get("rising"):
        _header("Rising")
        for row in report["rising"][:6]:
            unit = "day" if row["window_days"] == 1 else "days"
            print(f"   {row['lift']:>4.1f}x  {row['title']}  "
                  f"({row['recent']}/{row['total']} in the last {row['window_days']} {unit})")

    overlap = report.get("audience_overlap", {})
    if overlap.get("nodes"):
        _header("Audience overlap")
        for node in overlap["nodes"]:
            print(f"   {node['channel'][:34]:<34} {node['commenters']:>6,} commenters · "
                  f"{node['exclusive_pct']:>5.1f}% exclusive")
        if overlap.get("edges"):
            print()
            for edge in overlap["edges"][:6]:
                print(f"   {edge['source'][:24]:<24} ↔ {edge['target'][:24]:<24} "
                      f"{edge['shared']:>5,} shared ({edge['jaccard']:.3f} Jaccard)")

    if report.get("products"):
        _header("Products by share of voice")
        for row in report["products"][:10]:
            stance = f"{row['net_stance']:+.2f}"
            print(f"   {row['product'][:30]:<30} {row['mentions']:>5} mentions · "
                  f"net {stance} · {row['channel_spread']} channels")

    if report.get("trust"):
        _header("Trust signals by channel")
        for row in report["trust"][:10]:
            print(f"   {row['channel'][:30]:<30} ratio {row['trust_ratio']:.2f} · "
                  f"{row['purchase_intent']} intent · "
                  f"{row['sponsorship_skepticism']} sceptical")

    if report.get("vocabulary"):
        _header("Audience vocabulary")
        terms = ", ".join(f"{row['term']} ({row['count']})" for row in report["vocabulary"][:14])
        print(_wrap(terms))

    _print_caveats(report)


def _print_caveats(report: dict) -> None:
    _header("Caveats")
    for caveat in report["caveats"]:
        print(textwrap.fill(caveat, width=74, initial_indent="   • ", subsequent_indent="     "))


def print_video(report: dict) -> None:
    video, summary = report["video"], report["summary"]
    _header(f"{video['title']}  —  {video['channel']}{_sample_note(report)}")
    print(f"   {video['view_count']:,} views · {video['like_count']:,} likes · "
          f"{video['comment_count']:,} comments")
    print(f"   {summary['comments_analyzed']} analysed → {summary['items_extracted']} items, "
          f"{summary['spam_filtered']} spam filtered")
    counts = ", ".join(f"{k} {v}" for k, v in summary["counts_by_kind"].items())
    if counts:
        print(f"   {counts}")
    _print_cost(report)

    if report.get("questions"):
        _header("Top unanswered questions")
        for index, row in enumerate(report["questions"][:8], start=1):
            print(f"{index:2}. {row['question']}  ({row['asked_by']} asked · "
                  f"{row['likes']:,} likes)")
            if row.get("example"):
                print(f"    “{row['example'][:140]}”")

    for kind, label in (("complaint", "Complaints"), ("confusion", "Confusion"),
                        ("correction", "Factual pushback"), ("request", "Requests"),
                        ("praise", "What worked")):
        themes = report.get("themes", {}).get(kind, [])
        if not themes:
            continue
        _header(label)
        for theme in themes[:5]:
            print(f"   • {theme['title']}  ({theme['count']} comments · "
                  f"{theme['likes']:,} likes)")
            print(_wrap(theme["description"], indent="     "))

    if report.get("timestamps"):
        _header("Moments the audience reacted to")
        for moment in report["timestamps"][:8]:
            print(f"   {moment['timestamp']:>8}  {moment['count']:>4} mentions · "
                  f"{moment['likes']:,} likes")
            if moment["examples"]:
                print(f"             “{moment['examples'][0]['quote'][:120]}”")

    if report.get("products"):
        _header("Products mentioned")
        for row in report["products"][:8]:
            print(f"   {row['product'][:30]:<30} {row['mentions']:>4} mentions · "
                  f"net {row['net_stance']:+.2f}")

    _print_caveats(report)


def _studies_per_day(estimate: dict) -> str:
    if estimate["studies_per_day"]:
        return f"{estimate['studies_per_day']} studies per day on the free tier"
    return "more than the free tier allows in a day"


def cmd_study(args) -> int:
    from app.demo import demo_study
    from app.niche import gap_rows

    refs = [part.strip() for ref in args.channels for part in ref.split(",") if part.strip()]
    if len(refs) == 1 and refs[0].strip().lower() == "demo":
        report = demo_study()
    else:
        api_key = _need_key()
        preview = estimate_quota(len(refs), args.videos, args.comments)
        print(f"\nPlanned: {len(refs)} channels × {args.videos} videos × "
              f"{args.comments} comments = {preview['videos']} videos")
        print(f"Estimated YouTube quota: {preview['estimated_units']} units "
              f"({_studies_per_day(preview)})\n")

        from app.niche import run_study

        try:
            report = run_study(
                api_key, refs,
                videos_per_channel=args.videos,
                comments_per_video=args.comments,
                sort_by="time" if args.sort == "latest" else "relevance",
                label=args.label or "",
                progress=_progress,
            )
        except (YouTubeError, ExtractionError) as exc:
            print(f"\nError: {exc}")
            return 1

    print_study(report)
    _write_outputs(args, report, rows=gap_rows(report.get("content_gaps", [])))
    return 0


def cmd_video(args) -> int:
    from app.demo import demo_video_report

    if args.url.strip().lower() == "demo":
        report = demo_video_report()
    else:
        api_key = _need_key()
        from app.analysis import analyze_video

        try:
            report = analyze_video(
                api_key, args.url,
                max_comments=args.comments,
                sort_by="time" if args.sort == "latest" else "relevance",
            )
        except (YouTubeError, ExtractionError) as exc:
            print(f"\nError: {exc}")
            return 1

    print_video(report)
    _write_outputs(args, report, rows=report.get("questions", []))
    return 0


def cmd_estimate(args) -> int:
    result = estimate_quota(args.channels, args.videos, args.comments)
    _header("Quota estimate")
    print(f"   {args.channels} channels × {args.videos} videos = {result['videos']} videos")
    print(f"   {args.comments} comments per video\n")
    for endpoint, calls in result["breakdown"].items():
        print(f"   {endpoint:<22} {calls:>6} calls")
    print(f"\n   Total: {result['estimated_units']} units of "
          f"{result['daily_free_tier']:,}/day")
    print(f"   That is {_studies_per_day(result)}.")
    return 0


def _write_outputs(args, report: dict, rows: list[dict]) -> None:
    if getattr(args, "json", None):
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
        print(f"\nFull report written to {args.json}")
    if getattr(args, "csv", None) and rows:
        with open(args.csv, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Table written to {args.csv}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-channel YouTube audience research.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    study = sub.add_parser("study", help="Run a cross-channel niche study")
    study.add_argument("channels", nargs="+", help="Channel URLs, @handles, IDs, or 'demo'")
    study.add_argument("--videos", type=int, default=8, help="Videos per channel (default 8)")
    study.add_argument("--comments", type=int, default=300, help="Comments per video (default 300)")
    study.add_argument("--sort", choices=["latest", "top"], default="latest",
                       help="Comment sampling order; 'latest' is less biased for research")
    study.add_argument("--label", help="Name for this study")
    study.add_argument("--json", metavar="FILE", help="Write the full report as JSON")
    study.add_argument("--csv", metavar="FILE", help="Write content gaps as CSV")
    study.set_defaults(func=cmd_study)

    video = sub.add_parser("video", help="Report on one video's comments")
    video.add_argument("url", help="Video URL/ID, or 'demo'")
    video.add_argument("--comments", type=int, default=500, help="Comments to read (default 500)")
    video.add_argument("--sort", choices=["latest", "top"], default="top",
                       help="Comment order (default 'top')")
    video.add_argument("--json", metavar="FILE", help="Write the full report as JSON")
    video.add_argument("--csv", metavar="FILE", help="Write the unanswered questions as CSV")
    video.set_defaults(func=cmd_video)

    est = sub.add_parser("estimate", help="Predict a study's quota cost")
    est.add_argument("--channels", type=int, required=True, help="Number of channels")
    est.add_argument("--videos", type=int, default=8, help="Videos per channel (default 8)")
    est.add_argument("--comments", type=int, default=300, help="Comments per video (default 300)")
    est.set_defaults(func=cmd_estimate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
