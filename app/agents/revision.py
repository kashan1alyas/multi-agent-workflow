import logging
from typing import List, Optional

from ..schemas import SectionDraft, Fact
from ..agents.writer import write_section
from ..agents.reviewer import review_section
from ..metrics import metrics

logger = logging.getLogger(__name__)

MAX_REVISION_ROUNDS = 2


def revise_until_approved(
    question: str,
    facts: List[Fact],
    max_rounds: int = MAX_REVISION_ROUNDS,
) -> dict:
    """Write a draft, review it, and retry on failures until approved or max_rounds reached.

    Steps:
        1. Write a draft using write_section.
        2. Review the draft using review_section.
        3. If the review finds issues (passed=False), pass the issues back to the
           Writer as feedback and retry (up to max_rounds).
        4. Stop when the draft is approved (passed=True) or max_rounds is exceeded.

    Returns a result dict with:
        - draft: the final SectionDraft (or None if failed)
        - passed: bool -- True only if the final review passed
        - rounds_used: int -- how many write+review cycles were executed
        - issues: list of the last Review's Issue objects (empty if passed=True)

    Note: Never silently approves a draft that still fails; set passed=False and
    keep the issues.
    """
    current_feedback: Optional[str] = None
    rounds_used = 0
    last_issues: List = []

    for round_num in range(1, max_rounds + 1):
        logger.info(f"--- Revision round {round_num}/{max_rounds} ---")

        # Step 1: Write a draft (with feedback from previous round if any)
        with metrics.stage("write"):
            draft = write_section(question, facts, feedback=current_feedback)
        rounds_used += 1

        # Step 2: Review the draft
        with metrics.stage("review"):
            review = review_section(draft, facts)
        last_issues = review.issues

        logger.info(f"Reviewer found {len(last_issues)} issues in round {round_num}")
        for issue in last_issues:
            logger.info(
                "Review issue in round %d: claim=%s | problem=%s",
                round_num,
                issue.claim,
                issue.problem,
            )

        # Step 3: Check if approved
        if review.passed:
            logger.info(f"Draft approved after round {round_num}")
            return {
                "draft": draft,
                "passed": True,
                "rounds_used": rounds_used,
                "issues": [],
            }

        # Step 4: Not approved - prepare feedback for next round
        # Format issues as a string for the writer
        issues_str = "\n".join(
            f"- claim: '{issue.claim}', problem: '{issue.problem}'"
            for issue in last_issues
        )
        current_feedback = (
            f"Fix the following issues in the draft using only the provided facts:\n"
            f"{issues_str}"
        )

        logger.info(f"Draft not approved after round {round_num}, will retry with feedback")

    # Max rounds exceeded without approval
    logger.info(f"Exhausted {max_rounds} rounds without approval")
    return {
        "draft": draft if 'draft' in locals() else None,
        "passed": False,
        "rounds_used": rounds_used,
        "issues": last_issues,
    }


if __name__ == "__main__":
    # Disable disk cache so every call is real
    from ..cache import toggle_cache
    toggle_cache(enabled=False)

    # Configure logging at INFO
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Hardcoded test facts (Brand X scooter)
    facts = [
        Fact(claim="Brand X sells its scooter for Rs. 250,000.", source_url="https://example.com/1"),
        Fact(claim="Brand X offers a 2-year battery warranty.", source_url="https://example.com/2"),
    ]

    # A deliberately bad first draft with multiple issues
    bad_draft_content = (
        "Brand X is the most expensive scooter in the world, costing Rs. 1,000,000. "
        "It has a 10-year battery warranty and flies like a bird. "
        "Brand X also makes the fastest scooter ever, reaching 200 km/h."
    )

    bad_draft = SectionDraft(
        title="Scooter Review",
        content=bad_draft_content,
        source_urls=["https://example.com/1", "https://example.com/2"],
    )

    question = "Write a review of Brand X scooter features."

    print("=" * 60)
    print("Revision test: bad first draft")
    print("=" * 60)

    result = revise_until_approved(
        question,
        facts,
        max_rounds=MAX_REVISION_ROUNDS,
    )

    print()
    print("=" * 60)
    print("Final result")
    print("=" * 60)
    print(f"passed: {result['passed']}")
    print(f"rounds_used: {result['rounds_used']}")
    print(f"draft content: {result['draft'].content if result['draft'] else 'None'}")
    print(f"issues: {len(result['issues'])}")
    for issue in result['issues']:
        print(f"  - '{issue.claim}': {issue.problem}")