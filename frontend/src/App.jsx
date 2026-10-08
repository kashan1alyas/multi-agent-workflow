import { useEffect, useRef, useState } from "react";
import { startJob, getJob } from "./api";
import TopicForm from "./components/TopicForm";
import ProgressPanel from "./components/ProgressPanel";
import ReportView from "./components/ReportView";
import "./App.css";

export default function App() {
  const [status, setStatus] = useState("idle");
  const [messages, setMessages] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const timerRef = useRef(null);

  const stopPolling = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  // Stop polling if the component unmounts
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const handleReset = () => {
    stopPolling();
    setStatus("idle");
    setMessages([]);
    setResult(null);
    setError("");
  };

  const handleSubmit = async (topic, maxQuestions) => {
    if (timerRef.current) return; // a poll is already running

    setError("");
    setResult(null);
    setMessages([]);
    setStatus("queued");

    try {
      const { job_id } = await startJob(topic, maxQuestions);

      timerRef.current = setInterval(async () => {
        try {
          const job = await getJob(job_id);
          setStatus(job.status);
          setMessages(job.messages || job.progress || []);

          if (job.status === "done") {
            stopPolling();
            setResult(job.result);
          } else if (job.status === "failed") {
            stopPolling();
            setError(job.error || "The job failed.");
          }
        } catch (e) {
          stopPolling();
          setStatus("failed");
          setError(e.message);
        }
      }, 2000);
    } catch (e) {
      setStatus("failed");
      setError(e.message);
    }
  };

  const busy = status === "queued" || status === "running";

  return (
    <div className="container">
      <h1>Market Research Agents</h1>

      <TopicForm onSubmit={handleSubmit} disabled={busy} />

      {error && <div className="error">{error}</div>}

      {busy && <ProgressPanel status={status} messages={messages} />}

      {status === "done" && result && <ReportView result={result} />}

      {(status === "done" || status === "failed") && (
        <button type="button" className="secondary" onClick={handleReset}>
          Start new research
        </button>
      )}
    </div>
  );
}