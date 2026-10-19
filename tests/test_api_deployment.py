from datetime import datetime, timezone
from threading import Event
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import api


@pytest.fixture
def client():
    with api._jobs_lock:
        api._jobs.clear()
        api._active_ips.clear()
        api._daily_runs.clear()
        api._daily_run_date = datetime.now(timezone.utc).date()
        api._app_daily_runs = 0
    with TestClient(api.app) as test_client:
        yield test_client
    with api._jobs_lock:
        api._jobs.clear()
        api._active_ips.clear()
        api._daily_runs.clear()
        api._app_daily_runs = 0


def test_topic_length_limit_returns_400_without_echoing_input(client):
    secret_marker = "GEMINI_API_KEY=TEST_SECRET_VALUE"
    topic = f"{secret_marker}{'x' * (api.MAX_TOPIC_LENGTH + 1)}"

    response = client.post(
        "/api/jobs",
        json={"topic": topic, "max_sections": 2},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": f"Topic must be {api.MAX_TOPIC_LENGTH} characters or fewer.",
        "field": "topic",
        "limit": api.MAX_TOPIC_LENGTH,
    }
    assert secret_marker not in response.text
    assert "TEST_SECRET_VALUE" not in response.text


@pytest.mark.parametrize(
    ("payload", "expected_error", "field", "limit"),
    [
        (
            {},
            "Topic is required and must not be empty.",
            "topic",
            api.MAX_TOPIC_LENGTH,
        ),
        (
            {"topic": "   ", "max_sections": 2},
            "Topic is required and must not be empty.",
            "topic",
            api.MAX_TOPIC_LENGTH,
        ),
        (
            {"topic": "Valid topic", "max_sections": "2"},
            "max_sections must be an integer.",
            "max_sections",
            api.MAX_SECTIONS,
        ),
        (
            {"topic": "Valid topic", "max_sections": 1.5},
            "max_sections must be an integer.",
            "max_sections",
            api.MAX_SECTIONS,
        ),
        (
            {"topic": "Valid topic", "max_sections": True},
            "max_sections must be an integer.",
            "max_sections",
            api.MAX_SECTIONS,
        ),
        (
            {"topic": "Valid topic", "max_sections": 0},
            f"max_sections must be between 1 and {api.MAX_SECTIONS}.",
            "max_sections",
            api.MAX_SECTIONS,
        ),
        (
            {"topic": "Valid topic", "max_sections": api.MAX_SECTIONS + 1},
            f"max_sections must be between 1 and {api.MAX_SECTIONS}.",
            "max_sections",
            api.MAX_SECTIONS,
        ),
    ],
)
def test_job_validation_errors_are_specific(
    client, monkeypatch, payload, expected_error, field, limit
):
    pipeline = Mock(side_effect=AssertionError("Pipeline must not be called"))
    monkeypatch.setattr(api, "run_pipeline", pipeline)

    response = client.post("/api/jobs", json=payload)

    assert response.status_code == 400
    assert response.json() == {
        "error": expected_error,
        "field": field,
        "limit": limit,
    }
    pipeline.assert_not_called()


def test_per_ip_daily_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_RUNS_PER_IP_PER_DAY", 1)
    worker_finished = Event()

    def finish_without_running_pipeline(
        job_id: str, topic: str, max_sections: int, client_ip: str
    ) -> None:
        with api._jobs_lock:
            api._active_ips.discard(client_ip)
        worker_finished.set()

    monkeypatch.setattr(api, "_run_job", finish_without_running_pipeline)

    first = client.post(
        "/api/jobs",
        json={"topic": "A valid test topic", "max_sections": 2},
    )
    assert first.status_code == 202
    assert worker_finished.wait(timeout=2)

    second = client.post(
        "/api/jobs",
        json={"topic": "A second valid test topic", "max_sections": 2},
    )

    assert second.status_code == 429
    assert "daily run limit" in second.json()["error"]


def test_health_endpoint_is_available(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "max_sections": api.MAX_SECTIONS}


def test_job_succeeds_with_matching_max_sections_field(client, monkeypatch, tmp_path):
    pipeline_finished = Event()

    def fake_pipeline(*, topic: str, max_sections: int) -> dict[str, str | int]:
        pipeline_finished.set()
        return {"topic": topic, "max_sections": max_sections}

    pipeline = Mock(side_effect=fake_pipeline)
    monkeypatch.setattr(api, "run_pipeline", pipeline)
    monkeypatch.setattr(api, "CACHE_DIR", tmp_path / "cache")

    response = client.post(
        "/api/jobs",
        json={"topic": "A valid test topic", "max_sections": 2},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert pipeline_finished.wait(timeout=2)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.01)

    assert job["status"] == "done"
    assert job["result"] == {"topic": "A valid test topic", "max_sections": 2}
    pipeline.assert_called_once_with(topic="A valid test topic", max_sections=2)


def test_max_sections_is_capped_at_three(client):
    response = client.post(
        "/api/jobs",
        json={"topic": "A valid test topic", "max_sections": 4},
    )

    assert response.status_code == 400
    assert response.json()["field"] == "max_sections"
    assert response.json()["limit"] == 3


def test_expired_run_returns_504(client, monkeypatch):
    monkeypatch.setattr(api, "RUN_TIMEOUT_SECONDS", 1)
    with api._jobs_lock:
        api._jobs["expired"] = {
            "status": "running",
            "progress": [],
            "result": None,
            "error": None,
            "timed_out": False,
            "started_at": time.monotonic() - 2,
        }

    response = client.get("/api/jobs/expired")

    assert response.status_code == 504
    assert response.json()["error"] == "Research run exceeded the time limit."
