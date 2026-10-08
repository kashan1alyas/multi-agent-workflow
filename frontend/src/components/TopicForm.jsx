function TopicForm({ onSubmit, disabled }) {
  const handleSubmit = (e) => {
    e.preventDefault();
    const topic = e.target.topic.value;
    const maxQuestions = e.target.max_questions.value;
    onSubmit(topic, maxQuestions);
  };
  return (
    <form onSubmit={handleSubmit} disabled={disabled}>
      <label>
        Topic:
        <input type='text' name='topic' required />
      </label>
      <label>
        Max Questions:
        <input type='number' name='max_questions' min='1' max='5' step='1' defaultValue={2} required />
      </label>
      <button type='submit'>Submit</button>
    </form>
  );
}
export default TopicForm;
