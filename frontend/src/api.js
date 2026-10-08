const API_BASE = "http://localhost:8000";

async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    throw new Error(
      "Cannot reach the backend. Is uvicorn running on port 8000?",
      { cause: err },
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail || response.statusText || "HTTP " + response.status;
    throw new Error(detail);
  }
  return response.json();
}

export async function startJob(topic, maxQuestions = 3) {
  return request(API_BASE + '/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, max_questions: maxQuestions }),
  });
}

export async function getJob(jobId) {
  return request(API_BASE + '/api/jobs/' + jobId);
}
