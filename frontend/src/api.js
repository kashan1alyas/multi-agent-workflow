const API_BASE = "http://localhost:8000";

async function request(path, options) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, options);
  } catch (err) {
    throw new Error(
      "Cannot reach the backend. Is uvicorn running on port 8000?",
      { cause: err }
    );
  }

  if (!res.ok) {
    let message = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) {
        message =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
      }
    } catch {
      // response body was not JSON; keep the status message
    }
    throw new Error(message);
  }

  return res.json();
}

export function startJob(topic, maxQuestions) {
  return request("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, max_questions: maxQuestions }),
  });
}

export function getJob(jobId) {
  return request(`/api/jobs/${jobId}`);
}