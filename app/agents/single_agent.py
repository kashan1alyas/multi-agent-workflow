import logging
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..llm import ask_json
from ..metrics import metrics
from ..schemas import Issue, Report, SectionDraft, SectionResult
from ..tools.search import search_web

logger = logging.getLogger(__name__)

MAX_STEPS = 10
MAX_SEARCHES = 8
DEFAULT_MAX_SECTIONS = 3


class AgentSection(BaseModel):
    title: str
    content: str
    source_urls: list[str] = Field(default_factory=list)


class AgentAction(BaseModel):
    action: Literal["search", "finish"]
    query: str = ""
    sections: list[AgentSection] = Field(default_factory=list)


class FinishAction(BaseModel):
    action: Literal["finish"]
    sections: list[AgentSection] = Field(default_factory=list)


def _normalize_url(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{netloc}{path}"


def _build_prompt(topic: str, search_results: list[dict[str, str]]) -> str:
    context = "\n\n".join(
        f"[{index}] Title: {result.get('title', '')}\n"
        f"      URL: {result.get('url', '')}\n"
        f"      Snippet: {result.get('content', '')[:3000]}"
        for index, result in enumerate(search_results, 1)
    )
    return (
        f"TOPIC: {topic}\n\n"
        "You are a single-agent market research baseline. Plan the research, "
        "decide what to search, write the report sections, and check each claim "
        "against the raw search results yourself. Use only the supplied search "
        "results and cite their exact URLs. Search when evidence is insufficient; "
        "when finished, return sections with title, content, and source_urls. "
        "Never invent source URLs. Each section must be supported by one or more "
        "search result URLs. Return a JSON action with either action='search' and "
        "a query, or action='finish' and sections.\n\n"
        f"RAW SEARCH RESULTS:\n{context if context else '(none yet)'}"
    )


def run_single_agent(topic: str, max_sections: int | None = None) -> Report:
    """Run the bounded single-agent plan, search, write, and self-check loop."""
    section_limit = (
        max(0, max_sections)
        if max_sections is not None
        else DEFAULT_MAX_SECTIONS
    )
    all_results: list[dict[str, str]] = []
    allowed_urls: set[str] = set()
    output_sections: list[AgentSection] = []
    search_count = 0

    with metrics.stage("single_agent"):
        for step in range(1, MAX_STEPS + 1):
            force_finish = step == MAX_STEPS or search_count >= MAX_SEARCHES
            schema: type[AgentAction] | type[FinishAction] = (
                FinishAction if force_finish else AgentAction
            )
            action = ask_json(
                system=(
                    "Return exactly one provider-independent JSON action. "
                    "Search action: {\"action\":\"search\",\"query\":\"...\"}. "
                    "Finish action: {\"action\":\"finish\",\"sections\":["
                    "{\"title\":\"...\",\"content\":\"...\",\"source_urls\":[...]}]}."
                    f" Return no more than {section_limit} sections."
                    + (
                        " You must finish now; do not request another search."
                        if force_finish
                        else ""
                    )
                ),
                user=_build_prompt(topic, all_results),
                schema=schema,
            )
            if action.action == "finish":
                output_sections = action.sections[:section_limit]
                break
            if search_count >= MAX_SEARCHES:
                logger.warning("Single-agent search limit reached; requiring finish.")
                continue

            results = search_web(action.query, max_results=5)
            search_count += 1
            all_results.extend(results)
            allowed_urls.update(
                result["url"] for result in results if result.get("url")
            )
        else:
            logger.warning("Single-agent step limit reached without finish action.")

    normalized_allowed = {_normalize_url(url): url for url in allowed_urls}
    section_results: list[SectionResult] = []
    all_sources: list[str] = []
    for index, output in enumerate(output_sections, 1):
        valid_sources: list[str] = []
        for source_url in output.source_urls:
            normalized_source = _normalize_url(source_url)
            matched = normalized_allowed.get(normalized_source)
            if matched is None:
                matched = next(
                    (
                        allowed_url
                        for normalized_url, allowed_url in normalized_allowed.items()
                        if normalized_source.startswith(normalized_url)
                        or normalized_url.startswith(normalized_source)
                    ),
                    None,
                )
            if matched and matched not in valid_sources:
                valid_sources.append(matched)
        if valid_sources:
            draft = SectionDraft(
                title=output.title,
                content=output.content,
                source_urls=valid_sources,
            )
            passed = True
            issues: list[Issue] = []
            for source_url in valid_sources:
                if source_url not in all_sources:
                    all_sources.append(source_url)
        else:
            draft = SectionDraft(
                title=output.title,
                content="Not enough verified information found.",
                source_urls=[],
            )
            passed = False
            issues = [Issue(claim="", problem="no facts retrieved")]

        section_results.append(
            SectionResult(
                draft=draft,
                passed=passed,
                issues=issues,
                sources=valid_sources,
                original_index=index,
            )
        )

    return Report(
        topic=topic,
        sections=section_results,
        sources=all_sources,
    )
