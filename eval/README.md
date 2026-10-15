# Report evaluation harness

Run the experiment from the repository root:

```powershell
python eval\run_eval.py
```

The harness lists an estimated LLM-call count before it starts and waits for
Enter. The estimate assumes a typical one-pass run (four single-agent actions;
one planning/research/write pass per pipeline section; and, for `full`, one
verification call per section plus the report Editor). Actual calls vary with
searches, review revisions, and verifier URL batching. Use `--topics N` to run
only the first N topics. Each run uses at most three sections. Pipeline
conditions share the topic's plan file. Existing condition report files are
skipped so interrupted runs can resume. On a daily-quota error, the harness
stops and lists the runs left to complete.

Outputs are saved under `eval/`: reports and metrics, `results.md`, a shuffled
`scoring_sheet.csv`, and its separate `answer_key.csv`. The scoring sheet does
not contain condition labels or automated Verifier verdicts; row IDs are
randomized so their order does not reveal the condition.

**Complete the blind scoring in `scoring_sheet.csv` before opening
`answer_key.csv`.** For each sentence, fill `supported` with `yes`, `partly`,
or `no` (and optionally add notes). Only after scoring is complete, run:

```powershell
python eval\score.py
```

This joins ratings to conditions and writes `eval/scores.md`, including counts
and percentages for each rating and the mean number of sentences per report.
