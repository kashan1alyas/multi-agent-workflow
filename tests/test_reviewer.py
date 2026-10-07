import pytest
from unittest.mock import patch, MagicMock

from app.schemas import Fact, SectionDraft, Issue, Review
from app.agents.reviewer import review_section
from app.llm import ask_json
from app.agents.writer import write_section


class MockFact:
    def __init__(self, claim, source_url):
        self.claim = claim
        self.source_url = source_url


class MockSectionDraft:
    def __init__(self, content, source_urls=None):
        self.content = content
        self.source_urls = source_urls or []


@pytest.fixture
def mock_facts():
    return [
        MockFact(claim="Brand X sells its scooter for Rs. 250,000.", source_url="https://example.com/1"),
        MockFact(claim="Brand X offers a 2-year battery warranty.", source_url="https://example.com/2"),
    ]


@pytest.fixture
def mock_draft_faithful():
    return MockSectionDraft(content="Brand X sells its scooter for Rs. 250,000. Brand X offers a 2-year battery warranty.", source_urls=["https://example.com/1", "https://example.com/2"])


@pytest.fixture
def mock_draft_invented_number():
    return MockSectionDraft(content="Brand X sells its scooter for Rs. 250,000 with a 5-year battery warranty.", source_urls=["https://example.com/1", "https://example.com/2"])


@pytest.fixture
def mock_draft_wrong_brand():
    return MockSectionDraft(content="Brand Y sells its scooter for Rs. 250,000 and offers a 2-year battery warranty.", source_urls=["https://example.com/1", "https://example.com/2"])


@patch("app.llm.ask_json")
def test_reviewer_approves_faithful_draft(mock_ask_json, mock_facts, mock_draft_faithful):
    """Test that a faithful draft (all numbers in facts) gets passed=True."""
    # Mock the LLM to return an empty issues list (passed=True)
    mock_ask_json.return_value = Review(passed=True, issues=[])

    facts = [Fact(claim=f.claim, source_url=f.source_url) for f in mock_facts]
    # Use a real SectionDraft, not MockSectionDraft
    draft = SectionDraft(title="Test", content=mock_draft_faithful.content, source_urls=mock_draft_faithful.source_urls)

    review = review_section(draft, facts)

    assert review.passed is True
    assert review.issues == []


@patch("app.llm.ask_json")
def test_reviewer_rejects_invented_number(mock_ask_json, mock_facts, mock_draft_invented_number):
    """Test that an invented number (5-year warranty not in facts) gets flagged."""
    # Mock LLM to find the invented claim
    mock_ask_json.return_value = Review(
        passed=False,
        issues=[Issue(claim="Brand X sells its scooter for Rs. 250,000 with a 5-year battery warranty.", problem="Warranty duration contradicts facts.")]
    )

    facts = [Fact(claim=f.claim, source_url=f.source_url) for f in mock_facts]
    draft = SectionDraft(title="Test", content=mock_draft_invented_number.content, source_urls=mock_draft_invented_number.source_urls)

    review = review_section(draft, facts)

    assert review.passed is False
    assert len(review.issues) >= 1


@patch("app.llm.ask_json")
def test_reviewer_rejects_wrong_brand(mock_ask_json, mock_facts, mock_draft_wrong_brand):
    """Test that a wrong brand gets flagged by the LLM."""
    mock_ask_json.return_value = Review(
        passed=False,
        issues=[Issue(claim="Brand Y sells its scooter for Rs. 250,000 and offers a 2-year battery warranty.", problem="wrong attribution, facts refer to Brand X not Brand Y")]
    )

    facts = [Fact(claim=f.claim, source_url=f.source_url) for f in mock_facts]
    draft = SectionDraft(title="Test", content=mock_draft_wrong_brand.content, source_urls=mock_draft_wrong_brand.source_urls)

    review = review_section(draft, facts)

    assert review.passed is False
    assert len(review.issues) >= 1


@patch("app.agents.writer.write_section")
def test_revision_loop_stops_at_max_rounds(mock_write_section):
    """Test that revision loop stops after max_rounds even if still failing."""
    import app.agents.revision as revision_mod
    from app.schemas import Fact

    # Make write_section return a draft that will fail review
    failing_draft = SectionDraft(
        title="Test",
        content="Brand X sells scooter for Rs. 250,000 with a 10-year warranty.",
        source_urls=["https://example.com/1"]
    )
    mock_write_section.return_value = failing_draft

    # Make ask_json always return a failing review
    with patch("app.llm.ask_json") as mock_ask_json:
        mock_ask_json.return_value = Review(passed=False, issues=[Issue(claim="test", problem="always fails")])

        facts = [Fact(claim="Brand X sells scooter for Rs. 250,000.", source_url="https://example.com/1")]

        result = revision_mod.revise_until_approved(
            question="Test question",
            facts=facts,
            max_rounds=3,
        )

    assert result["rounds_used"] == 3
    assert result["passed"] is False
    assert len(result["issues"]) > 0