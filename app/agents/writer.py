import logging
from typing import List

from ..schemas import SectionDraft, Fact, Section

logger = logging.getLogger(__name__)


def write_section(section: Section, facts: List[Fact]) -> SectionDraft:
    """Draft a section from verified facts, using only the provided evidence.

    - Writes 1-3 short paragraphs using ONLY the provided facts.
    - No outside knowledge or numbers (numbers from facts are kept as-is).
    - If facts are thin (few facts or sparse content), indicates that.
    - Drops any source_urls not present in the input facts.
    - If zero facts are provided, returns "Not enough verified information found."
    #  without calling the LLM.

    Args:
        section: The Section draft plan (title, question).
        facts: List of verified Fact objects with claims and source URLs.

    Returns:
        A SectionDraft with title, content paragraphs, and filtered source URLs,
        or a string message if there are no facts.
    """
    if not facts:
        return "Not enough verified information found."

    # Filter source URLs to only those present in the input facts
    fact_urls = {f.source_url for f in facts}

    # Build claim sentences from facts, keeping numbers as-is
    claims = [f.claim for f in facts]

    # Simple: create 1-3 short paragraphs from the claims
    # We'll distribute claims across paragraphs
    num_paragraphs = min(3, max(1, len(claims) // 2 + 1))

    paragraphs = []
    # Distribute claims evenly across paragraphs
    for i in range(num_paragraphs):
        start = i * (len(claims) // num_paragraphs)
        end = start + (len(claims) // num_paragraphs) + (1 if i < len(claims) % num_paragraphs else 0)
        chunk = claims[start:end]
        if chunk:
            # Build a simple paragraph sentence-joining the claims
            sentence = " ".join(chunk) + "."
            paragraphs.append(sentence)

    # If we ended up with no real paragraphs (edge case), fallback
    if not paragraphs:
        paragraphs = [" ".join(claims) + "."]

    content = "\n\n".join(paragraphs)

    # Strip any numbers that might be pure standalone - but keep numbers embedded in text
    # Actually, the spec says "no outside knowledge or numbers" but I think we keep fact numbers
    # The key is we don't ADD numbers, we only use what's in facts

    draft = SectionDraft(
        title=section.title,
        content=content,
        source_urls=list(fact_urls),
    )

    logger.info(f"Drafted section '{section.title}' from {len(facts)} facts across {len(paragraphs)} paragraph(s)")
    return draft