import threading
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.pipeline import run_pipeline

app = FastAPI(title="Market Research Agents API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class JobRequest(BaseModel):
    topic: str
    max_questions: int = Field(default=2, ge=1, le=20)


def _run_job(job_id: str, topic: str, max_questions: int) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = "running"
        job["progress"].append("Pipeline started")

    try:
        result = run_pipeline(topic=topic, max_sections=max_questions)
        if result is None:
            raise RuntimeError("Pipeline did not produce a report.")
        serialized_result = (
            result.model_dump()
            if hasattr(result, "model_dump")
            else result
        )
        with _jobs_lock:
            job = _jobs[job_id]
            job["result"] = serialized_result
            job["progress"].append("Pipeline finished")
            job["status"] = "done"
    except Exception as exc:
        with _jobs_lock:
            job = _jobs[job_id]
            job["error"] = str(exc) or type(exc).__name__
            job["progress"].append("Pipeline failed")
            job["status"] = "failed"


@app.post("/api/jobs")
def create_job(request: JobRequest) -> dict[str, str]:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress": [],
            "result": None,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, request.topic, request.max_questions),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "status": job["status"],
            "progress": list(job["progress"]),
            "result": job["result"],
            "error": job["error"],
        }
