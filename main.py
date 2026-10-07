import argparse
import logging
import sys
import time

from app.schemas import ResearchResult
from app.agents.researcher import research
from app.agents.revision import MAX_REVISION_ROUNDS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Market Research Report Generator - Week 1"
    )
    parser.add_argument(
        "question",
        nargs="?",
        default="What are the main trends in electric scooters in Pakistan?",
        help="The research question to answer",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="Run single-question research mode (old behavior)",
    )
    parser.add_argument(
        "--pipeline",
        action="store_true",
        help="Run full pipeline: plan -> research -> write -> report",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=None,
        help="Maximum number of sections to process (for testing)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=MAX_REVISION_ROUNDS,
        help=f"Maximum writer/reviewer rounds per section (default: {MAX_REVISION_ROUNDS})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable disk cache (.cache/ folder)",
    )
    args = parser.parse_args()

    question = args.question

    from app.config import (
        ANTHROPIC_MODEL,
        GEMINI_MODEL,
        LLM_PROVIDER,
        OLLAMA_MODEL,
    )
    active_model = {
        "gemini": GEMINI_MODEL,
        "ollama": OLLAMA_MODEL,
        "anthropic": ANTHROPIC_MODEL,
    }[LLM_PROVIDER]
    logger.info("LLM_PROVIDER=%s | MODEL=%s", LLM_PROVIDER, active_model)
    logger.info(f"Starting research for: '{question}'")

    if args.research:
        # Old single-question research mode
        logger.info(f"Running research-only mode for: '{question}'")
        result: ResearchResult = research(question=question)

        print(f"\nResearch question: {result.question}\n")
        if result.facts:
            for i, fact in enumerate(result.facts, 1):
                print(f"  {i}. {fact.claim}")
                print(f"     Source: {fact.source_url}")
        else:
            print("  No verifiable facts found.")

        print(f"\n--- Summary ---")
        print(f"Facts returned: {len(result.facts)}")
        print(f"Facts after URL guard: {len(result.facts)}")

    elif args.pipeline:
        from app.pipeline import run_pipeline, print_report
        from app.report import save_report

        # Time the pipeline run
        main._pipeline_start = time.time()
        logger.info(f"Running pipeline for: '{question}'")

        # Pass cache setting and max_sections to pipeline
        report = run_pipeline(
            question,
            max_sections=args.max_sections,
            use_cache=not args.no_cache,
            max_rounds=args.max_rounds,
        )

        # Check if pipeline failed (returned None)
        if report is None:
            print(
                "Error: Pipeline did not complete successfully. "
                "Check the logs above for details."
            )
            sys.exit(1)

        # Save the report to disk
        report_path = save_report(report)

        total_time = time.time() - main._pipeline_start

        # Print summary
        print(f"\nReport saved to: {report_path}")
        print(f"Total time: {total_time:.1f}s")
        print(f"Sections processed: {len(report.sections)}")
        print(f"Unique sources: {len(report.sources)}")
        
        # Print per-section summary
        passed = sum(1 for s in report.sections if s.passed)
        insufficient = sum(
            1
            for s in report.sections
            if any(issue.problem == "no facts retrieved" for issue in s.issues)
        )
        failed = len(report.sections) - passed - insufficient
        print(
            f"Sections passed: {passed}, failed reviews: {failed}, "
            f"insufficient evidence: {insufficient}"
        )
        for i, s in enumerate(report.sections, 1):
            insufficient_evidence = any(
                issue.problem == "no facts retrieved" for issue in s.issues
            )
            status = (
                "PASS"
                if s.passed
                else "INSUFFICIENT EVIDENCE"
                if insufficient_evidence
                else "FAIL"
            )
            issue_count = len(s.issues)
            print(f"  {i}. {s.draft.title} [{status}] (issues: {issue_count})")
        
        # Print full report using the print_report helper
        print_report(report)

    else:
        result: ResearchResult = research(question=question)

        # Print numbered facts with source URLs
        print(f"\nResearch question: {result.question}\n")
        if result.facts:
            for i, fact in enumerate(result.facts, 1):
                print(f"  {i}. {fact.claim}")
                print(f"     Source: {fact.source_url}")
        else:
            print("  No verifiable facts found.")

        print(f"\n--- Summary ---")
        print(f"Facts returned: {len(result.facts)}")

        # Count dropped facts: these would be facts whose source_url wasn't in the search results.
        # Since researcher.py already filters them, we just report the count.
        # For now, we can't easily compute "dropped" without re-running search, but we report the result count.
        print(f"Facts after URL guard: {len(result.facts)}")


if __name__ == "__main__":
    main()