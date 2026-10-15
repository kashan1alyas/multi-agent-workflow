import logging
import re
from collections import defaultdict
from typing import Literal
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

from ..config import VERIFIER_PROVIDER
from ..llm import ask_json
from ..schemas import SectionDraft, SentenceCheck

logger = logging.getLogger(__name__)

MAX_PAGE_CHARACTERS = 12_000
MAX_EVIDENCE_WORDS = 25
MIN_PAGE_TEXT_CHARACTERS = 100
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_CITATION = re.compile(r"\[(\d+)\]")
_SENTENCE = re.compile(r".+?(?:[.!?](?:\s*\[\d+\])?(?=\s|$)|$)", re.DOTALL)


class VerdictEvidence(BaseModel):
    verdict: Literal["supported", "partly_supported", "unsupported", "unverifiable"]
    evidence: str = ""


class VerifierBatch(BaseModel):
    checks: list[VerdictEvidence]


def _split_sentences(text: str) -> list[str]:
    return [match.group().strip() for match in _SENTENCE.finditer(text) if match.group().strip()]


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def _fetch_page_text(url: str) -> str | None:
    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Verifier could not fetch %s: %s", url, exc)
        return None

    content_type = response.headers.get("Content-Type", "").lower()
    if "application/pdf" in content_type or urlparse(response.url or url).path.lower().endswith(".pdf"):
        logger.info("Verifier cannot parse PDF source %s", url)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    text = soup.get_text(" ", strip=True)[:MAX_PAGE_CHARACTERS]
    if len(text) < MIN_PAGE_TEXT_CHARACTERS:
        logger.info("Verifier found too little page text at %s", url)
        return None
    return text


def verify_section(draft: SectionDraft) -> list[SentenceCheck]:
    """Check each cited draft sentence against the text fetched from its source page."""
    sentences = _split_sentences(draft.content)
    source_urls = {index: url for index, url in enumerate(draft.source_urls, 1)}
    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
    checks: list[SentenceCheck | None] = [None] * sum(
        len(_CITATION.findall(sentence)) or 1
        for sentence in sentences
    )
    check_index = 0

    for sentence in sentences:
        citation_numbers = list(dict.fromkeys(_CITATION.findall(sentence)))
        if not citation_numbers:
            continue
        for citation in citation_numbers:
            source_url = source_urls.get(int(citation))
            if source_url:
                grouped[source_url].append((check_index, sentence))
            else:
                checks[check_index] = SentenceCheck(
                    sentence=sentence,
                    source_url="",
                    verdict="unverifiable",
                    evidence="",
                )
                logger.warning("Verifier found unmapped citation [%s]", citation)
            check_index += 1

    page_texts = {url: _fetch_page_text(url) for url in grouped}
    for source_url, entries in grouped.items():
        page_text = page_texts[source_url]
        if page_text is None:
            for index, sentence in entries:
                checks[index] = SentenceCheck(
                    sentence=sentence,
                    source_url=source_url,
                    verdict="unverifiable",
                    evidence="",
                )
            continue

        for batch_start in range(0, len(entries), 4):
            batch = entries[batch_start:batch_start + 4]
            sentence_list = "\n".join(
                f"{index + 1}. {sentence}" for index, sentence in batch
            )
            result: VerifierBatch = ask_json(
                system=(
                    "You are an independent source verifier. Evaluate each supplied "
                    "sentence using only the original page text. For every sentence, "
                    "return verdict supported, partly_supported, unsupported, or "
                    "unverifiable, and an exact quote copied from the page (at most "
                    "25 words) that supports the sentence. Use an empty evidence "
                    "string when no supporting quote exists. Preserve input order."
                ),
                user=(
                    f"ORIGINAL PAGE TEXT:\n{page_text}\n\n"
                    f"SENTENCES TO CHECK:\n{sentence_list}"
                ),
                schema=VerifierBatch,
                provider=VERIFIER_PROVIDER,
            )
            if len(result.checks) != len(batch):
                raise ValueError(
                    "Verifier returned a different number of judgments than sentences."
                )
            for (index, sentence), judgment in zip(batch, result.checks):
                evidence = " ".join(judgment.evidence.split()[:MAX_EVIDENCE_WORDS])
                verdict = judgment.verdict
                if evidence and _normalized(evidence) not in _normalized(page_text):
                    verdict, evidence = "unverifiable", ""
                elif verdict in ("supported", "partly_supported") and not evidence:
                    verdict = "unverifiable"
                checks[index] = SentenceCheck(
                    sentence=sentence,
                    source_url=source_url,
                    verdict=verdict,
                    evidence=evidence,
                )

    return [check for check in checks if check is not None]


def apply_verification(
    content: str,
    checks: list[SentenceCheck],
) -> tuple[str, str]:
    """Remove unsupported sentences, annotate uncertain ones, and summarize checks."""
    by_sentence: dict[str, list[SentenceCheck]] = defaultdict(list)
    for check in checks:
        by_sentence[check.sentence].append(check)

    sentences = _split_sentences(content)
    confirmed = 0
    total = sum(1 for sentence in sentences if sentence in by_sentence)
    revised_sentences: list[str] = []
    for sentence in sentences:
        sentence_checks = by_sentence.get(sentence, [])
        if not sentence_checks:
            revised_sentences.append(sentence)
            continue
        verdicts = {check.verdict for check in sentence_checks}
        if verdicts == {"unsupported"}:
            continue
        if verdicts == {"supported"}:
            confirmed += 1
        elif "partly_supported" in verdicts or (
            "supported" in verdicts and "unsupported" in verdicts
        ):
            sentence = f"{sentence} [Partly supported by source]"
        elif "unverifiable" in verdicts:
            sentence = f"{sentence} [Could not check against source]"
        revised_sentences.append(sentence)

    summary = f"{confirmed} of {total} sentences confirmed against sources"
    return " ".join(revised_sentences), summary
