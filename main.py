import argparse
import logging
import sys
import time

from app.schemas import ResearchResult
from app.agents.researcher import research

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
        "--no-cache",
        action="store_true",
        help="Disable disk cache (.cache/ folder)",
    )
    args = parser.parse_args()

    question = args.question

    # Log active provider and key fingerprints (first 5 chars only)
    from app.config import LLM_PROVIDER, GEMINI_API_KEY, TAVILY_API_KEY, ANTHROPIC_API_KEY
    provider_label = f"LLM_PROVIDER={LLM_PROVIDER}"
    key_fingerprints = []
    if GEMINI_API_KEY:
        key_fingerprints.append(f"GEMINI_KEY={GEMINI_API_KEY[:5]}...")
    if TAVILY_API_KEY:
        key_fingerprints.append(f"TAVILY_KEY={TAVILY_API_KEY[:5]}...")
    if ANTHROPIC_API_KEY:
        key_fingerprints.append(f"ANTHROPIC_KEY={ANTHROPIC_API_KEY[:5]}...")
    logger.info(f" {provider_label} | {' | '.join(key_fingerprints)}")
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
        print(f"Sections completed: {len(report.sections)}")
        print(f"Unique sources: {len(report.sources)}")
        for i, s in enumerate(report.sections, 1):
            print(f"  {i}. {s.title}")
        print(f"Sources: {report.sources}")

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