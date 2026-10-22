import logging
from typing import Any

from app.agents.editor import EditorResult, apply_editor_result, edit_report
from app.agents.planner import plan
from app.agents.researcher import research
from app.agents.revision import MAX_REVISION_ROUNDS, revise_until_approved
from app.agents.supervisor import Decision, decide
from app.agents.verifier import apply_verification, verify_section
from app.agents.writer import write_section
from app.errors import DailyQuotaExceeded, LLMProviderError
from app.config import MAX_SECTIONS_LIMIT
from app.graph.state import PipelineState, SectionResearch
from app.metrics import metrics
from app.pipeline import (
    MAX_EXTRA_ROUNDS_PER_SECTION,
    MAX_EXTRA_SEARCHES,
    _generate_fallback_queries,
)
from app.report import section_group, sort_sections
from app.schemas import Issue, Plan, Report, SectionDraft, SectionResult

logger = logging.getLogger(__name__)


def _flags(state: PipelineState) -> dict[str, bool]:
    return state.get(
        "flags",
        {
            "no_review": False,
            "no_supervisor": False,
            "no_verifier": False,
            "no_editor": False,
        },
    )


def _failed_result(section, index: int, error: str) -> SectionResult:
    return SectionResult(
        draft=SectionDraft(
            title=section.title,
            content="This question could not be completed.",
            source_urls=[],
        ),
        passed=False,
        issues=[
            Issue(
                claim=section.question,
                problem=f"Question processing failed: {error}",
            )
        ],
        sources=[],
        original_index=index,
    )


def _empty_result(section, index: int, reason: str) -> SectionResult:
    return SectionResult(
        draft=SectionDraft(
            title=section.title,
            content="Not enough verified information found.",
            source_urls=[],
        ),
        passed=False,
        issues=[Issue(claim="", problem=reason)],
        sources=[],
        original_index=index,
    )


def _find_provider_error(error: BaseException) -> LLMProviderError | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, LLMProviderError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def plan_node(state: PipelineState) -> dict[str, Any]:
    max_sections = state.get("max_sections")
    requested = max_sections if max_sections is not None else 5
    try:
        with metrics.stage("plan"):
            result: Plan = plan(state["topic"], n_sections=requested)
        return {"plan": result}
    except LLMProviderError:
        raise
    except Exception as exc:
        logger.error("Planning failed: %s", exc)
        return {"plan": None, "errors": [f"Planning failed: {exc}"]}


def research_node(state: PipelineState) -> dict[str, Any]:
    plan_result = state.get("plan")
    if plan_result is None:
        return {"research_results": []}

    flags = _flags(state)
    total_extra_searches = 0
    records: list[SectionResearch] = []
    for index, section in enumerate(plan_result.sections, 1):
        queries_used = [section.search_query] if section.search_query else []
        try:
            with metrics.stage("research"):
                result = research(
                    question=section.question,
                    search_query=section.search_query,
                )
            if result is None:
                records.append(
                    {
                        "section": section,
                        "original_index": index,
                        "result": None,
                        "error": None,
                        "skip_reason": "no facts retrieved",
                    }
                )
                continue

            skip_reason = None
            if flags["no_supervisor"]:
                if not result.facts:
                    skip_reason = "no facts retrieved"
            else:
                extra_rounds = 0
                enough = False
                gave_up = False
                while extra_rounds < MAX_EXTRA_ROUNDS_PER_SECTION:
                    with metrics.stage("supervise"):
                        try:
                            decision: Decision = decide(
                                section_question=section.question,
                                facts=result.facts,
                                queries_used=queries_used,
                            )
                        except Exception as exc:
                            provider_error = _find_provider_error(exc)
                            if provider_error is not None:
                                raise provider_error from exc
                            raise

                    if decision.action == "enough":
                        enough = True
                        break
                    if decision.action == "give_up":
                        gave_up = True
                        break
                    if decision.action != "search_again":
                        break
                    if total_extra_searches >= MAX_EXTRA_SEARCHES:
                        total_extra_searches = MAX_EXTRA_SEARCHES
                        break

                    new_queries = decision.new_queries or _generate_fallback_queries(
                        section.question,
                        queries_used,
                    )
                    new_queries = [query for query in new_queries if query not in queries_used]
                    if not new_queries:
                        break
                    queries_used.extend(new_queries)
                    total_extra_searches += len(new_queries)
                    with metrics.stage("research"):
                        result = research(
                            question=section.question,
                            search_query=section.search_query,
                            extra_queries=new_queries,
                        )
                    extra_rounds += 1
                    if result is None:
                        break

                if gave_up:
                    skip_reason = "supervisor gave up"
                elif not enough and (result is None or not result.facts):
                    skip_reason = "no facts found after extra searches"
                elif not enough and result.facts:
                    enough = True
                if result is None and skip_reason is None:
                    skip_reason = "no facts retrieved"

            records.append(
                {
                    "section": section,
                    "original_index": index,
                    "result": result,
                    "error": None,
                    "skip_reason": skip_reason,
                }
            )
        except LLMProviderError:
            raise
        except Exception as exc:
            provider_error = _find_provider_error(exc)
            if provider_error is not None:
                raise provider_error from exc
            logger.exception("Section %d research failed", index)
            records.append(
                {
                    "section": section,
                    "original_index": index,
                    "result": None,
                    "error": str(exc) or type(exc).__name__,
                    "skip_reason": None,
                }
            )

    return {"research_results": records}


def write_node(state: PipelineState) -> dict[str, Any]:
    flags = _flags(state)
    max_rounds = state.get("max_rounds", MAX_REVISION_ROUNDS)
    results: list[SectionResult] = []
    for record in state.get("research_results", []):
        section = record["section"]
        index = record["original_index"]
        if record["error"] is not None:
            results.append(_failed_result(section, index, record["error"]))
            continue
        if record["skip_reason"] is not None:
            results.append(_empty_result(section, index, record["skip_reason"]))
            continue

        research_result = record["result"]
        if research_result is None:
            results.append(_empty_result(section, index, "no facts retrieved"))
            continue

        try:
            if flags["no_review"]:
                with metrics.stage("write"):
                    draft = write_section(section.title, research_result.facts)
                revise_result = {
                    "draft": draft,
                    "passed": False,
                    "issues": [
                        Issue(claim="", problem="review skipped (--no-review)")
                    ],
                }
            else:
                revise_result = revise_until_approved(
                    question=section.title,
                    facts=research_result.facts,
                    max_rounds=max_rounds,
                )
            draft = revise_result["draft"]
            section_sources = draft.source_urls if draft else []
            results.append(
                SectionResult(
                    draft=draft
                    if draft
                    else SectionDraft(
                        title=section.title,
                        content="Not enough verified information found.",
                        source_urls=[],
                    ),
                    passed=revise_result["passed"],
                    issues=revise_result["issues"],
                    sources=section_sources,
                    original_index=index,
                )
            )
        except LLMProviderError:
            raise
        except Exception as exc:
            provider_error = _find_provider_error(exc)
            if provider_error is not None:
                raise provider_error from exc
            logger.exception("Section %d writing or review failed", index)
            results.append(_failed_result(section, index, str(exc) or type(exc).__name__))

    return {"section_results": results}


def review_node(state: PipelineState) -> dict[str, Any]:
    results = list(state.get("section_results", []))
    if not _flags(state)["no_verifier"]:
        for section_result in results:
            if section_result.passed:
                with metrics.stage("verify"):
                    checks = verify_section(section_result.draft)
                content, summary = apply_verification(
                    section_result.draft.content,
                    checks,
                )
                section_result.draft.content = content
                section_result.sentence_checks = checks
                section_result.source_check_summary = summary
    return {"section_results": results}


def assemble_node(state: PipelineState) -> dict[str, Any]:
    topic = state["topic"]
    section_results = sort_sections(state.get("section_results", []))
    report = Report(
        topic=topic,
        sections=section_results,
        sources=list({url for section in section_results for url in section.sources}),
    )
    content_section_count = sum(
        1
        for section in report.sections
        if section_group(section) != 2
        and section.draft.content.strip()
        and section.draft.content.strip() != "Not enough verified information found."
    )
    editor_result = None
    if not _flags(state)["no_editor"] and content_section_count >= 2:
        editor_result = edit_report(report)
        apply_editor_result(report, editor_result)
    metrics.record_section_counts(
        sections=len(section_results),
        insufficient_evidence_sections=sum(
            section_group(section) == 2 for section in report.sections
        ),
    )
    requested = state.get("max_sections")
    requested = requested if requested is not None else 5
    planned = len(state["plan"].sections) if state.get("plan") else 0
    logger.info(
        "requested=%d limit=%d planned=%d researched=%d",
        requested,
        MAX_SECTIONS_LIMIT,
        planned,
        len(state.get("research_results", [])),
    )
    return {
        "section_results": section_results,
        "editor_result": editor_result,
        "report": report,
    }
