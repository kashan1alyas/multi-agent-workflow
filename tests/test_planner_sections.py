import json
import logging
from unittest.mock import Mock

import pytest

from app import pipeline
from app.agents import planner
from app.schemas import Plan, ResearchResult, Section


def make_plan(count: int, topic: str = "Planner test topic") -> Plan:
    angles = [
        "market size",
        "customer demand",
        "technology adoption",
        "regulatory compliance",
        "supplier competition",
        "investment outlook",
        "pricing structures",
        "distribution channels",
        "workforce skills",
        "environmental impacts",
    ]
    return Plan(
        topic=topic,
        sections=[
            Section(
                title=angles[index - 1].title(),
                question=f"Evaluate {angles[index - 1]} trends",
                search_query=f"{angles[index - 1]} trends",
            )
            for index in range(1, count + 1)
        ],
    )


@pytest.mark.parametrize("n_sections", [3, 7, 10])
def test_planner_returns_requested_section_count(monkeypatch, n_sections):
    response = make_plan(n_sections)
    ask_json = Mock(return_value=response)
    monkeypatch.setattr(planner, "ask_json", ask_json)

    result = planner.plan("Planner test topic", n_sections)

    assert len(result.sections) == n_sections
    assert str(n_sections) in ask_json.call_args.kwargs["system"]


def test_planner_retries_near_duplicate_questions(monkeypatch):
    duplicate_plan = Plan(
        topic="Planner test topic",
        sections=[
            Section(
                title="Market trends",
                question="How are market trends affecting growth?",
                search_query="market trends growth",
            ),
            Section(
                title="Market trends growth",
                question="How are market trends affecting growth globally?",
                search_query="global market trends growth",
            ),
            Section(
                title="Regulation",
                question="How do new regulations affect the market?",
                search_query="market regulations effects",
            ),
        ],
    )
    valid_plan = make_plan(3)
    ask_json = Mock(side_effect=[duplicate_plan, valid_plan])
    monkeypatch.setattr(planner, "ask_json", ask_json)

    result = planner.plan("Planner test topic", 3)

    assert len(result.sections) == 3
    assert ask_json.call_count == 2
    assert "near-duplicates" in ask_json.call_args.kwargs["user"]


def test_planner_uses_four_valid_sections_after_three_shortfalls(
    monkeypatch, caplog
):
    short_plan = make_plan(4)
    ask_json = Mock(return_value=short_plan)
    monkeypatch.setattr(planner, "ask_json", ask_json)

    with caplog.at_level(logging.INFO):
        result = planner.plan("Planner test topic", 7)

    assert len(result.sections) == 4
    assert "Planner returned 4 of 7 requested sections" in caplog.text
    assert ask_json.call_count == 3


def test_pipeline_regenerates_saved_plan_with_different_section_count(
    monkeypatch, tmp_path, caplog
):
    plan_path = tmp_path / "saved-plan.json"
    plan_path.write_text(
        json.dumps(make_plan(2).model_dump(mode="json")),
        encoding="utf-8",
    )
    generated_plan = make_plan(7)
    plan_mock = Mock(return_value=generated_plan)
    monkeypatch.setattr(pipeline, "plan", plan_mock)
    monkeypatch.setattr(
        pipeline,
        "research",
        lambda question, **kwargs: ResearchResult(question=question, facts=[]),
    )

    with caplog.at_level(logging.INFO):
        result = pipeline.run_pipeline(
            "Planner test topic",
            max_sections=7,
            plan_file=str(plan_path),
            no_supervisor=True,
            no_verifier=True,
            no_editor=True,
        )

    assert result is not None
    assert len(result.sections) == 7
    plan_mock.assert_called_once_with("Planner test topic", n_sections=7)
    saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert saved_plan["n_sections"] == 7
    assert len(saved_plan["plan"]["sections"]) == 7
    assert "Regenerating" in caplog.text
    assert "requested=7 limit=10 planned=7 researched=7" in caplog.text
