import { useState } from "react";

export default function TopicForm({ onSubmit, disabled }) {
  const [topic, setTopic] = useState("");
  const [maxQuestions, setMaxQuestions] = useState(2);

  const handleSubmit = (e) => {
    e.preventDefault();
    const questionCount = Math.min(20, Math.max(1, Number(maxQuestions) || 1));
    onSubmit(topic.trim(), questionCount);
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
        Max questions (1 to 20)
        <input
          type="number"
          min="1"
          max="20"
          value={maxQuestions}
          onChange={(e) => setMaxQuestions(e.target.value)}
        />
      </label>
      {Number(maxQuestions) > 5 && (
        <p>Large runs take longer and use more API quota.</p>
      )}

      <button type="submit" disabled={disabled || !topic.trim()}>
        {disabled ? "Researching..." : "Start research"}
      </button>
    </form>
  );
}