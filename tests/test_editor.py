from unittest.mock import patch

from app.agents.editor import (
    EditorResult,
    _Contradiction,
    _EditorOutput,
    apply_editor_result,
    edit_report,
)
from app.schemas import Issue, Report, SectionDraft, SectionResult


def make_section(title, content, source):
    return SectionResult(
        draft=SectionDraft(
            title=title,
            content=content,
            source_urls=[source],
        ),
        passed=True,
        issues=[],
        sources=[source],
    )


def make_report(contents):
    sections = [
        make_section(
            f"Section {index}",
            content,
            f"https://example.test/{index}",
        )
        for index, content in enumerate(contents, 1)
    ]
    return Report(
        topic="Test report",
        sections=sections,
        sources=[source for section in sections for source in section.sources],
    )


def editor_output(summary, duplicates=None):
    return _EditorOutput(
        summary=summary,
        contradictions=[
            _Contradiction(
                section_a=1,
                section_b=2,
                description="The sections discuss the same market trend.",
            )
        ],
        duplicate_sentences=duplicates or [],
    )


@patch("app.agents.editor.ask_json")
def test_summary_with_invented_number_rejected_after_one_regeneration(mock_ask):
    report = make_report(
        [
            "The market is growing steadily. Consumer interest is increasing.",
            "Companies are expanding distribution. Demand remains strong.",
        ]
    )
    mock_ask.side_effect = [
        editor_output(
            "The market grew 80%. Consumers are showing greater interest. "
            "Companies continue to expand distribution."
        ),
        editor_output(
            "The market grew 80%. Consumers are showing greater interest. "
            "Companies continue to expand distribution."
        ),
    ]

    result = edit_report(report)

    assert result.summary == ""
    assert mock_ask.call_count == 2


def test_duplicate_removal_only_removes_exact_sentence_matches():
    report = make_report(
        [
            "The product is popular. The first section has unique details.",
            "The product is popular. The product is popular among commuters.",
        ]
    )

    apply_editor_result(
        report,
        EditorResult(
            summary="",
            notes=[],
            removed_sentences=["The product is popular."],
        ),
    )

    assert report.sections[0].draft.content == (
        "The product is popular. The first section has unique details."
    )
    assert report.sections[1].draft.content == (
        "The product is popular among commuters."
    )
    assert report.editor_removed_sentences == ["The product is popular."]


@patch("app.agents.editor.ask_json")
def test_one_content_section_skips_editor(mock_ask):
    report = Report(
        topic="Single section",
        sections=[
            make_section(
                "Content",
                "A single section contains usable research.",
                "https://example.test/1",
            ),
            SectionResult(
                draft=SectionDraft(
                    title="Empty",
                    content="Not enough verified information found.",
                    source_urls=[],
                ),
                passed=False,
                issues=[Issue(claim="", problem="no facts retrieved")],
                sources=[],
            ),
        ],
        sources=["https://example.test/1"],
    )

    result = edit_report(report)

    assert result == EditorResult()
    mock_ask.assert_not_called()


def test_build_markdown_includes_summary_but_not_editor_notes():
    from app.report import build_markdown

    report = make_report(["First section content.", "Second section content."])
    report.editor_summary = "The report presents two research findings."
    report.editor_notes = ["Sections 1 and 2 overlap."]
    report.editor_removed_sentences = ["A duplicate sentence."]

    markdown = build_markdown(report, include_empty=False)

    assert "## Executive Summary" in markdown
    assert report.editor_summary in markdown
    assert "Editor notes" not in markdown
    assert "overlap" not in markdown
