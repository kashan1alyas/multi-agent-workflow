from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.agents.verifier import (
    VerifierBatch,
    VerdictEvidence,
    apply_verification,
    verify_section,
)
from app.schemas import SectionDraft


PAGE_TEXT = (
    "Acme launched its electric scooter in 2024 and sells it across Pakistan. "
    "The company also offers a two-year warranty on the scooter battery. "
    "This page contains additional product and company details for verification."
)


def make_draft(content):
    return SectionDraft(
        title="Scooter",
        content=content,
        source_urls=["https://example.test/scooter"],
    )


def mock_page():
    return SimpleNamespace(
        headers={"Content-Type": "text/html; charset=utf-8"},
        url="https://example.test/scooter",
        text=f"<html><body><p>{PAGE_TEXT}</p></body></html>",
        raise_for_status=lambda: None,
    )


@patch("app.agents.verifier.ask_json")
@patch("app.agents.verifier.requests.get")
def test_supported_stays_and_unsupported_is_removed(mock_get, mock_ask_json):
    mock_get.return_value = mock_page()
    mock_ask_json.return_value = VerifierBatch(
        checks=[
            VerdictEvidence(verdict="supported", evidence="launched its electric scooter in 2024"),
            VerdictEvidence(verdict="unsupported", evidence=""),
        ]
    )
    draft = make_draft(
        "Acme launched its electric scooter in 2024 [1]. "
        "Acme is the country's most popular scooter brand [1]."
    )

    checks = verify_section(draft)
    content, summary = apply_verification(draft.content, checks)

    assert [check.verdict for check in checks] == ["supported", "unsupported"]
    assert "launched its electric scooter in 2024" in content
    assert "most popular scooter brand" not in content
    assert summary == "1 of 2 sentences confirmed against sources"


@patch("app.agents.verifier.ask_json")
@patch("app.agents.verifier.requests.get")
def test_fetch_failure_is_unverifiable_and_does_not_call_llm(mock_get, mock_ask_json):
    mock_get.side_effect = requests.RequestException("offline")
    draft = make_draft("Acme launched an electric scooter [1].")

    checks = verify_section(draft)

    assert len(checks) == 1
    assert checks[0].verdict == "unverifiable"
    assert checks[0].verdict != "supported"
    mock_ask_json.assert_not_called()


@patch("app.agents.verifier.ask_json")
@patch("app.agents.verifier.requests.get")
def test_quote_missing_from_page_downgrades_verdict(mock_get, mock_ask_json):
    mock_get.return_value = mock_page()
    mock_ask_json.return_value = VerifierBatch(
        checks=[
            VerdictEvidence(verdict="supported", evidence="Acme leads the global market")
        ]
    )
    draft = make_draft("Acme leads the global market [1].")

    checks = verify_section(draft)

    assert checks[0].verdict == "unverifiable"
    assert checks[0].evidence == ""


@patch("app.agents.verifier.ask_json")
@patch("app.agents.verifier.requests.get")
def test_two_sentences_from_one_url_share_one_llm_call(mock_get, mock_ask_json):
    mock_get.return_value = mock_page()
    mock_ask_json.return_value = VerifierBatch(
        checks=[
            VerdictEvidence(verdict="supported", evidence="launched its electric scooter in 2024"),
            VerdictEvidence(verdict="supported", evidence="offers a two-year warranty"),
        ]
    )
    draft = make_draft(
        "Acme launched its electric scooter in 2024 [1]. "
        "Acme offers a two-year warranty [1]."
    )

    checks = verify_section(draft)

    assert len(checks) == 2
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["timeout"] == 15
    assert "Mozilla" in mock_get.call_args.kwargs["headers"]["User-Agent"]
    mock_ask_json.assert_called_once()
