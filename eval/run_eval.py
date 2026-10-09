import csv
import json
import random
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
PLANS_DIR = EVAL_DIR / "plans"
REPORTS_DIR = ROOT / "reports" / "eval"
TOPICS_FILE = EVAL_DIR / "topics.txt"
PROGRESS_FILE = EVAL_DIR / "progress.json"
CONDITIONS = (("noreview", True), ("review", False))
DAILY_QUOTA_MESSAGES = ("PerDay", "Daily free quota exhausted")
MAX_SECTIONS = 3
MAX_REVISION_ROUNDS = 2


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "topic"


def load_topics() -> list[str]:
    return [
        line.strip()
        for line in TOPICS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def report_path(topic: str, condition: str) -> Path:
    return REPORTS_DIR / f"{slugify(topic)}-{condition}.md"


def metrics_path(topic: str, condition: str) -> Path:
    return REPORTS_DIR / f"{slugify(topic)}-{condition}.json"


def expected_llm_calls(topics: list[str]) -> int:
    total = 0
    for topic in topics:
        plan_file = PLANS_DIR / f"{slugify(topic)}.json"
        pending = [
            (condition, report_path(topic, condition).exists())
            for condition, _ in CONDITIONS
        ]
        if all(exists for _, exists in pending):
            continue
        if not plan_file.exists():
            total += 1
        for condition, exists in pending:
            if exists:
                continue
            if condition == "noreview":
                total += MAX_SECTIONS * 2
            else:
                total += MAX_SECTIONS * (1 + 2 * MAX_REVISION_ROUNDS)
    return total


def run_condition(topic: str, condition: str, no_review: bool) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        "main.py",
        "--pipeline",
        "--max-sections",
        str(MAX_SECTIONS),
        "--plan-file",
        str(Path("eval") / "plans" / f"{slugify(topic)}.json"),
        "--output-suffix",
        condition,
    ]
    if no_review:
        command.append("--no-review")
    command.append(topic)
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def relocate_outputs(topic: str, condition: str) -> None:
    slug = slugify(topic)
    report_source = ROOT / "reports" / f"{slug}-{condition}.md"
    metrics_source = ROOT / "reports" / f"{slug}-metrics-{condition}.json"
    report_target = report_path(topic, condition)
    metrics_target = metrics_path(topic, condition)

    if report_source.exists():
        report_source.replace(report_target)
    if metrics_source.exists():
        metrics_source.replace(metrics_target)


def is_daily_quota_error(output: str) -> bool:
    return any(message.lower() in output.lower() for message in DAILY_QUOTA_MESSAGES)


def read_metrics(topic: str, condition: str) -> dict:
    path = metrics_path(topic, condition)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read metrics file {path}: {exc}")
        return {}


def stage_data(metrics: dict, stage: str) -> dict:
    stages = metrics.get("stages", {})
    if not isinstance(stages, dict):
        return {}
    data = stages.get(stage, {})
    return data if isinstance(data, dict) else {}


def metric_number(metrics: dict, *keys: str) -> float:
    value = metrics
    for key in keys:
        if not isinstance(value, dict):
            return 0
        value = value.get(key, 0)
    return value if isinstance(value, (int, float)) else 0


def write_results(topics: list[str]) -> None:
    lines = [
        "# Evaluation Results",
        "",
        "| Topic | Condition | LLM calls | Tokens | Seconds | Sections | Revision rounds | Failed review in round 1 | Insufficient evidence |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for topic in topics:
        for condition, _ in CONDITIONS:
            metrics = read_metrics(topic, condition)
            llm_calls = tokens = seconds = 0
            review_calls = 0
            for stage in ("plan", "research", "write", "review"):
                stage_metrics = stage_data(metrics, stage)
                llm_calls += metric_number(stage_metrics, "llm_real_calls")
                llm_calls += metric_number(stage_metrics, "llm_cache_hits")
                tokens += metric_number(stage_metrics, "input_tokens")
                tokens += metric_number(stage_metrics, "output_tokens")
                seconds += metric_number(stage_metrics, "seconds")
                if stage == "review":
                    review_calls = int(
                        metric_number(stage_metrics, "llm_real_calls")
                        + metric_number(stage_metrics, "llm_cache_hits")
                    )
            evaluation = metrics.get("evaluation", {})
            if not isinstance(evaluation, dict):
                evaluation = {}
            sections = evaluation.get("sections", 0)
            failed_first = evaluation.get("failed_review_round1", 0)
            insufficient = evaluation.get("insufficient_evidence_sections", 0)
            revision_rounds = review_calls if condition == "review" else 0
            lines.append(
                f"| {topic} | {condition} | {int(llm_calls)} | {int(tokens)} | "
                f"{seconds:.2f} | {sections} | {revision_rounds} | "
                f"{failed_first} | {insufficient} |"
            )
    (EVAL_DIR / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def report_sentences(topic: str, condition: str) -> list[dict[str, str]]:
    path = report_path(topic, condition)
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    report_body, _, sources_body = text.partition("## Sources")
    sources = {
        int(match.group(1)): match.group(2)
        for match in re.finditer(
            r"^\s*(\d+)\.\s+(https?://\S+)", sources_body, re.MULTILINE
        )
    }
    section = ""
    section_lines: dict[str, list[str]] = {}
    for line in report_body.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            section_lines.setdefault(section, [])
            continue
        if not line.strip() or line.startswith("#") or line.startswith(">"):
            continue
        if section:
            section_lines[section].append(line.strip())

    entries: list[dict[str, str]] = []
    for section, lines in section_lines.items():
        content = " ".join(lines)
        citations = [int(value) for value in re.findall(r"\[(\d+)\]", content)]
        sentence_text = re.sub(r"\s*\[\d+\]", "", content).strip()
        sentences = re.split(r"(?<=[.!?])\s+", sentence_text)
        urls = "; ".join(
            dict.fromkeys(sources[number] for number in citations if number in sources)
        )
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                entries.append(
                    {
                        "topic": topic,
                        "condition": condition,
                        "section": section,
                        "sentence": sentence,
                        "source_urls": urls,
                    }
                )
    return entries


def write_scoring_files(topics: list[str]) -> None:
    keyed_rows: list[tuple[dict[str, str], dict[str, str]]] = []
    row_number = 1
    for topic in topics:
        for condition, _ in CONDITIONS:
            for entry in report_sentences(topic, condition):
                row_id = f"R{row_number:04d}"
                row_number += 1
                scoring_row = {
                    "row_id": row_id,
                    "sentence": entry["sentence"],
                    "source_urls": entry["source_urls"],
                    "supported": "",
                    "notes": "",
                }
                answer_row = {
                    "row_id": row_id,
                    "topic": entry["topic"],
                    "condition": entry["condition"],
                    "section": entry["section"],
                    "source_urls": entry["source_urls"],
                }
                keyed_rows.append((scoring_row, answer_row))

    random.Random(0).shuffle(keyed_rows)
    with (EVAL_DIR / "scoring_sheet.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as scoring_file:
        writer = csv.DictWriter(
            scoring_file,
            fieldnames=["row_id", "sentence", "source_urls", "supported", "notes"],
        )
        writer.writeheader()
        writer.writerows(row for row, _ in keyed_rows)

    with (EVAL_DIR / "answer_key.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as answer_file:
        writer = csv.DictWriter(
            answer_file,
            fieldnames=["row_id", "topic", "condition", "section", "source_urls"],
        )
        writer.writeheader()
        writer.writerows(answer for _, answer in keyed_rows)


def write_progress(completed_runs: list[dict[str, str]], stopped_at: dict | None = None) -> None:
    progress = {"completed_runs": completed_runs}
    if stopped_at:
        progress["stopped_at"] = stopped_at
    PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_partial_outputs(topics: list[str]) -> None:
    write_results(topics)
    write_scoring_files(topics)


def pending_runs(topics: list[str]) -> list[tuple[str, str]]:
    return [
        (topic, condition)
        for topic in topics
        for condition, _ in CONDITIONS
        if not report_path(topic, condition).exists()
    ]


def main() -> int:
    topics = load_topics()
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Expected LLM calls (upper-bound estimate): {expected_llm_calls(topics)}")
    try:
        input("Press Enter to begin evaluation...")
    except EOFError:
        print("No confirmation received; evaluation cancelled.")
        return 1

    completed_runs: list[dict[str, str]] = []
    for topic in topics:
        for condition, no_review in CONDITIONS:
            output_report = report_path(topic, condition)
            if output_report.exists():
                print(f"Skipping existing report: {output_report}")
                completed_runs.append(
                    {"topic": topic, "condition": condition, "status": "existing"}
                )
                write_progress(completed_runs)
                continue

            print(f"Running {condition}: {topic}")
            completed = run_condition(topic, condition, no_review)
            output = f"{completed.stdout}\n{completed.stderr}"
            relocate_outputs(topic, condition)

            if is_daily_quota_error(output):
                print(f"Daily quota error; stopping evaluation at {topic} ({condition}).")
                completed_runs.append(
                    {"topic": topic, "condition": condition, "status": "quota-error"}
                )
                write_progress(
                    completed_runs,
                    {"topic": topic, "condition": condition},
                )
                write_partial_outputs(topics)
                print("Pending runs:")
                for remaining_topic, remaining_condition in pending_runs(topics):
                    print(f"- {remaining_topic} ({remaining_condition})")
                return 1

            if completed.returncode:
                completed_runs.append(
                    {"topic": topic, "condition": condition, "status": "failed"}
                )
                write_progress(
                    completed_runs,
                    {"topic": topic, "condition": condition},
                )
                write_partial_outputs(topics)
                print(output[-5000:])
                print(
                    f"Evaluation run failed for {topic} ({condition}), "
                    f"exit code {completed.returncode}."
                )
                return completed.returncode

            completed_runs.append(
                {"topic": topic, "condition": condition, "status": "done"}
            )
            write_progress(completed_runs)
            write_partial_outputs(topics)

    write_partial_outputs(topics)
    print(
        "Wrote eval/results.md, eval/scoring_sheet.csv, eval/answer_key.csv, "
        "and eval/progress.json."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
