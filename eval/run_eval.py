"""Run the four evaluation conditions and create blind sentence-scoring files."""

import argparse
import csv
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = Path(__file__).resolve().parent
TOPICS_FILE = EVAL_DIR / "topics.txt"
CONDITIONS: dict[str, tuple[str, ...]] = {
    "single": ("--single-agent",),
    "basic": (
        "--pipeline",
        "--no-review",
        "--no-supervisor",
        "--no-verifier",
        "--no-editor",
    ),
    "review-supervisor": ("--pipeline", "--no-verifier", "--no-editor"),
    "full": ("--pipeline",),
}
EXPECTED_CALLS_PER_TOPIC = {
    "single": 4,
    "basic": 7,
    "review-supervisor": 13,
    "full": 17,
}
LEVEL_TWO_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
SECTION_HEADING = re.compile(r"^Section \d+:\s*(.*)$")
SOURCE_ENTRY = re.compile(r"^(\d+)\.\s+(https?://\S+)", re.MULTILINE)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
CITATION = re.compile(r"\[(\d+)\]")
SOURCE_CHECK = re.compile(
    r"Source check:\*\*\s*(\d+)\s+of\s+(\d+)\s+sentences confirmed against sources"
)


def slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "topic"


def load_topics(path: Path = TOPICS_FILE, limit: int | None = None) -> list[str]:
    topics = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return topics[:limit] if limit is not None else topics


def report_path(topic: str, condition: str, eval_dir: Path = EVAL_DIR) -> Path:
    return eval_dir / "reports" / f"{slugify(topic)}-{condition}.md"


def metric_path(topic: str, condition: str, eval_dir: Path = EVAL_DIR) -> Path:
    return eval_dir / "metrics" / f"{slugify(topic)}-metrics-{condition}.json"


def expected_llm_calls(topics: Sequence[str], eval_dir: Path = EVAL_DIR) -> int:
    pending_estimates = 0
    for topic in topics:
        for condition, estimate in EXPECTED_CALLS_PER_TOPIC.items():
            if not report_path(topic, condition, eval_dir).exists():
                pending_estimates += estimate
    return pending_estimates


def build_command(topic: str, condition: str, eval_dir: Path = EVAL_DIR) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "main.py"),
        topic,
        "--max-sections",
        "3",
        "--output-suffix",
        condition,
    ]
    if condition != "single":
        plan_file = eval_dir / "plans" / f"{slugify(topic)}.json"
        try:
            plan_argument = str(plan_file.relative_to(ROOT))
        except ValueError:
            plan_argument = str(plan_file)
        command.extend(
            [
                "--plan-file",
                plan_argument,
            ]
        )
    command.extend(CONDITIONS[condition])
    return command


def _relocate_outputs(topic: str, condition: str, eval_dir: Path) -> None:
    slug = slugify(topic)
    reports_dir = eval_dir / "reports"
    metrics_dir = eval_dir / "metrics"
    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    for source, target in (
        (
            ROOT / "reports" / f"{slug}-{condition}.md",
            report_path(topic, condition, eval_dir),
        ),
        (
            ROOT / "reports" / f"{slug}-metrics-{condition}.json",
            metric_path(topic, condition, eval_dir),
        ),
    ):
        if source.exists():
            shutil.move(str(source), str(target))


def _report_sections(markdown: str) -> list[tuple[str, str]]:
    headings = list(LEVEL_TWO_HEADING.finditer(markdown))
    sections = []
    for index, heading in enumerate(headings):
        section_match = SECTION_HEADING.match(heading.group(1))
        if not section_match:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        sections.append(
            (section_match.group(1).strip(), markdown[heading.end():end])
        )
    return sections


def _content_lines(block: str) -> list[str]:
    return [
        line.strip()
        for line in block.splitlines()
        if line.strip()
        and not line.lstrip().startswith((">", "#", "*"))
    ]


def _section_content(block: str) -> str:
    content = " ".join(_content_lines(block))
    content = re.sub(r"\[(?:Partly supported by source|Could not check against source)\]", "", content)
    return re.sub(r"\s+", " ", CITATION.sub("", content)).strip()


def _report_stats(markdown: str) -> tuple[int, int, int]:
    content_count = 0
    empty_count = 0
    verifier_removed = 0
    for _, block in _report_sections(markdown):
        content = _section_content(block)
        if not content or "No evidence found" in block or content == "Not enough verified information found.":
            empty_count += 1
        else:
            content_count += 1

        checked = SOURCE_CHECK.search(block)
        if checked:
            original_sentence_count = int(checked.group(2))
            kept_sentence_count = sum(
                bool(sentence.strip())
                for sentence in SENTENCE_SPLIT.split(content)
            )
            verifier_removed += max(0, original_sentence_count - kept_sentence_count)
    return content_count, empty_count, verifier_removed


def write_results(topics: Sequence[str], eval_dir: Path = EVAL_DIR) -> None:
    headers = [
        "Topic",
        "Condition",
        "LLM calls",
        "Tokens",
        "Seconds",
        "Sections with content",
        "Sections empty",
        "Sections failed in review round 1",
        "Sentences removed by Verifier",
    ]
    lines = [
        "# Evaluation results",
        "",
        "Verifier removals are estimated as checked sentences minus final retained sentences.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |",
    ]
    for topic in topics:
        for condition in CONDITIONS:
            report_file = report_path(topic, condition, eval_dir)
            data_file = metric_path(topic, condition, eval_dir)
            content_count = empty_count = removed = "n/a"
            if report_file.exists():
                content, empty, removed_count = _report_stats(
                    report_file.read_text(encoding="utf-8")
                )
                content_count, empty_count, removed = (
                    str(content),
                    str(empty),
                    str(removed_count),
                )

            calls = tokens = seconds = failed_round1 = "n/a"
            if data_file.exists():
                data = json.loads(data_file.read_text(encoding="utf-8"))
                stages = data.get("stages", {})
                calls = str(sum(
                    stage.get("llm_real_calls", 0) + stage.get("llm_cache_hits", 0)
                    for stage in stages.values()
                ))
                tokens = str(sum(
                    stage.get("input_tokens", 0) + stage.get("output_tokens", 0)
                    for stage in stages.values()
                ))
                seconds = f"{sum(stage.get('seconds', 0) for stage in stages.values()):.2f}"
                failed_round1 = str(
                    data.get("evaluation", {}).get("failed_review_round1", 0)
                )
            row = [
                topic,
                condition,
                calls,
                tokens,
                seconds,
                content_count,
                empty_count,
                failed_round1,
                removed,
            ]
            lines.append("| " + " | ".join(row) + " |")
    (eval_dir / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def report_sentences(topic: str, condition: str, eval_dir: Path = EVAL_DIR) -> list[dict[str, str]]:
    path = report_path(topic, condition, eval_dir)
    if not path.exists():
        return []
    markdown = path.read_text(encoding="utf-8")
    sources_block = markdown.partition("## Sources")[2]
    source_urls = {
        int(number): url
        for number, url in SOURCE_ENTRY.findall(sources_block)
    }
    rows: list[dict[str, str]] = []
    for section_number, (_, block) in enumerate(_report_sections(markdown), 1):
        content = _section_content(block)
        if not content or content == "Not enough verified information found.":
            continue
        content_lines = _content_lines(block)
        final_citations = (
            re.search(r"((?:\s+\[\d+\])+)\s*$", content_lines[-1])
            if content_lines
            else None
        )
        source_ids = sorted({
            int(number)
            for number in CITATION.findall(final_citations.group(1) if final_citations else "")
            if int(number) in source_urls
        })
        urls = "; ".join(source_urls[number] for number in source_ids)
        for sentence in SENTENCE_SPLIT.split(content):
            sentence = sentence.strip()
            if sentence:
                rows.append({
                    "topic": topic,
                    "section": str(section_number),
                    "sentence": sentence,
                    "source_urls": urls,
                })
    return rows


def write_scoring_files(topics: Sequence[str], eval_dir: Path = EVAL_DIR) -> None:
    scoring_rows: list[dict[str, str]] = []
    answer_rows: list[dict[str, str]] = []
    row_ids = random.SystemRandom()
    allocated_ids: set[str] = set()
    for topic in topics:
        for condition in CONDITIONS:
            for entry in report_sentences(topic, condition, eval_dir):
                row_id = f"R{row_ids.getrandbits(32):08X}"
                while row_id in allocated_ids:
                    row_id = f"R{row_ids.getrandbits(32):08X}"
                allocated_ids.add(row_id)
                scoring_rows.append({
                    "row_id": row_id,
                    "topic": topic,
                    "sentence": entry["sentence"],
                    "source_urls": entry["source_urls"],
                    "supported": "",
                    "notes": "",
                })
                answer_rows.append({
                    "row_id": row_id,
                    "condition": condition,
                    "section": entry["section"],
                })

    random.Random(20261016).shuffle(scoring_rows)
    eval_dir.mkdir(parents=True, exist_ok=True)
    with (eval_dir / "scoring_sheet.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["row_id", "topic", "sentence", "source_urls", "supported", "notes"],
        )
        writer.writeheader()
        writer.writerows(scoring_rows)
    with (eval_dir / "answer_key.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["row_id", "condition", "section"],
        )
        writer.writeheader()
        writer.writerows(answer_rows)


def pending_runs(topics: Sequence[str], eval_dir: Path = EVAL_DIR) -> list[tuple[str, str]]:
    return [
        (topic, condition)
        for topic in topics
        for condition in CONDITIONS
        if not report_path(topic, condition, eval_dir).exists()
    ]


def run_evaluation(
    topics: Sequence[str],
    *,
    eval_dir: Path = EVAL_DIR,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    input_fn: Callable[[str], str] = input,
) -> int:
    estimate = expected_llm_calls(topics, eval_dir)
    print(
        f"Expected LLM calls: approximately {estimate} "
        "(one-pass estimate; extra searches, revisions, and verification batches vary)."
    )
    try:
        input_fn("Press Enter to begin evaluation: ")
    except EOFError:
        print("No confirmation received; evaluation cancelled.")
        return 1

    plans_dir = eval_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    for topic in topics:
        for condition in CONDITIONS:
            output_file = report_path(topic, condition, eval_dir)
            if output_file.exists():
                print(f"Skipping existing report: {topic} [{condition}]")
                continue
            command = build_command(topic, condition, eval_dir)
            completed = runner(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
            _relocate_outputs(topic, condition, eval_dir)
            if "Daily free quota exhausted" in output:
                remaining = pending_runs(topics, eval_dir)
                print(f"Daily free quota exhausted during {topic} [{condition}].")
                print("Left to run:")
                for remaining_topic, remaining_condition in remaining:
                    print(f"- {remaining_topic} [{remaining_condition}]")
                write_results(topics, eval_dir)
                write_scoring_files(topics, eval_dir)
                return 1
            if completed.returncode:
                print(output[-5000:])
                print(
                    f"Evaluation failed for {topic} [{condition}] "
                    f"(exit {completed.returncode})."
                )
                write_results(topics, eval_dir)
                write_scoring_files(topics, eval_dir)
                return completed.returncode
            print(f"Completed: {topic} [{condition}]")

    write_results(topics, eval_dir)
    write_scoring_files(topics, eval_dir)
    print(f"Wrote results and blind scoring files under {eval_dir}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topics", type=int, default=None, help="Run only the first N topics.")
    args = parser.parse_args(argv)
    if args.topics is not None and args.topics < 1:
        parser.error("--topics must be at least 1")
    topics = load_topics(limit=args.topics)
    return run_evaluation(topics)


if __name__ == "__main__":
    raise SystemExit(main())
