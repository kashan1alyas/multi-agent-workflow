import csv
import subprocess
from pathlib import Path

from eval import run_eval, score


def sample_report(content="A finding is reported. [1]"):
    return (
        "# Sample topic\n\n"
        "## Section 1: Findings\n\n"
        "> **Passed review**\n\n"
        f"{content}\n\n"
        "## Sources\n\n"
        "1. https://example.test/source (company)\n"
    )


def test_topics_file_has_ten_topics_including_requested_examples():
    topics = run_eval.load_topics()

    assert len(topics) == 10
    assert "Trekking and mountaineering tourism in the Karakoram" in topics
    assert "Solar panels for homes in Pakistan" in topics
    assert "AI tools for dentists in Pakistan" in topics


def test_commands_apply_four_conditions_and_topic_plan_files(tmp_path):
    single = run_eval.build_command("Test topic", "single", tmp_path)
    basic = run_eval.build_command("Test topic", "basic", tmp_path)

    assert "--single-agent" in single
    assert "--plan-file" not in single
    assert "--max-sections" in single and single[single.index("--max-sections") + 1] == "3"
    assert basic[basic.index("--plan-file") + 1] == str(
        tmp_path / "plans" / "test-topic.json"
    )
    assert all(flag in basic for flag in ("--no-review", "--no-supervisor", "--no-verifier", "--no-editor"))


def test_quota_stops_and_lists_remaining_runs(tmp_path, capsys):
    topic = "quota check topic"
    existing = run_eval.report_path(topic, "single", tmp_path)
    existing.parent.mkdir(parents=True)
    existing.write_text(sample_report(), encoding="utf-8")
    calls = []

    def fake_runner(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(
            args[0],
            1,
            stdout="Daily free quota exhausted",
            stderr="",
        )

    result = run_eval.run_evaluation(
        [topic],
        eval_dir=tmp_path,
        runner=fake_runner,
        input_fn=lambda _: "",
    )

    assert result == 1
    assert len(calls) == 1
    assert "daily free quota exhausted during quota check topic [basic]" in capsys.readouterr().out.lower()
    assert (tmp_path / "results.md").exists()


def test_scoring_sheet_hides_condition_and_answer_key_maps_row(tmp_path):
    topic = "sample topic"
    for condition in run_eval.CONDITIONS:
        path = run_eval.report_path(topic, condition, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sample_report(), encoding="utf-8")

    run_eval.write_scoring_files([topic], tmp_path)

    with (tmp_path / "scoring_sheet.csv").open(encoding="utf-8-sig", newline="") as file:
        scoring_rows = list(csv.DictReader(file))
        assert list(scoring_rows[0]) == [
            "row_id",
            "topic",
            "sentence",
            "source_urls",
            "supported",
            "notes",
        ]
        assert "condition" not in scoring_rows[0]
        assert "verdict" not in scoring_rows[0]
        assert scoring_rows[0]["source_urls"] == "https://example.test/source"

    with (tmp_path / "answer_key.csv").open(encoding="utf-8-sig", newline="") as file:
        answer_rows = list(csv.DictReader(file))
    assert list(answer_rows[0]) == ["row_id", "condition", "section"]
    assert {row["condition"] for row in answer_rows} == set(run_eval.CONDITIONS)


def test_results_estimate_verifier_removed_sentences_from_report():
    markdown = sample_report(
        "> **Source check:** 1 of 3 sentences confirmed against sources\n\n"
        "A retained sentence. Another retained sentence. [1]"
    )

    assert run_eval._report_stats(markdown) == (1, 0, 1)


def test_score_joins_ratings_and_writes_condition_percentages(tmp_path):
    scoring_path = tmp_path / "scoring_sheet.csv"
    answer_path = tmp_path / "answer_key.csv"
    output_path = tmp_path / "scores.md"
    with scoring_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["row_id", "topic", "sentence", "source_urls", "supported", "notes"],
        )
        writer.writeheader()
        writer.writerows([
            {"row_id": "r1", "topic": "topic", "sentence": "one", "source_urls": "", "supported": "yes", "notes": ""},
            {"row_id": "r2", "topic": "topic", "sentence": "two", "source_urls": "", "supported": "partly", "notes": ""},
            {"row_id": "r3", "topic": "topic", "sentence": "three", "source_urls": "", "supported": "no", "notes": ""},
        ])
    with answer_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["row_id", "condition", "section"])
        writer.writeheader()
        writer.writerows([
            {"row_id": "r1", "condition": "single", "section": "1"},
            {"row_id": "r2", "condition": "basic", "section": "1"},
            {"row_id": "r3", "condition": "full", "section": "1"},
        ])

    score.write_scores(output_path, scoring_path, answer_path)
    result = output_path.read_text(encoding="utf-8")

    assert "| single | 1 (100.0%) | 0 (0.0%) | 0 (0.0%) | 1.0 |" in result
    assert "| basic | 0 (0.0%) | 1 (100.0%) | 0 (0.0%) | 1.0 |" in result
    assert "| full | 0 (0.0%) | 0 (0.0%) | 1 (100.0%) | 1.0 |" in result


def test_score_rejects_unfilled_supported_ratings(tmp_path):
    scoring_path = tmp_path / "scoring_sheet.csv"
    answer_path = tmp_path / "answer_key.csv"
    scoring_path.write_text(
        "row_id,topic,sentence,source_urls,supported,notes\nr1,t,s,,,",
        encoding="utf-8",
    )
    answer_path.write_text("row_id,condition,section\nr1,single,1\n", encoding="utf-8")

    try:
        score.calculate_scores(scoring_path, answer_path)
    except ValueError as exc:
        assert "yes, partly, or no" in str(exc)
    else:
        raise AssertionError("Unfilled scoring values must be rejected.")
