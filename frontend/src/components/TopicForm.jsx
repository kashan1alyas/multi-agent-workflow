import { useState } from "react";

export default function TopicForm({ onSubmit, disabled }) {
  const [topic, setTopic] = useState("");
  const [maxQuestions, setMaxQuestions] = useState(2);

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(topic.trim(), Number(maxQuestions));
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
        Max questions (1 to 5)
        <input
          type="number"
          min="1"
          max="5"
          value={maxQuestions}
          onChange={(e) => setMaxQuestions(e.target.value)}
        />
      </label>

      <button type="submit" disabled={disabled || !topic.trim()}>
        {disabled ? "Researching..." : "Start research"}
      </button>
    </form>
  );
}