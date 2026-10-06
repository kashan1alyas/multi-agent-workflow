import argparse
import logging
import sys

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
        "--plan",
        action="store_true",
        help="Generate a research plan with sections and search questions for the default question",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Generate a research draft with sections from verified facts",
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

    if args.plan:
        from app.agents.planner import plan
        logger.info(f"Generating research plan for: '{question}'")
        result = plan(question)
        print(f"\nResearch Plan: {result.topic}\n")
        for i, section in enumerate(result.sections, 1):
            print(f"  {i}. {section.title}")
            print(f"     Question: {section.question}")
            print(f"     Search query: {section.search_query}")
        print(f"\n--- Plan Summary ---")
        print(f"Sections: {len(result.sections)}")
    elif args.draft:
        from app.agents.researcher import research
        from app.agents.writer import write_section
        from app.schemas import Section, SectionDraft, ResearchResult
        
        logger.info(f"Generating research draft for: '{question}'")
        research_result: ResearchResult = research(question=question)
        
        print(f"\nResearch question: {research_result.question}\n")
        print(f"Facts found: {len(research_result.facts)}")
        
        if not research_result.facts:
            print("  No verifiable facts found.")
        else:
            for i, fact in enumerate(research_result.facts, 1):
                print(f"  {i}. {fact.claim} - {fact.source_url}")
            
            # Draft a section using the provided facts
            section = Section(title="Key Findings", question=question, search_query="electric scooters Pakistan")
            draft = write_section(section, research_result.facts)
            
            if isinstance(draft, str):
                print(f"\nDraft: {draft}")
            else:
                print(f"\nDraft - {draft.title}:")
                print(draft.content)
                print(f"\nSource URLs used: {draft.source_urls}")
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
        # We'll just note the number of facts found.
        print(f"Facts after URL guard: {len(result.facts)}")


if __name__ == "__main__":
    main()