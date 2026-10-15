"""Summarize human support ratings after the blind scoring sheet is complete."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CONDITIONS = ("single", "basic", "review-supervisor", "full")
RATINGS = ("yes", "partly", "no")


def calculate_scores(
    scoring_path: Path = EVAL_DIR / "scoring_sheet.csv",
    answer_key_path: Path = EVAL_DIR / "answer_key.csv",
) -> dict[str, dict[str, int | float]]:
    with answer_key_path.open(encoding="utf-8-sig", newline="") as file:
        answer_key = {row["row_id"]: row for row in csv.DictReader(file)}
    with scoring_path.open(encoding="utf-8-sig", newline="") as file:
        scoring_rows = list(csv.DictReader(file))

    if len(answer_key) != len(scoring_rows):
        raise ValueError("Scoring sheet and answer key rows do not match.")

    totals = {
        condition: {
            "yes": 0,
            "partly": 0,
            "no": 0,
            "rated": 0,
            "sentences": 0,
            "reports": 0,
        }
        for condition in CONDITIONS
    }
    reports: dict[str, set[str]] = defaultdict(set)
    for row in scoring_rows:
        row_id = row.get("row_id", "")
        if row_id not in answer_key:
            raise ValueError(f"Scoring row {row_id!r} is missing from the answer key.")
        condition = answer_key[row_id].get("condition", "")
        if condition not in totals:
            raise ValueError(f"Unknown condition for row {row_id!r}: {condition!r}")
        rating = row.get("supported", "").strip().lower()
        if rating not in RATINGS:
            raise ValueError(
                f"Score row {row_id!r} as yes, partly, or no before running score.py."
            )
        totals[condition][rating] += 1
        totals[condition]["rated"] += 1
        totals[condition]["sentences"] += 1
        reports[condition].add(row.get("topic", ""))

    for condition in CONDITIONS:
        report_count = len(reports[condition])
        totals[condition]["reports"] = report_count
        totals[condition]["sentences_per_report"] = (
            totals[condition]["sentences"] / report_count if report_count else 0
        )
    return totals


def write_scores(
    output_path: Path = EVAL_DIR / "scores.md",
    scoring_path: Path = EVAL_DIR / "scoring_sheet.csv",
    answer_key_path: Path = EVAL_DIR / "answer_key.csv",
) -> None:
    totals = calculate_scores(scoring_path, answer_key_path)
    lines = [
        "# Evaluation scores",
        "",
        "Percentages use rated sentences for each condition as the denominator.",
        "",
        "| Condition | Yes | Partly | No | Sentences per report |",
        "|---|---:|---:|---:|---:|",
    ]
    for condition, values in totals.items():
        denominator = int(values["rated"])
        ratings = []
        for rating in RATINGS:
            count = int(values[rating])
            percent = 100 * count / denominator if denominator else 0
            ratings.append(f"{count} ({percent:.1f}%)")
        average = float(values["sentences_per_report"])
        lines.append(
            f"| {condition} | {ratings[0]} | {ratings[1]} | {ratings[2]} | "
            f"{average:.1f} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    write_scores()
    print(f"Wrote {EVAL_DIR / 'scores.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
