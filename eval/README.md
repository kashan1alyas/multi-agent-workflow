# Evaluation

This directory contains the evaluation results for the Supervisor gap-filling loop against a single-agent baseline.

## How to run the evaluation

1. Ensure the virtual environment is activated.
2. Run the pipeline with and without the `--no-supervisor` flag on the same set of questions.
3. Paste the per-condition results into `scores.md` using the template below.
3. Review the scores and note any patterns or edge cases.

## Evaluation conditions

Each condition is scored on a question-by-question basis. The final per-condition result is:
- **yes** if the behavior holds for the majority of questions,
- **partly** if it holds for some but not all questions,
- **no** if it does not hold.

| Condition | yes | partly | no |
|-----------|-----|--------|----|
| A: Enough facts returns "enough" without calling the LLM | | | |
| B: Too few facts returns new queries that differ from used ones | | | |
| C: The loop stops after 2 rounds per section | | | |
| D: The loop respects MAX_EXTRA_SEARCHES = 6 per run | | | |

## How to paste results

1. Run `python main.py "question" --pipeline` and `python main.py "question" --no-supervisor`.
2. Record whether each condition (A–D) was observed.
3. Fill in the yes/partly/no column accordingly.
4. Save the completed table as `eval/scores.md` and reference it from the README.md Results section.