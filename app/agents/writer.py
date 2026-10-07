import logging
from typing import List, Optional

from pydantic import BaseModel

from ..llm import ask_json
from ..schemas import Fact, SectionDraft

logger = logging.getLogger(__name__)


class WriterOutput(BaseModel):
    content: str
    source_urls: list[str]


def write_section(
    question: str,
    facts: List[Fact],
    feedback: Optional[str] = None,
) -> SectionDraft:
    """Draft a section from verified facts and retain only their source URLs."""
    if not facts:
        return SectionDraft(
            title=question,
            content="Not enough verified information found.",
            source_urls=[],
        )

    facts_summary = "\n".join(
        f"{index}. {fact.claim} (source: {fact.source_url})"
        for index, fact in enumerate(facts, 1)
    )
    system_prompt = (
        "You are a market research writer. Write 1 to 3 short paragraphs for a "
        "market research report using ONLY the provided numbered facts. Do not "
        "use outside knowledge, numbers that are not in the facts, or "
        "superlatives unless a fact says so. If the facts are thin, say so in "
        "the text. List the source URLs used."
    )
    user_prompt = f"SECTION: {question}\n\nNUMBERED FACTS:\n{facts_summary}"
    if feedback:
        user_prompt += (
            "\n\nYour previous draft had these problems: "
            f"{feedback}. Rewrite the section fixing each one, removing "
            "unsupported claims instead of rewording them."
        )

    output: WriterOutput = ask_json(
        system=system_prompt,
        user=user_prompt,
        schema=WriterOutput,
        retries=2,
    )
    verified_urls = {fact.source_url for fact in facts}
    source_urls = [
        url for url in output.source_urls if url in verified_urls
    ]
    draft = SectionDraft(
        title=question,
        content=output.content,
        source_urls=source_urls,
    )
    logger.info("Drafted section '%s' from %d facts", question, len(facts))
    return draft


if __name__ == "__main__":
    from ..cache import toggle_cache

    toggle_cache(enabled=False)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    sample_facts = [
        Fact(
            claim="Brand X sells its scooter for Rs. 250,000.",
            source_url="https://example.com/price",
        ),
        Fact(
            claim="Brand X offers a 2-year battery warranty.",
            source_url="https://example.com/warranty",
        ),
    ]
    sample_draft = write_section(
        "What are Brand X's scooter price and warranty?",
        sample_facts,
    )
    print(sample_draft.content)
    print("Sources:")
    for source_url in sample_draft.source_urls:
        print(f"- {source_url}")
