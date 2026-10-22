import { useState } from "react";

export default function TopicForm({ onSubmit, disabled, maxSections, error }) {
  const [topic, setTopic] = useState("");
  const [sectionCount, setSectionCount] = useState(2);
  const displayedSections = maxSections == null
    ? sectionCount
    : Math.min(maxSections, Math.max(1, Number(sectionCount) || 1));

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(topic.trim(), displayedSections);
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <label>
        Research topic
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. Solar panel adoption in Pakistan"
        />
      </label>

      <label>
        Max sections (1 to {maxSections ?? "…"})
        <input
          type="number"
          min="1"
          max={maxSections ?? undefined}
          value={displayedSections}
          onChange={(e) => setSectionCount(e.target.value)}
        />
      </label>

      {error && <p className="error" role="alert">{error}</p>}

      <button
        type="submit"
        disabled={disabled || maxSections == null || !topic.trim()}
      >
        {disabled ? "Researching..." : "Start research"}
      </button>
    </form>
  );
}