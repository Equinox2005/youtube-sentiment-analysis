import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    return TestClient(app)


def test_index_serves_the_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>" in response.text
    # Revalidated on every load so an update shows up without a hard refresh.
    assert response.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"


def test_status_reports_missing_keys_and_default_models(client):
    status = client.get("/api/status").json()
    assert status["youtube_key_configured"] is False
    assert status["anthropic_key_configured"] is False
    assert status["map_model"] == status["reduce_model"] == "claude-opus-5-5"


def test_estimate(client):
    params = {"channels": 12, "videos_per_channel": 8, "comments_per_video": 500}
    assert client.get("/api/estimate", params=params).json()["estimated_units"] == 506


def test_demo_study_and_its_exports(client):
    report = client.get("/api/study", params={"channels": "demo"}).json()
    assert report["demo"] is True
    report_id = report["_id"]

    for path, media_type in [
        (f"/api/export/{report_id}/gaps.csv", "text/csv"),
        (f"/api/export/{report_id}/themes.csv", "text/csv"),
        (f"/api/export/{report_id}/overlap.csv", "text/csv"),
        (f"/api/export/{report_id}.json", "application/json"),
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith(media_type)

    gaps_csv = client.get(f"/api/export/{report_id}/gaps.csv").text
    assert gaps_csv.splitlines()[0].startswith("title,kind,comments")
    assert "Grinder-first buying guidance" in gaps_csv


def test_demo_video_report_has_no_gap_export(client):
    report = client.get("/api/analyze", params={"url": "demo"}).json()
    assert report["video"]["title"]
    assert client.get(f"/api/export/{report['_id']}/themes.csv").status_code == 200
    assert client.get(f"/api/export/{report['_id']}/gaps.csv").status_code == 404


def test_demo_stream_ends_with_the_report(client):
    response = client.get("/api/study/stream", params={"channels": "demo"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[len("data: "):]) for line in response.text.splitlines()
              if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    assert events[-1]["report"]["study"]["channels"]


def test_real_runs_need_a_youtube_key(client):
    response = client.get("/api/study", params={"channels": "@somechannel"})
    assert response.status_code == 400
    assert "YOUTUBE_API_KEY" in response.json()["detail"]

    response = client.get("/api/analyze", params={"url": "dQw4w9WgXcQ"})
    assert response.status_code == 400


def test_study_rejects_too_many_channels(client, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "not-a-real-key")
    channels = ",".join(f"@channel{i}" for i in range(26))
    response = client.get("/api/study", params={"channels": channels})
    assert response.status_code == 400
    assert "25 channels" in response.json()["detail"]


def test_unknown_report_export_is_404(client):
    assert client.get("/api/export/nope/themes.csv").status_code == 404


@pytest.mark.parametrize("args, expected", [
    (["study", "demo"], "Content gaps"),
    (["video", "demo"], "Top unanswered questions"),
    (["estimate", "--channels", "12"], "Total:"),
])
def test_cli_runs_without_keys(args, expected):
    result = subprocess.run(
        [sys.executable, "cli.py", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
