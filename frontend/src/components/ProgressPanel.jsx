export default function ProgressPanel({ status, messages }) {
  return (
    <div className="card">
      <p className="status-line">
        <span className="spinner" aria-hidden="true" />
        Status: <strong>{status}</strong>
      </p>

      {messages.length > 0 && (
        <ul>
          {messages.map((m, i) => (
            <li key={i}>{typeof m === "string" ? m : JSON.stringify(m)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}