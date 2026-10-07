import re
import logging
from typing import List

from ..schemas import Issue, Review, SectionDraft, Fact
from ..cache import toggle_cache

logger = logging.getLogger(__name__)


def _extract_numbers(content: str) -> List[str]:
    """Extract all numbers from content: digits, percentages, years, prices."""
    numbers = []

    # Digits (whole numbers, decimals)
    numbers.extend(re.findall(r"\b\d+(?:\.\d+)?\b", content))

    # Percentages
    numbers.extend(re.findall(r"\b\d+(?:\.\d+)?%\b", content))

    # Years (4-digit numbers that look like years, 1500-2999)
    numbers.extend(re.findall(r"\b(?:15|16|17|18|19|2)\d{2}\b", content))

    # Prices: $ amount or amount $
    numbers.extend(re.findall(r"\$\d+(?:\.\d+)?", content))
    numbers.extend(re.findall(r"\b\d+(?:\.\d+)?\s*\$", content))

    # Normalize: strip trailing $ from price-right patterns
    normalized = []
    for n in numbers:
        if n.endswith("$"):
            n = n[:-1]
        if n.endswith("%"):
            pass  # keep percentage as-is
        normalized.append(n.strip())

    # Deduplicate while preserving order
    seen = set()
    result = []
    for n in normalized:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def review_section(draft: SectionDraft, facts: List[Fact]) -> Review:
    """Review a drafted section against verified facts.

    Step A (no LLM): check that every number in the draft content
    appears in the text of the facts. Any number not found becomes an Issue.

    Step B (LLM, via ask_json): ask the model to find every sentence that
    makes a claim NOT supported by the facts (invented detail, exaggeration,
    wrong attribution), with a one-line reason each.

    passed = True only if both steps find zero issues (after merging and
    deduplicating). If the draft says "Not enough verified information found."
    skip the LLM and return passed=True.
    """
    # Skip if draft indicates no verified information
    if draft.content.strip() == "Not enough verified information found.":
        return Review(passed=True, issues=[])

    # Step A: check numbers in draft content against facts text
    draft_numbers = _extract_numbers(draft.content)

    # Build a searchable text pool from facts claims
    facts_text = " ".join(f.claim for f in facts)

    number_issues: List[Issue] = []
    for num in draft_numbers:
        # Check if the number string appears in any fact claim
        if num not in facts_text:
            number_issues.append(
                Issue(claim=num, problem="number not found in facts")
            )

    logger.info(f"Reviewer step A found {len(number_issues)} issues")

    # Step B: LLM review - always run (except skip condition already handled)
    # Ask_json schema expects {"passed": bool, "issues": [{"claim": str, "problem": str}]}
    from ..llm import ask_json

    # Build a summary of facts for the LLM prompt
    facts_summary = "\n".join(
        f"{i+1}. {f.claim} (source: {f.source_url})" for i, f in enumerate(facts)
    )

    system_prompt = (
        "You are a market research reviewer. Your task is to find claims in the "
        "draft that are NOT supported by the provided facts. Use ONLY the provided "
        "facts - do NOT use any outside knowledge. For each problematic sentence, "
        "quote it exactly as it appears in the draft and provide a one-line reason. "
        "Return valid JSON with two fields: \"passed\" (boolean) and \"issues\" "
        "(array of objects, each with \"claim\" and \"problem\" fields). No prose, "
        "no markdown code fences."
    )

    user_prompt = f"""
QUESTION: Review the following drafted section for accuracy against the provided facts.

DRAFT:
{draft.content}

FACTS:
{facts_summary}

Instructions:
- Find every sentence in the draft that makes a claim not supported by the facts.
- This includes invented details, exaggerations, wrong attributions, and any claim
  that goes beyond what the facts state.
- Quote each problematic sentence exactly as it appears in the draft.
- Provide a one-line reason for each (e.g. "invented detail not in facts", 
  "exaggeration beyond what facts support", "wrong attribution").
- Do NOT use any outside knowledge.
- Return valid JSON with two fields:
  "passed": boolean (true only if zero unsupported claims exist),
  "issues": array of objects, each with "claim" (the exact sentence) and "problem" 
  (one-line reason).
- The output must be a single JSON object with "passed" and "issues" keys, no 
  array of Issue objects.
"""

    result: Review = ask_json(
        system=system_prompt,
        user=user_prompt,
        schema=Review,
        retries=2,
    )
    logger.info(f"Reviewer step B found {len(result.issues)} issues")

    # Merge both issue lists and drop duplicates that refer to the same sentence
    seen_claims: set = set()
    merged_issues: List[Issue] = []

    for issue in number_issues + result.issues:
        key = issue.claim
        if key not in seen_claims:
            seen_claims.add(key)
            merged_issues.append(issue)

    # passed is based on the merged list, not the model's own passed value
    passed = len(merged_issues) == 0

    return Review(passed=passed, issues=merged_issues)


if __name__ == "__main__":
    # Disable disk cache so every call is real
    toggle_cache(enabled=False)

    # Configure logging at INFO
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Hardcoded test facts
    facts = [
        Fact(claim="Brand X sells its scooter for Rs. 250,000.", source_url="https://example.com/1"),
        Fact(claim="Brand X offers a 2-year battery warranty.", source_url="https://example.com/2"),
    ]

    # (a) "Brand X sells its scooter for Rs. 250,000 and offers a 2-year battery warranty."
    draft_a = SectionDraft(
        title="Scooter Review",
        content="Brand X sells its scooter for Rs. 250,000 and offers a 2-year battery warranty.",
        source_urls=["https://example.com/1", "https://example.com/2"],
    )

    # (b) "Brand X sells its scooter for Rs. 250,000 with a 5-year battery warranty."
    draft_b = SectionDraft(
        title="Scooter Review",
        content="Brand X sells its scooter for Rs. 250,000 with a 5-year battery warranty.",
        source_urls=["https://example.com/1", "https://example.com/2"],
    )

    # (c) "Brand X is the most popular scooter in the country, and its battery is considered the best in the industry."
    draft_c = SectionDraft(
        title="Scooter Review",
        content="Brand X is the most popular scooter in the country, and its battery is considered the best in the industry.",
        source_urls=["https://example.com/1", "https://example.com/2"],
    )

    # (d) "Brand Y sells its scooter for Rs. 250,000 and offers a 2-year battery warranty."
    draft_d = SectionDraft(
        title="Scooter Review",
        content="Brand Y sells its scooter for Rs. 250,000 and offers a 2-year battery warranty.",
        source_urls=["https://example.com/1", "https://example.com/2"],
    )

    drafts = [draft_a, draft_b, draft_c, draft_d]
    draft_labels = [
        "(a) Faithful draft with both correct numbers and claim",
        "(b) Invented number: 5-year warranty",
        "(c) Invented claim: most popular, best in industry",
        "(d) Wrong brand: Brand Y instead of Brand X",
    ]

    for draft, label in zip(drafts, draft_labels):
        print("=" * 60)
        print(f"Review {label}")
        print("=" * 60)
        review = review_section(draft, facts)
        print(f"passed: {review.passed}")
        for issue in review.issues:
            print(f"  - claim: '{issue.claim}', problem: '{issue.problem}'")
        print()