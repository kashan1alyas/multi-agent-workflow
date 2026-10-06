import asyncio
import logging
import time
from typing import List, Optional

from pydantic import ValidationError

from ..schemas import Plan, SectionDraft, Report, Fact
from ..agents.planner import plan
from ..agents.researcher import research
from ..agents.writer import write_section
from ..llm import ask_json


logger = logging.getLogger(__name__)


def _sleep(seconds: int) -> None:
    """Simple blocking sleep."""
    time.sleep(seconds)


def _run_with_retries(
    func,
    args: tuple = (),
    kwargs: dict = None,
    max_attempts: int = 3,
    backoff_seconds: int = 20,
    error_msg: str = "",
) -> Optional:
    """Run a function with retry logic for 429 rate-limit errors.

    Args:
        func: The async or sync function to call.
        args: Positional arguments for func.
        kwargs: Keyword arguments for func.
        max_attempts: Maximum number of attempts (including the first).
        backoff_seconds: Seconds to wait on 429 errors.
        error_msg: Prefix for error logging.

    Returns:
        The function result, or None if all attempts fail.
    """
    if kwargs is None:
        kwargs = {}
    attempt = 0
    while attempt < max_attempts:
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            err_str = str(e)
            # Check for rate-limit / 429 errors
            is_rate_limit = "429" in err_str or "rate" in err_str.lower() or "too many" in err_str.lower()
            attempt += 1
            if is_rate_limit and attempt < max_attempts:
                logger.warning(f"{error_msg} Attempt {attempt}/{max_attempts} failed with rate-limit error. Waiting {backoff_seconds}s...")
                _sleep(backoff_seconds)
                continue
            else:
                logger.error(f"{error_msg} All {max_attempts} attempts failed. Last error: {err_str}")
                return None
    return None


def run_pipeline(topic: str) -> Report:
    """Run the full research pipeline for a given topic.

    Steps:
        1. Plan: Break the topic into research sections.
        2. For each section: research the question sequentially, then write the section.
        3. Assemble the report with deduplicated source URLs.

    If a section fails (research or write), it is logged and skipped; the pipeline continues.

    Args:
        topic: The research topic string.

    Returns:
        A Report containing the topic, list of drafted sections, and deduplicated source URLs.
    """
    logger.info(f"Starting pipeline for topic: '{topic}'")
    start_time = time.time()

    # === Step 1: Plan ===
    logger.info("Step 1: Planning section breakdown...")
    plan_start = time.time()
    try:
        plan_result: Plan = plan(topic)
        plan_elapsed = time.time() - plan_start
        logger.info(f"Planning completed in {plan_elapsed:.2f}s: {len(plan_result.sections)} sections")
    except Exception as e:
        logger.error(f"Planning failed: {e}")
        return Report(topic=topic, sections=[], sources=[])

    all_sections: List[SectionDraft] = []
    all_source_urls: set = set()

    # === Step 2: Research + Write each section sequentially ===
    for i, section_plan in enumerate(plan_result.sections, 1):
        section_num = i
        logger.info(f"Step 2.{section_num}: Researching section '{section_plan.title}'...")
        section_research_start = time.time()

        # Research the question for this section
        research_kwargs = {"question": section_plan.question}
        research_result = _run_with_retries(
            research,
            kwargs=research_kwargs,
            max_attempts=3,
            backoff_seconds=20,
            error_msg=f"Section {section_num} research",
        )

        if research_result is None or not research_result.facts:
            logger.warning(f"Section {section_num}: No facts retrieved, skipping write.")
            elapsed = time.time() - section_research_start
            logger.info(f"Section {section_num} research finished in {elapsed:.2f}s (no facts)")
            continue

        logger.info(
            f"Section {section_num} research finished in {time.time() - section_research_start:.2f}s: "
            f"{len(research_result.facts)} facts"
        )

        # Write the section from facts
        write_start = time.time()
        try:
            draft: SectionDraft = write_section(section_plan, research_result.facts)
        except Exception as e:
            logger.error(f"Section {section_num} write failed: {e}")
            elapsed = time.time() - section_research_start
            logger.info(f"Section {section_num} finished in {elapsed:.2f}s (write error)")
            continue

        write_elapsed = time.time() - write_start
        logger.info(
            f"Section {section_num} write finished in {write_elapsed:.2f}s: "
            f"'{draft.title}' with {len(draft.source_urls)} source URLs"
        )

        # Deduplicate source URLs
        for url in draft.source_urls:
            all_source_urls.add(url)

        all_sections.append(draft)
        logger.info(f"Section {section_num} completed.")

    # === Step 3: Assemble report ===
    total_elapsed = time.time() - start_time
    deduplicated_sources = list(all_source_urls)

    logger.info(f"Pipeline finished in {total_elapsed:.2f}s: {len(all_sections)} sections, {len(deduplicated_sources)} deduplicated sources")

    report = Report(
        topic=topic,
        sections=all_sections,
        sources=deduplicated_sources,
    )
    return report


def print_report(report: Report) -> None:
    """Print the report sections to console in a readable format."""
    print(f"\n=== Report: {report.topic} ===\n")
    for i, section in enumerate(report.sections, 1):
        print(f"  {i}. {section.title}")
        print(f"     Content: {section.content[:200]}{'...' if len(section.content) > 200 else ''}")
        print(f"     Sources: {section.source_urls}")
    print(f"\n  Total sections: {len(report.sections)}")
    print(f"  Total deduplicated sources: {len(report.sources)}")
    print(f"  Sources: {report.sources}\n")