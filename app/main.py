"""FastAPI web app for YouTube Sentiment Insights."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .analysis import analyze_video
from .config import get_api_key
from .demo import demo_report
from .youtube import YouTubeError

app = FastAPI(title="YouTube Sentiment Insights", version="2.0.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Simple in-memory cache of the most recent reports (also powers export).
_report_cache: dict[str, dict] = {}
_CACHE_LIMIT = 20


def _cache_report(report: dict) -> None:
    video_id = report["video"]["video_id"]
    _report_cache[video_id] = report
    while len(_report_cache) > _CACHE_LIMIT:
        _report_cache.pop(next(iter(_report_cache)))


@app.get("/api/status")
def status() -> dict:
    """Whether a YouTube API key is configured (demo mode otherwise)."""
    return {"api_key_configured": get_api_key() is not None}


@app.get("/api/analyze")
def analyze(
    url: str = Query(..., description="YouTube video URL or ID"),
    max_comments: int = Query(500, ge=10, le=5000),
    sort_by: str = Query("relevance", pattern="^(relevance|time)$"),
    include_transcript: bool = Query(True),
) -> dict:
    if url.strip().lower() == "demo":
        report = demo_report(max_comments=min(max_comments, 120))
        _cache_report(report)
        return report

    api_key = get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "No YouTube API key configured. Set the YOUTUBE_API_KEY environment "
                "variable (or put it in a .env file), or type 'demo' to explore sample data."
            ),
        )
    try:
        report = analyze_video(
            api_key,
            url,
            max_comments=max_comments,
            sort_by=sort_by,
            include_transcript=include_transcript,
        )
    except YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _cache_report(report)
    return report


@app.get("/api/compare")
def compare(
    url_a: str = Query(...),
    url_b: str = Query(...),
    max_comments: int = Query(300, ge=10, le=2000),
) -> dict:
    """Analyze two videos and return both reports for side-by-side comparison."""
    reports = []
    for url in (url_a, url_b):
        if url.strip().lower() == "demo":
            reports.append(demo_report(max_comments=min(max_comments, 120)))
            continue
        api_key = get_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="No YouTube API key configured.")
        try:
            reports.append(
                analyze_video(api_key, url, max_comments=max_comments, include_transcript=False)
            )
        except YouTubeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    for report in reports:
        _cache_report(report)
    return {"a": reports[0], "b": reports[1]}


@app.get("/api/export/{video_id}.csv")
def export_csv(video_id: str) -> Response:
    report = _report_cache.get(video_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found — analyze the video first.")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["author", "text", "likes", "reply_count", "published_at", "label", "compound"],
    )
    writer.writeheader()
    for comment in report["comments"]:
        writer.writerow({key: comment[key] for key in writer.fieldnames})
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={video_id}_sentiment.csv"},
    )


@app.get("/api/export/{video_id}.json")
def export_json(video_id: str) -> Response:
    report = _report_cache.get(video_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found — analyze the video first.")
    return Response(
        content=json.dumps(report, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={video_id}_report.json"},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
