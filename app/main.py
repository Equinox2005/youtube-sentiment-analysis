"""FastAPI app for YouTube Audience Research."""

from __future__ import annotations

import csv
import io
import json
import queue
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .analysis import analyze_video
from .config import get_anthropic_key, get_api_key, get_map_model, get_reduce_model, use_batch_api
from .demo import demo_study, demo_video_report
from .extraction import ExtractionError
from .niche import gap_rows, run_study
from .youtube import YouTubeError, estimate_quota

app = FastAPI(title="YouTube Audience Research", version=__version__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# In-memory store of recent reports; also what the export endpoints read from.
# Streamed runs store from worker threads, hence the lock.
_reports: dict[str, dict] = {}
_reports_lock = threading.Lock()
_CACHE_LIMIT = 20


def _store(report: dict) -> str:
    report_id = report.get("video", {}).get("video_id") or uuid.uuid4().hex[:12]
    report["_id"] = report_id
    with _reports_lock:
        _reports[report_id] = report
        while len(_reports) > _CACHE_LIMIT:
            _reports.pop(next(iter(_reports)))
    return report_id


def _split_channels(raw: str) -> list[str]:
    refs = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
    if not refs:
        raise HTTPException(status_code=400, detail="Provide at least one channel.")
    if len(refs) > 25:
        raise HTTPException(status_code=400, detail="A study is limited to 25 channels.")
    return refs


def _require_youtube_key() -> str:
    key = get_api_key()
    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                "No YouTube API key configured. Set YOUTUBE_API_KEY (or put it in a "
                ".env file), or use 'demo' to explore a pre-computed study."
            ),
        )
    return key


def _stream(work) -> StreamingResponse:
    """Run `work(progress)` on a thread and stream progress as server-sent events."""
    events: queue.Queue = queue.Queue()

    def progress(stage: str, done: int, total: int) -> None:
        events.put({"type": "progress", "stage": stage, "done": done, "total": total})

    def run() -> None:
        try:
            events.put({"type": "done", "report": work(progress)})
        except HTTPException as exc:
            events.put({"type": "error", "detail": exc.detail})
        except (YouTubeError, ExtractionError) as exc:
            events.put({"type": "error", "detail": str(exc)})
        except Exception as exc:  # pragma: no cover - unexpected failure
            events.put({"type": "error", "detail": f"Unexpected error: {exc}"})

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            event = events.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("done", "error"):
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status")
def status() -> dict:
    return {
        "youtube_key_configured": get_api_key() is not None,
        "anthropic_key_configured": get_anthropic_key() is not None,
        "map_model": get_map_model(),
        "reduce_model": get_reduce_model(),
        "batch_api": use_batch_api(),
    }


@app.get("/api/estimate")
def estimate(
    channels: int = Query(..., ge=1, le=25),
    videos_per_channel: int = Query(8, ge=1, le=50),
    comments_per_video: int = Query(300, ge=10, le=1000),
) -> dict:
    """Predict a study's YouTube quota cost before spending any of it."""
    return estimate_quota(channels, videos_per_channel, comments_per_video)


@app.get("/api/study")
def study(
    channels: str = Query(..., description="Comma-separated channel URLs, @handles or IDs"),
    videos_per_channel: int = Query(8, ge=1, le=50),
    comments_per_video: int = Query(300, ge=10, le=1000),
    sort_by: str = Query("time", pattern="^(time|relevance)$"),
    label: str = Query(""),
) -> dict:
    """Run a niche study synchronously. Expect minutes, not seconds."""
    if channels.strip().lower() == "demo":
        report = demo_study()
        _store(report)
        return report

    api_key = _require_youtube_key()
    try:
        report = run_study(
            api_key,
            _split_channels(channels),
            videos_per_channel=videos_per_channel,
            comments_per_video=comments_per_video,
            sort_by=sort_by,
            label=label,
        )
    except (YouTubeError, ExtractionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _store(report)
    return report


@app.get("/api/study/stream")
def study_stream(
    channels: str = Query(...),
    videos_per_channel: int = Query(8, ge=1, le=50),
    comments_per_video: int = Query(300, ge=10, le=1000),
    sort_by: str = Query("time", pattern="^(time|relevance)$"),
    label: str = Query(""),
):
    """Same as /api/study, streamed with progress events."""
    if channels.strip().lower() == "demo":
        def demo_work(_progress):
            report = demo_study()
            _store(report)
            return report

        return _stream(demo_work)

    # Checked inside work() so a failure arrives as an event: the page reads this
    # stream with EventSource, which cannot see the body of a 400.
    def work(progress):
        report = run_study(
            _require_youtube_key(),
            _split_channels(channels),
            videos_per_channel=videos_per_channel,
            comments_per_video=comments_per_video,
            sort_by=sort_by,
            label=label,
            progress=progress,
        )
        _store(report)
        return report

    return _stream(work)


@app.get("/api/analyze")
def analyze(
    url: str = Query(..., description="YouTube video URL or ID"),
    max_comments: int = Query(500, ge=10, le=5000),
    sort_by: str = Query("relevance", pattern="^(relevance|time)$"),
) -> dict:
    """Report on one video's comments."""
    if url.strip().lower() == "demo":
        report = demo_video_report()
        _store(report)
        return report

    api_key = _require_youtube_key()
    try:
        report = analyze_video(api_key, url, max_comments=max_comments, sort_by=sort_by)
    except (YouTubeError, ExtractionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _store(report)
    return report


@app.get("/api/analyze/stream")
def analyze_stream(
    url: str = Query(...),
    max_comments: int = Query(500, ge=10, le=5000),
    sort_by: str = Query("relevance", pattern="^(relevance|time)$"),
):
    """Same as /api/analyze, streamed with progress events."""
    if url.strip().lower() == "demo":
        def demo_work(_progress):
            report = demo_video_report()
            _store(report)
            return report

        return _stream(demo_work)

    def work(progress):
        report = analyze_video(
            _require_youtube_key(), url, max_comments=max_comments, sort_by=sort_by,
            progress=progress,
        )
        _store(report)
        return report

    return _stream(work)


def _get_report(report_id: str) -> dict:
    with _reports_lock:
        report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found — run the analysis first.")
    return report


def _csv_response(rows: list[dict], fields: list[str], filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/{report_id}/gaps.csv")
def export_gaps(report_id: str) -> Response:
    report = _get_report(report_id)
    rows = gap_rows(report.get("content_gaps", []))
    if not rows:
        raise HTTPException(status_code=404, detail="This report has no content gaps.")
    return _csv_response(
        rows,
        ["title", "kind", "comments", "likes", "channel_spread", "coverage",
         "gap_score", "closest_video", "description"],
        f"{report_id}_content_gaps.csv",
    )


@app.get("/api/export/{report_id}/themes.csv")
def export_themes(report_id: str) -> Response:
    report = _get_report(report_id)
    rows = [
        {
            "kind": kind,
            "title": theme["title"],
            "comments": theme["count"],
            "likes": theme["likes"],
            "channel_spread": theme["channel_spread"],
            "description": theme["description"],
            "example": (theme["examples"][0]["quote"] if theme.get("examples") else ""),
        }
        for kind, themes in report.get("themes", {}).items()
        for theme in themes
    ]
    if not rows:
        raise HTTPException(status_code=404, detail="This report has no themes.")
    rows.sort(key=lambda row: row["comments"], reverse=True)
    return _csv_response(
        rows,
        ["kind", "title", "comments", "likes", "channel_spread", "description", "example"],
        f"{report_id}_themes.csv",
    )


@app.get("/api/export/{report_id}/overlap.csv")
def export_overlap(report_id: str) -> Response:
    report = _get_report(report_id)
    rows = report.get("audience_overlap", {}).get("edges", [])
    if not rows:
        raise HTTPException(status_code=404, detail="This report has no overlap data.")
    return _csv_response(
        rows,
        ["source", "target", "shared", "jaccard", "pct_of_source", "pct_of_target"],
        f"{report_id}_audience_overlap.csv",
    )


@app.get("/api/export/{report_id}.json")
def export_json(report_id: str) -> Response:
    report = _get_report(report_id)
    return Response(
        content=json.dumps(report, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={report_id}_report.json"},
    )


# The frontend is a few small files; have the browser revalidate them on every
# load so an update shows up without a hard refresh.
_NO_CACHE = {"Cache-Control": "no-cache"}


class _StaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers.update(_NO_CACHE)
        return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)


app.mount("/static", _StaticFiles(directory=STATIC_DIR), name="static")
