from app.report import build_markdown, sort_sections
from app.schemas import Issue, Report, SectionDraft, SectionResult


def make_section(title, content, passed, source, issue=None, original_index=0):
    return SectionResult(
        draft=SectionDraft(
            title=title,
            content=content,
            source_urls=[source] if source else [],
        ),
        passed=passed,
        issues=[issue] if issue else [],
        sources=[source] if source else [],
        original_index=original_index,
    )


def test_sort_sections_groups_and_preserves_order():
    empty_first = make_section(
        "empty first", "Not enough verified information found.", False, None
    )
    verified_first = make_section("verified first", "Verified content.", True, "https://source.test/1")
    unverified = make_section(
        "unverified", "Unverified content.", False, "https://source.test/2",
        Issue(claim="Claim", problem="Problem"),
    )
    verified_second = make_section("verified second", "More content.", True, "https://source.test/3")
    empty_second = make_section("empty second", "No content.", False, None)

    assert sort_sections([
        empty_first,
        verified_first,
        unverified,
        verified_second,
        empty_second,
    ]) == [
        verified_first,
        verified_second,
        unverified,
        empty_first,
        empty_second,
    ]


def test_build_markdown_omits_empty_sections_and_renumbers_sources():
    report = Report(
        topic="Test topic",
        sections=[
            make_section("empty sentinel", "Not enough verified information found.", False, "https://empty.test"),
            make_section("passed one", "Passed content.", True, "https://source.test/1"),
            make_section(
                "unverified text", "Unverified content.", False, "https://source.test/3",
                Issue(claim="Claim", problem="Review warning"),
            ),
            make_section("passed two", "More passed content.", True, "https://source.test/2"),
            make_section("empty no source", "No content.", False, None),
        ],
        sources=[
            "https://empty.test",
            "https://source.test/1",
            "https://source.test/2",
            "https://source.test/3",
        ],
    )

    markdown = build_markdown(report, include_empty=False)

    assert "## Section 1: passed one" in markdown
    assert "## Section 2: passed two" in markdown
    assert "## Section 3: unverified text" in markdown
    assert "## Section 4:" not in markdown
    assert "Not enough verified information found." not in markdown
    assert "https://empty.test" not in markdown
    assert "https://source.test/1" in markdown
    assert "https://source.test/2" in markdown
    assert "https://source.test/3" in markdown
    assert "https://source.test/1" in markdown.split("## Sources", 1)[1]
    assert "Passed content. [1]" in markdown
    assert "More passed content. [2]" in markdown
    assert "Unverified content. [3]" in markdown
    assert "1. https://source.test/1" in markdown
    assert "2. https://source.test/2" in markdown
    assert "3. https://source.test/3" in markdown
    assert "**Unverified.** Review notes: Claim: Review warning" in markdown


def test_build_markdown_returns_empty_for_all_empty_sections():
    report = Report(
        topic="Empty topic",
        sections=[
            make_section("sentinel", "Not enough verified information found.", False, None),
            make_section("no evidence", "Draft without sources.", True, None),
        ],
        sources=[],
    )

    assert build_markdown(report, include_empty=False) == ""


def test_build_markdown_shows_source_check_under_section_badge():
    section = make_section(
        "checked",
        "Verified content.",
        True,
        "https://source.test/1",
    )
    section.source_check_summary = "1 of 1 sentences confirmed against sources"
    report = Report(
        topic="Checked topic",
        sections=[section],
        sources=["https://source.test/1"],
    )

    markdown = build_markdown(report, include_empty=True)

    assert markdown.index("> **Passed review**") < markdown.index(
        "> **Source check:** 1 of 1 sentences confirmed against sources"
    )
