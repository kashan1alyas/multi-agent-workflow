import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import cache as cache_store
from app.config import (
    CACHE_DIR,
    FRONTEND_ORIGIN,
    MAX_RUNS_PER_DAY,
    MAX_RUNS_PER_IP_PER_DAY,
    MAX_SECTIONS_LIMIT,
    MAX_TOPIC_LENGTH,
    RUN_TIMEOUT_SECONDS,
)
from app.pipeline import run_pipeline
from app.report import build_markdown
from app.schemas import Report

_original_cache_filename = cache_store._cache_filename


def _configured_cache_filename(key: str) -> str:
    return str(CACHE_DIR / Path(_original_cache_filename(key)).name)


cache_store._cache_filename = _configured_cache_filename

app = FastAPI(
    title="Dossier Agents",
    description="Multi-agent research where every claim is cited and checked.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN else [],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

_jobs: dict[str, dict[str, Any]] = {}
_active_ips: set[str] = set()
_daily_runs: dict[str, int] = {}
_daily_run_date = datetime.now(timezone.utc).date()
_app_daily_runs = 0
_jobs_lock = threading.Lock()


@app.exception_handler(RequestValidationError)
async def invalid_request_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Request validation failed."},
    )


@app.exception_handler(HTTPException)
async def safe_http_error_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": message, "detail": message},
        headers=exc.headers,
    )


@app.get("/health")
def health() -> dict[str, str | int]:
    return {"status": "ok", "max_sections": MAX_SECTIONS_LIMIT}


@app.get("/api/limits")
def get_limits() -> dict[str, int]:
    return {
        "max_sections": MAX_SECTIONS_LIMIT,
        "max_topic_length": MAX_TOPIC_LENGTH,
    }


def _reset_daily_counters_if_needed() -> None:
    global _daily_run_date, _app_daily_runs
    today = datetime.now(timezone.utc).date()
    if today != _daily_run_date:
        _daily_runs.clear()
        _daily_run_date = today
        _app_daily_runs = 0


def _reserve_run(client_ip: str) -> None:
    global _app_daily_runs
    with _jobs_lock:
        _reset_daily_counters_if_needed()
        if client_ip in _active_ips:
            raise HTTPException(
                status_code=429,
                detail="A research run is already active for this IP address.",
            )
        if _daily_runs.get(client_ip, 0) >= MAX_RUNS_PER_IP_PER_DAY:
            raise HTTPException(
                status_code=429,
                detail="This IP address has reached its daily run limit.",
            )
        if _app_daily_runs >= MAX_RUNS_PER_DAY:
            raise HTTPException(
                status_code=429,
                detail="The application has reached its daily run limit.",
            )
        _active_ips.add(client_ip)
        _daily_runs[client_ip] = _daily_runs.get(client_ip, 0) + 1
        _app_daily_runs += 1


def _mark_timed_out(job: dict[str, Any]) -> None:
    job["timed_out"] = True
    job["status"] = "failed"
    job["error"] = "Research run exceeded the time limit."


def _run_job(job_id: str, topic: str, max_sections: int, client_ip: str) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = "running"
        job["progress"].append("Pipeline started")

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        result = run_pipeline(topic=topic, max_sections=max_sections)
        if result is None:
            raise RuntimeError("Pipeline did not produce a report.")
        serialized_result = (
            result.model_dump()
            if hasattr(result, "model_dump")
            else result
        )
        with _jobs_lock:
            job = _jobs[job_id]
            if time.monotonic() - job["started_at"] >= RUN_TIMEOUT_SECONDS:
                _mark_timed_out(job)
            else:
                job["result"] = serialized_result
                job["progress"].append("Pipeline finished")
                job["status"] = "done"
    except Exception:
        with _jobs_lock:
            job = _jobs[job_id]
            if time.monotonic() - job["started_at"] >= RUN_TIMEOUT_SECONDS:
                _mark_timed_out(job)
            else:
                job["error"] = "Research run failed. Please try again later."
                job["progress"].append("Pipeline failed")
                job["status"] = "failed"
    finally:
        with _jobs_lock:
            _active_ips.discard(client_ip)


def _job_request_error(message: str, field: str, limit: int) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": message, "field": field, "limit": limit},
    )


@app.post("/api/jobs", status_code=202)
async def create_job(http_request: Request) -> Any:
    global _app_daily_runs
    try:
        payload = await http_request.json()
    except ValueError:
        return _job_request_error(
            "Request body must be valid JSON.", "request", MAX_SECTIONS_LIMIT
        )
    if not isinstance(payload, dict):
        return _job_request_error(
            "Request body must be a JSON object.", "request", MAX_SECTIONS_LIMIT
        )

    topic = payload.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        return _job_request_error(
            "Topic is required and must not be empty.", "topic", MAX_TOPIC_LENGTH
        )
    topic = topic.strip()
    if len(topic) > MAX_TOPIC_LENGTH:
        return _job_request_error(
            f"Topic must be {MAX_TOPIC_LENGTH} characters or fewer.",
            "topic",
            MAX_TOPIC_LENGTH,
        )

    max_sections = payload.get("max_sections", 2)
    if type(max_sections) is not int:
        return _job_request_error(
            "max_sections must be an integer.",
            "max_sections",
            MAX_SECTIONS_LIMIT,
        )
    if max_sections < 1 or max_sections > MAX_SECTIONS_LIMIT:
        return _job_request_error(
            f"max_sections must be between 1 and {MAX_SECTIONS_LIMIT}",
            "max_sections",
            MAX_SECTIONS_LIMIT,
        )

    client_ip = http_request.client.host if http_request.client else "unknown"
    _reserve_run(client_ip)
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress": [],
            "result": None,
            "error": None,
            "timed_out": False,
            "started_at": time.monotonic(),
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, topic, max_sections, client_ip),
        daemon=True,
    )
    try:
        thread.start()
    except RuntimeError:
        with _jobs_lock:
            _jobs.pop(job_id, None)
            _active_ips.discard(client_ip)
            _daily_runs[client_ip] -= 1
            _app_daily_runs -= 1
        raise HTTPException(
            status_code=503,
            detail="Unable to start the research run.",
        ) from None
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if (
            job["status"] in ("queued", "running")
            and time.monotonic() - job["started_at"] >= RUN_TIMEOUT_SECONDS
        ):
            _mark_timed_out(job)
        if job["timed_out"]:
            raise HTTPException(
                status_code=504,
                detail="Research run exceeded the time limit.",
            )
        return {
            "status": job["status"],
            "progress": list(job["progress"]),
            "result": job["result"],
            "error": job["error"],
        }


@app.post("/api/reports/markdown")
def report_markdown(report: Report) -> dict[str, str]:
    return {"markdown": build_markdown(report, include_empty=False)}


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIST, html=True, check_dir=False),
    name="frontend",
)
