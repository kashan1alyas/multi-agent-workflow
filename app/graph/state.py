import operator
from typing import Annotated, TypedDict

from app.agents.editor import EditorResult
from app.schemas import Plan, Report, ResearchResult, Section, SectionResult


class GraphFlags(TypedDict):
    no_review: bool
    no_supervisor: bool
    no_verifier: bool
    no_editor: bool


class SectionResearch(TypedDict):
    section: Section
    original_index: int
    result: ResearchResult | None
    error: str | None
    skip_reason: str | None


def merge_section_results(
    current: list[SectionResult], updates: list[SectionResult]
) -> list[SectionResult]:
    merged = list(current)
    index_by_original = {
        section.original_index: position
        for position, section in enumerate(merged)
    }
    for section in updates:
        position = index_by_original.get(section.original_index)
        if position is None:
            index_by_original[section.original_index] = len(merged)
            merged.append(section)
        else:
            merged[position] = section
    return merged


class PipelineState(TypedDict, total=False):
    topic: str
    max_sections: int | None
    max_rounds: int
    plan: Plan | None
    research_results: Annotated[list[SectionResearch], operator.add]
    section_results: Annotated[list[SectionResult], merge_section_results]
    verified_results: list[SectionResult]
    editor_result: EditorResult | None
    report: Report | None
    flags: GraphFlags
    errors: Annotated[list[str], operator.add]
