import logging
import json
from pathlib import Path
import time
from typing import List, Optional

from pydantic import ValidationError

from app.schemas import Plan, SectionDraft, Report, Fact, SectionResult, Issue
from app.report import EMPTY_ISSUE, section_group, sort_sections
from app.agents.planner import plan
from app.agents.researcher import research
from app.agents.writer import write_section
from app.agents.revision import MAX_REVISION_ROUNDS, revise_until_approved
from app.agents.supervisor import decide, Decision
from app.llm import LLMProviderError, ask_json
from app.metrics import metrics
from app.config import MAX_SECTIONS_LIMIT
from app.agents.verifier import apply_verification, verify_section
from app.agents.editor import apply_editor_result, edit_report

logger = logging.getLogger(__name__)

# Disk cache root: <project_root>/.cache/
import os
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

# Maximum extra search rounds per section and per run
MAX_EXTRA_SEARCHES = 6
MAX_EXTRA_ROUNDS_PER_SECTION = 2


def run_pipeline(
    topic: str,
    max_sections: Optional[int] = None,
    max_rounds: int = MAX_REVISION_ROUNDS,
    plan_file: Optional[str] = None,
    no_review: bool = False,
    no_supervisor: bool = False,
    no_verifier: bool = False,
    no_editor: bool = False,
    single_agent: bool = False,
) -> Optional[Report]:
    """Run the full research pipeline for a given topic.

    Steps:
        1. Plan: Break the topic into research sections.
        2. For each section: research the question, then use revise_until_approved
           to write and review the draft.
        3. Assemble the report with deduplicated source URLs and per-section pass/fail status.

    If planning fails or zero sections complete, returns None (caller should
    print error and exit with nonzero code).

    If daily quota is exhausted, raises RuntimeError.

    Each section is independently processed - if a section fails after max_rounds,
    it is marked as unverified (passed=False) but the pipeline continues with
    remaining sections.

    Args:
        topic: The research topic string.
        max_sections: Maximum number of sections to process (None = all).
        max_rounds: Maximum write/review rounds per section.
        plan_file: Optional path to load a plan from or save a newly generated plan to.
        no_review: Draft sections without running the reviewer.
        no_supervisor: Switch off the Supervisor gap-filling loop for comparison testing.
        no_verifier: Skip checking final sentences against their original source pages.
        no_editor: Skip report-level summarization and duplicate detection.
        single_agent: Run the bounded single-agent baseline instead of the pipeline.

    Returns:
        A Report containing the topic, per-section SectionResult objects with
        draft/passed/issues/sources, and deduplicated source URLs,
        or None if the pipeline couldn't complete.
    """
    metrics.reset()

    logger.info(f"Starting pipeline for topic: '{topic}'")
    start_time = time.time()
    requested_sections = max_sections if max_sections is not None else 5
    if single_agent:
        from app.agents.single_agent import run_single_agent

        report = run_single_agent(topic, max_sections=max_sections)
        metrics.record_section_counts(
            sections=len(report.sections),
            insufficient_evidence_sections=sum(
                section_group(section) == 2 for section in report.sections
            ),
        )
        logger.info(
            "Single-agent baseline finished in %.2fs with %d sections",
            time.time() - start_time,
            len(report.sections),
        )
        single_agent_request = (
            requested_sections if max_sections is not None else len(report.sections)
        )
        logger.info(
            "requested=%d limit=%d planned=%d researched=%d",
            single_agent_request,
            MAX_SECTIONS_LIMIT,
            len(report.sections),
            len(report.sections),
        )
        return report

    # === Step 1: Plan ===
    logger.info("Step 1: Planning section breakdown...")
    plan_start = time.time()
    try:
        plan_path = Path(plan_file) if plan_file else None
        plan_result = None
        if plan_path is not None and plan_path.exists():
            saved = json.loads(plan_path.read_text(encoding="utf-8"))
            saved_plan_data = saved.get("plan", saved) if isinstance(saved, dict) else saved
            candidate = Plan.model_validate(saved_plan_data)
            if len(candidate.sections) == requested_sections:
                plan_result = candidate
                logger.info("Loaded plan from %s", plan_path)
            else:
                logger.info(
                    "Saved plan has %d sections; requested %d. Regenerating.",
                    len(candidate.sections),
                    requested_sections,
                )
        if plan_result is None:
            with metrics.stage("plan"):
                plan_result = plan(topic, n_sections=requested_sections)
            if plan_path is not None:
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(
                    json.dumps(
                        {
                            "n_sections": requested_sections,
                            "plan": plan_result.model_dump(mode="json"),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                logger.info("Saved plan to %s", plan_path)
        plan_elapsed = time.time() - plan_start
        logger.info(f"Planning completed in {plan_elapsed:.2f}s: {len(plan_result.sections)} sections")
    except LLMProviderError:
        logger.exception("LLM provider failed during planning")
        raise
    except Exception as e:
        logger.error(f"Planning failed: {e}")
        return None

    if not plan_result.sections:
        logger.error("No sections generated by planner. Cannot continue.")
        return None

    sections_to_process = plan_result.sections

    section_results: List[SectionResult] = []
    all_source_urls: set = set()
    researched_sections = 0

    # === Step 2: Research + Write+Review each section sequentially ===
    # Track extra search budget: total across all sections, and per-section round count
    total_extra_searches = 0
    # Track queries used per section for the supervisor
    section_queries: dict[int, List[str]] = {}

    for i, section_plan in enumerate(sections_to_process, 1):
        researched_sections += 1
        section_num = i
        logger.info(f"Step 2.{section_num}: Researching section '{section_plan.title}'...")
        try:
            # Track this section's query budget
            section_queries[section_num] = [section_plan.search_query] if section_plan.search_query else []

            # Research with the concise query while retaining the full question for extraction.
            logger.info(
                "Section %d final search_query: %s",
                section_num,
                section_plan.search_query,
            )
            research_start = time.time()
            with metrics.stage("research"):
                research_result = research(
                    question=section_plan.question,
                    search_query=section_plan.search_query,
                )
            research_elapsed = time.time() - research_start

            if research_result is None:
                logger.warning(
                    "Section %d: No facts retrieved, marking as insufficient evidence.",
                    section_num,
                )
                section_results.append(
                    SectionResult(
                        draft=SectionDraft(
                            title=section_plan.title,
                            content="Not enough verified information found.",
                            source_urls=[],
                        ),
                        passed=False,
                        issues=[Issue(claim="", problem="no facts retrieved")],
                        sources=[],
                        original_index=section_num,
                    )
                )
                logger.info(
                    "Section %d research finished in %.2fs (no facts)",
                    section_num,
                    research_elapsed,
                )
                continue

            if not research_result.facts:
                if no_supervisor:
                    logger.warning(
                        "Section %d: No facts retrieved, marking as insufficient evidence.",
                        section_num,
                    )
                    section_results.append(
                        SectionResult(
                            draft=SectionDraft(
                                title=section_plan.title,
                                content="Not enough verified information found.",
                                source_urls=[],
                            ),
                            passed=False,
                            issues=[Issue(claim="", problem="no facts retrieved")],
                            sources=[],
                            original_index=section_num,
                        )
                    )
                    logger.info(
                        "Section %d research finished in %.2fs (no facts)",
                        section_num,
                        research_elapsed,
                    )
                    continue
                # else: fall through to supervisor loop with zero facts;
                # the Supervisor will decide whether to search again or give up

            logger.info(
                "Section %d research finished in %.2fs (%d facts)",
                section_num,
                research_elapsed,
                len(research_result.facts),
            )

            # --- Supervisor loop (or direct proceed if --no-supervisor) ---
            if no_supervisor:
                logger.info(
                    "Section %d: --no-supervisor mode, proceeding directly to write+review",
                    section_num,
                )
                # Use revise_until_approved to write and review the draft
                logger.info(f"Section {section_num}: Starting write+review cycle...")
                if no_review:
                    with metrics.stage("write"):
                        draft = write_section(
                            section_plan.title,
                            research_result.facts,
                        )
                    revise_result = {
                        "draft": draft,
                        "passed": False,
                        "issues": [Issue(claim="", problem="review skipped (--no-review)")],
                    }
                else:
                    revise_result = revise_until_approved(
                        question=section_plan.title,
                        facts=research_result.facts,
                        max_rounds=max_rounds,
                    )

                section_sources = (
                    revise_result["draft"].source_urls
                    if revise_result["draft"]
                    else []
                )
                section_result = SectionResult(
                    draft=revise_result["draft"] if revise_result["draft"] else SectionDraft(
                        title=section_plan.title,
                        content="Not enough verified information found.",
                        source_urls=[],
                    ),
                    passed=revise_result["passed"],
                    issues=revise_result["issues"],
                    sources=section_sources,
                    original_index=section_num,
                )
                if not no_verifier and section_result.passed:
                    with metrics.stage("verify"):
                        checks = verify_section(section_result.draft)
                    content, summary = apply_verification(
                        section_result.draft.content,
                        checks,
                    )
                    section_result.draft.content = content
                    section_result.sentence_checks = checks
                    section_result.source_check_summary = summary

                for url in section_sources:
                    all_source_urls.add(url)

                section_results.append(section_result)
                logger.info(
                    "Section %d completed: passed=%s, issues=%d",
                    section_num,
                    revise_result["passed"],
                    len(revise_result["issues"]),
                )
            else:
                # Supervisor loop
                extra_rounds = 0
                enough = False
                section_gave_up = False

                while extra_rounds < MAX_EXTRA_ROUNDS_PER_SECTION:
                    # Call the Supervisor to decide if we have enough facts
                    with metrics.stage("supervise"):
                        decision: Decision = decide(
                            section_question=section_plan.question,
                            facts=research_result.facts,
                            queries_used=section_queries[section_num],
                        )

                    logger.info(
                        "Section %d Supervisor: action=%s, reason=%s",
                        section_num,
                        decision.action,
                        decision.reason,
                    )

                    if decision.action == "enough":
                        enough = True
                        break
                    elif decision.action == "give_up":
                        section_gave_up = True
                        break
                    elif decision.action == "search_again":
                        # Check global budget: at most MAX_EXTRA_SEARCHES = 6 per run
                        if total_extra_searches >= MAX_EXTRA_SEARCHES:
                            logger.warning(
                                "Section %d: Max extra searches (%d) reached, stopping extra rounds",
                                section_num,
                                MAX_EXTRA_SEARCHES,
                            )
                            total_extra_searches = MAX_EXTRA_SEARCHES
                            break

                        # Add up to 2 new queries that differ from every query already used
                        new_queries = decision.new_queries
                        if not new_queries:
                            new_queries = _generate_fallback_queries(
                                section_plan.question,
                                section_queries[section_num],
                            )

                        # Validate that new queries differ from all already-used queries
                        validated_queries = []
                        for q in new_queries:
                            if q not in section_queries[section_num]:
                                validated_queries.append(q)
                            else:
                                logger.warning(
                                    "Section %d: Query '%s' already used, skipping",
                                    section_num,
                                    q,
                                )

                        if not validated_queries:
                            logger.warning(
                                "Section %d: No new valid queries after filtering, stopping extra rounds",
                                section_num,
                            )
                            break

                        # Add the new queries to the section's used list
                        section_queries[section_num].extend(validated_queries)
                        total_extra_searches += len(validated_queries)

                        logger.info(
                            "Section %d: Queuing %d new query/queries (total extra searches: %d/%d)",
                            section_num,
                            len(validated_queries),
                            total_extra_searches,
                            MAX_EXTRA_SEARCHES,
                        )

                        # Re-search with the new extra queries
                        with metrics.stage("research"):
                            research_result = research(
                                question=section_plan.question,
                                search_query=section_plan.search_query,
                                extra_queries=validated_queries,
                            )

                        extra_rounds += 1
                        logger.info(
                            "Section %d: Extra round %d completed (%d facts so far)",
                            section_num,
                            extra_rounds,
                            len(research_result.facts),
                        )
                # while loop completed (either by condition or break)

                if section_gave_up:
                    logger.warning(
                        "Section %d: Supervisor gave up on this section", section_num,
                    )
                    section_results.append(
                        SectionResult(
                            draft=SectionDraft(
                                title=section_plan.title,
                                content="Not enough verified information found.",
                                source_urls=[],
                            ),
                            passed=False,
                            issues=[Issue(claim="", problem="supervisor gave up")],
                            sources=[],
                            original_index=section_num,
                        )
                    )
                    logger.info(
                        "Section %d research finished in %.2fs (gave up)",
                        section_num,
                        research_elapsed,
                    )
                    continue

                if enough:
                    # Use revise_until_approved to write and review the draft
                    logger.info(f"Section {section_num}: Starting write+review cycle...")
                    if no_review:
                        with metrics.stage("write"):
                            draft = write_section(
                                section_plan.title,
                                research_result.facts,
                            )
                        revise_result = {
                            "draft": draft,
                            "passed": False,
                            "issues": [Issue(claim="", problem="review skipped (--no-review)")],
                        }
                    else:
                        revise_result = revise_until_approved(
                            question=section_plan.title,
                            facts=research_result.facts,
                            max_rounds=max_rounds,
                        )

                    section_sources = (
                        revise_result["draft"].source_urls
                        if revise_result["draft"]
                        else []
                    )
                    section_result = SectionResult(
                        draft=revise_result["draft"] if revise_result["draft"] else SectionDraft(
                            title=section_plan.title,
                            content="Not enough verified information found.",
                            source_urls=[],
                        ),
                        passed=revise_result["passed"],
                        issues=revise_result["issues"],
                        sources=section_sources,
                        original_index=section_num,
                    )
                    if not no_verifier and section_result.passed:
                        with metrics.stage("verify"):
                            checks = verify_section(section_result.draft)
                        content, summary = apply_verification(
                            section_result.draft.content,
                            checks,
                        )
                        section_result.draft.content = content
                        section_result.sentence_checks = checks
                        section_result.source_check_summary = summary

                    for url in section_sources:
                        all_source_urls.add(url)

                    section_results.append(section_result)
                    logger.info(
                        "Section %d completed: passed=%s, issues=%d",
                        section_num,
                        revise_result["passed"],
                        len(revise_result["issues"]),
                    )
                else:
                    # Loop exhausted without reaching 'enough' or 'give_up'
                    if research_result.facts:
                        # Facts remain after max extra searches; treat as enough
                        logger.info(
                            "Section %d: Max extra searches reached (%d/%d), "
                            "marking as enough after %d extra rounds",
                            section_num,
                            total_extra_searches,
                            MAX_EXTRA_SEARCHES,
                            MAX_EXTRA_ROUNDS_PER_SECTION,
                        )
                        enough = True
                    else:
                        # No facts found after extra searches
                        logger.warning(
                            "Section %d: No facts found after extra searches, "
                            "marking as insufficient",
                            section_num,
                        )
                        section_results.append(
                            SectionResult(
                                draft=SectionDraft(
                                    title=section_plan.title,
                                    content="Not enough verified information found.",
                                    source_urls=[],
                                ),
                                passed=False,
                                issues=[Issue(claim="", problem="no facts found after extra searches")],
                                sources=[],
                                original_index=section_num,
                            )
                        )
                        logger.info(
                            "Section %d research finished in %.2fs (no facts after extra searches)",
                            section_num,
                            research_elapsed,
                        )
                        continue

                    # If facts remain and enough is still False (edge case),
                    # proceed as enough so the section is written
                    logger.info(
                        "Section %d: Facts remain after extra searches; proceeding as enough",
                        section_num,
                    )
        except LLMProviderError:
            logger.exception("LLM provider failed while processing section %d", section_num)
            raise
        except Exception as exc:
            logger.exception("Section %d failed: %s", section_num, exc)
            section_results.append(
                SectionResult(
                    draft=SectionDraft(
                        title=section_plan.title,
                        content="This question could not be completed.",
                        source_urls=[],
                    ),
                    passed=False,
                    issues=[
                        Issue(
                            claim=section_plan.question,
                            problem=f"Question processing failed: {exc}",
                        )
                    ],
                    sources=[],
                    original_index=section_num,
                )
            )

    # === Step 3: Assemble the report ===
    deduplicated_sources = list(all_source_urls)

    logger.info(f"Pipeline finished in {time.time() - start_time:.2f}s: {len(section_results)} sections, {len(deduplicated_sources)} deduplicated sources")

    report = Report(
        topic=topic,
        sections=sort_sections(section_results),
        sources=deduplicated_sources,
    )
    content_section_count = sum(
        1
        for section in report.sections
        if section_group(section) != 2
        and section.draft.content.strip()
        and section.draft.content.strip() != "Not enough verified information found."
    )
    if not no_editor and content_section_count >= 2:
        apply_editor_result(report, edit_report(report))
    metrics.record_section_counts(
        sections=len(section_results),
        insufficient_evidence_sections=sum(
            section_group(result) == 2
            for result in report.sections
        ),
    )
    logger.info(
        "requested=%d limit=%d planned=%d researched=%d",
        requested_sections,
        MAX_SECTIONS_LIMIT,
        len(plan_result.sections),
        researched_sections,
    )
    return report


def _generate_fallback_queries(question: str, queries_used: List[str]) -> List[str]:
    """Generate fallback search queries when the LLM doesn't provide enough new ones.

    Creates simple keyword-based queries that differ from already-used queries.
    """
    fallback = [
        " ".join(question.split()[:5]),  # first 5 words of question as query
        " ".join(question.split()[5:10]) if len(question.split()) > 5 else "",
    ]
    # Filter out empty lists and queries already used
    result = []
    for candidate in fallback:
        if candidate and candidate not in queries_used:
            result.append(candidate)
    return result


def print_report(report: Report) -> None:
    """Print the report sections to console in a readable format."""
    print(f"\n=== Report: {report.topic} ===\n")
    passed_count = 0
    failed_count = 0
    insufficient_count = 0
    sections = sort_sections(report.sections)
    for i, section in enumerate(sections, 1):
        group = section_group(section)
        status = (
            "PASS"
            if group == 0
            else "FAIL"
            if group == 1
            else "NO EVIDENCE"
        )
        if group == 2:
            insufficient_count += 1
        elif group == 0:
            passed_count += 1
        else:
            failed_count += 1
        print(f"  {i}. {section.draft.title} [{status}]")
        if section.source_check_summary:
            print(f"     Source check: {section.source_check_summary}")
        print(f"     Content: {section.draft.content[:200]}{'...' if len(section.draft.content) > 200 else ''}")
        print(f"     Sources: {section.sources}")
        if group == 2:
            print(f"     Issue: {EMPTY_ISSUE}")
        elif section.issues:
            print(f"     Issues: {len(section.issues)} issue(s)")
            for issue in section.issues:
                print(f"       - '{issue.claim}': {issue.problem}")
    print(f"\n  Total sections: {len(sections)}")
    print(
        f"  Passed: {passed_count}, Failed reviews: {failed_count}, "
        f"Insufficient evidence: {insufficient_count}"
    )
    print(f"  Total deduplicated sources: {len(report.sources)}")
    print(f"  Sources: {report.sources}\n")