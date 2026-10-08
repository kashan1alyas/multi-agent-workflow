function ProgressPanel({ status, messages }) {
  return (
    <div>
      <strong>Status: {status}</strong>
      <ul>
        {messages.map((msg, i) => (
          <li key={i}>{msg}</li>
        ))}
      </ul>
    </div>
  );
}
export default ProgressPanel;

