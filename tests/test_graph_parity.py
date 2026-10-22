from unittest.mock import Mock

import pytest

from app import llm, pipeline
from app.agents.supervisor import Decision
from app.errors import DailyQuotaExceeded
from app.graph import build_graph
from app.graph import build as graph_build
from app.graph import nodes as graph_nodes
from app.schemas import Fact, Plan, ResearchResult, Section, SectionDraft


def _mock_pipeline_calls(monkeypatch):
    plan_result = Plan(
        topic="Test topic",
        sections=[
            Section(
                title="First angle",
                question="Research the first angle",
                search_query="first angle test",
            ),
            Section(
                title="Second angle",
                question="Research the second angle",
                search_query="second angle test",
            ),
        ],
    )
    facts_by_question = {
        section.question: ResearchResult(
            question=section.question,
            facts=[
                Fact(
                    claim=f"Verified fact for {section.title}.",
                    source_url=f"https://example.test/{section.title.lower().replace(' ', '-')}",
                )
            ],
        )
        for section in plan_result.sections
    }

    plan_mock = Mock(return_value=plan_result)
    research_mock = Mock(side_effect=lambda question, **kwargs: facts_by_question[question])

    def revise_mock(*, question, facts, max_rounds):
        fact = facts[0]
        return {
            "draft": SectionDraft(
                title=question,
                content=fact.claim,
                source_urls=[fact.source_url],
            ),
            "passed": True,
            "rounds_used": 1,
            "issues": [],
        }

    revise = Mock(side_effect=revise_mock)
    decide = Mock(
        return_value=Decision(
            action="enough",
            new_queries=[],
            reason="mocked sufficient facts",
        )
    )
    monkeypatch.setattr(pipeline, "plan", plan_mock)
    monkeypatch.setattr(graph_nodes, "plan", plan_mock)
    monkeypatch.setattr(pipeline, "research", research_mock)
    monkeypatch.setattr(graph_nodes, "research", research_mock)
    monkeypatch.setattr(pipeline, "revise_until_approved", revise)
    monkeypatch.setattr(graph_nodes, "revise_until_approved", revise)
    monkeypatch.setattr(pipeline, "decide", decide)
    monkeypatch.setattr(graph_nodes, "decide", decide)
    return plan_result, plan_mock, research_mock, revise, decide


def _section_signature(report):
    return [
        (
            section.draft.title,
            section.draft.content,
            section.sources,
        )
        for section in report.sections
    ]


def test_graph_matches_pipeline_sections_for_same_mocked_inputs(monkeypatch):
    _, plan_mock, research_mock, revise_mock, decide_mock = _mock_pipeline_calls(
        monkeypatch
    )
    flags = {
        "no_review": False,
        "no_supervisor": False,
        "no_verifier": True,
        "no_editor": True,
    }

    old_report = pipeline.run_pipeline(
        "Test topic",
        max_sections=2,
        no_supervisor=False,
        no_verifier=True,
        no_editor=True,
    )
    old_signature = _section_signature(old_report)

    graph = build_graph()
    state = graph.invoke(
        {
            "topic": "Test topic",
            "max_sections": 2,
            "flags": flags,
            "section_results": [],
            "research_results": [],
            "errors": [],
        }
    )

    assert _section_signature(state["report"]) == old_signature
    assert [section[0] for section in old_signature] == [
        "First angle",
        "Second angle",
    ]
    assert plan_mock.call_count == 2
    assert research_mock.call_count == 4
    assert revise_mock.call_count == 4
    assert decide_mock.call_count == 4


def test_per_day_provider_error_is_typed_and_propagated(monkeypatch):
    def fail_provider(*args, **kwargs):
        raise RuntimeError("PerDay request limit reached")

    monkeypatch.setattr(llm, "_ask_gemini", fail_provider)

    with pytest.raises(DailyQuotaExceeded, match="Daily free quota exhausted"):
        llm.ask("system", "user", provider="gemini")


def test_graph_stops_after_daily_quota_error(monkeypatch):
    def quota_failure(state):
        raise DailyQuotaExceeded("PerDay quota exhausted")

    research_mock = Mock()
    monkeypatch.setattr(graph_build, "plan_node", quota_failure)
    monkeypatch.setattr(graph_build, "research_node", research_mock)

    with pytest.raises(DailyQuotaExceeded, match="PerDay quota exhausted"):
        build_graph().invoke(
            {
                "topic": "Test topic",
                "max_sections": 1,
                "flags": {
                    "no_review": False,
                    "no_supervisor": True,
                    "no_verifier": True,
                    "no_editor": True,
                },
                "section_results": [],
                "research_results": [],
                "errors": [],
            }
        )

    research_mock.assert_not_called()
