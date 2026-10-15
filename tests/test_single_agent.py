from unittest.mock import patch

from app.agents.single_agent import (
    AgentAction,
    AgentSection,
    FinishAction,
    run_single_agent,
)
from app.schemas import Report
from app.metrics import metrics


def test_single_agent_forces_finish_at_step_limit(monkeypatch):
    monkeypatch.setattr("app.agents.single_agent.MAX_STEPS", 2)
    monkeypatch.setattr("app.agents.single_agent.MAX_SEARCHES", 8)
    metrics.reset()
    with (
        patch("app.agents.single_agent.search_web") as mock_search,
        patch("app.agents.single_agent.ask_json") as mock_ask,
    ):
        mock_search.return_value = [
            {
                "title": "Source",
                "url": "https://example.test/source",
                "content": "A source snippet.",
            }
        ]
        mock_ask.side_effect = [
            AgentAction(action="search", query="topic facts"),
            FinishAction(
                action="finish",
                sections=[
                    AgentSection(
                        title="Findings",
                        content="A supported finding.",
                        source_urls=["https://example.test/source"],
                    )
                ],
            ),
        ]

        report = run_single_agent("A topic")

    assert mock_ask.call_count == 2
    assert mock_ask.call_args_list[1].kwargs["schema"] is FinishAction
    mock_search.assert_called_once_with("topic facts", max_results=5)
    assert report.sections[0].draft.content == "A supported finding."
    assert "single_agent" in metrics.snapshot()["stages"]


def test_single_agent_never_searches_more_than_eight_times():
    with (
        patch("app.agents.single_agent.search_web", return_value=[]) as mock_search,
        patch("app.agents.single_agent.ask_json") as mock_ask,
    ):
        mock_ask.side_effect = [
            *[
                AgentAction(action="search", query=f"query {index}")
                for index in range(8)
            ],
            FinishAction(action="finish", sections=[]),
        ]

        report = run_single_agent("A topic")

    assert mock_search.call_count == 8
    assert mock_ask.call_count == 9
    assert mock_ask.call_args_list[-1].kwargs["schema"] is FinishAction
    assert report.sections == []


@patch("app.agents.single_agent.search_web")
@patch("app.agents.single_agent.ask_json")
def test_single_agent_drops_invented_source_urls(mock_ask, mock_search):
    mock_search.return_value = [
        {
            "title": "Real source",
            "url": "https://example.test/real",
            "content": "The real search result.",
        }
    ]
    mock_ask.side_effect = [
        AgentAction(action="search", query="topic facts"),
        FinishAction(
            action="finish",
            sections=[
                AgentSection(
                    title="Unsupported sources",
                    content="A claim with an invented citation.",
                    source_urls=[
                        "https://example.test/real",
                        "https://invented.test/fake",
                    ],
                ),
                AgentSection(
                    title="No valid source",
                    content="Another claim.",
                    source_urls=["https://invented.test/only"],
                ),
            ],
        ),
    ]

    report = run_single_agent("A topic")

    assert report.sections[0].sources == ["https://example.test/real"]
    assert report.sections[0].draft.source_urls == ["https://example.test/real"]
    assert report.sections[1].draft.content == "Not enough verified information found."
    assert report.sections[1].sources == []
    assert report.sources == ["https://example.test/real"]


@patch("app.agents.single_agent.search_web")
@patch("app.agents.single_agent.ask_json")
def test_single_agent_output_matches_report_schema(mock_ask, mock_search):
    mock_search.return_value = [
        {
            "title": "Source",
            "url": "https://example.test/source",
            "content": "A source snippet.",
        }
    ]
    mock_ask.side_effect = [
        AgentAction(action="search", query="topic facts"),
        FinishAction(
            action="finish",
            sections=[
                AgentSection(
                    title="Findings",
                    content="A supported finding.",
                    source_urls=["https://example.test/source"],
                )
            ],
        ),
    ]

    report = run_single_agent("A topic", max_sections=1)

    validated = Report.model_validate(report.model_dump())
    assert validated.topic == "A topic"
    assert len(validated.sections) == 1
