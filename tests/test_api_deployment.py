from datetime import datetime, timezone
from threading import Event
import time

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
        json={"topic": topic, "max_questions": 2},
    )

    assert response.status_code == 400
    assert secret_marker not in response.text
    assert "TEST_SECRET_VALUE" not in response.text


def test_per_ip_daily_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_RUNS_PER_IP_PER_DAY", 1)
    worker_finished = Event()

    def finish_without_running_pipeline(
        job_id: str, topic: str, max_questions: int, client_ip: str
    ) -> None:
        with api._jobs_lock:
            api._active_ips.discard(client_ip)
        worker_finished.set()

    monkeypatch.setattr(api, "_run_job", finish_without_running_pipeline)

    first = client.post(
        "/api/jobs",
        json={"topic": "A valid test topic", "max_questions": 2},
    )
    assert first.status_code == 202
    assert worker_finished.wait(timeout=2)

    second = client.post(
        "/api/jobs",
        json={"topic": "A second valid test topic", "max_questions": 2},
    )

    assert second.status_code == 429
    assert "daily run limit" in second.json()["error"]


def test_health_endpoint_is_available(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_max_sections_is_capped_at_three(client):
    response = client.post(
        "/api/jobs",
        json={"topic": "A valid test topic", "max_questions": 4},
    )

    assert response.status_code == 400


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
