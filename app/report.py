import json
import logging
import re
import os
from urllib.parse import urlparse
from typing import List

from app.schemas import Report, SectionResult, Issue
from app.llm import ask, ask_json

logger = logging.getLogger(__name__)


def _slugify(topic: str) -> str:
    """Convert a topic string to a filesystem-safe slug."""
    topic = re.sub(r"[^\w\s-]", "", topic.strip()).lower()
    return re.sub(r"[-\s]+", "-", topic)


def _format_source_list(source_urls: List[str]) -> str:
    """Format a list of source URLs as a numbered reference list."""
    if not source_urls:
        return "-"
    lines = []
    for i, url in enumerate(source_urls, 1):
        parsed = urlparse(url)
        domain = parsed.netloc or url
        lines.append(f"  {i}. **{domain}** — {url}")
    return "\n".join(lines)


def _format_issues(issues: List[Issue]) -> str:
    """Format a list of issues as a concise summary."""
    if not issues:
        return "-"
    lines = []
    for issue in issues:
        lines.append(f"  - **{issue.claim}**: {issue.problem}")
    return "\n".join(lines)


def generate_report(report: Report, output_dir: str = "reports") -> str:
    """Generate a Markdown report from a pipeline Report result.

    Steps:
        1. Collect approved sections (passed=True) for the executive summary.
        2. Call ask_json with the approved sections to generate a one-paragraph
           executive summary using ONLY those approved sections - no outside knowledge.
        3. Write the Markdown file to <output_dir>/<topic-slug>.md.
        4. Include:
           - Report title (from the Report.topic)
           - Executive summary (from LLM, approved sections only)
           - Each section with its draft content and numbered source URL references
           - A clearly labeled "Unverified sections" note for any passed=False sections
        5. Ensure the output directory is in .gitignore (assumed pre-configured).

    Returns the path to the generated Markdown file.
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Separate approved and unverified sections
    approved_sections = [s for s in report.sections if s.passed]
    unverified_sections = [s for s in report.sections if not s.passed]

    # --- Generate executive summary using LLM with approved sections only ---
    summary_parts = []
    for s in approved_sections:
        summary_parts.append(f"Section: {s.draft.title}\nContent: {s.draft.content}")

    summary_prompt = f"""
You are writing an executive summary for a market research report.

Topic: {report.topic}

Using ONLY the approved sections below (passed review, no issues), write a concise
one-paragraph executive summary (3-5 sentences maximum). Do NOT use any outside
knowledge - rely strictly on the content provided below. Do not cite section numbers
or reference individual sections; just write a coherent summary of the overall findings.

Approved sections content:
{"\n\n---\n\n".join(summary_parts)}
"""

    summary_result = ask(
        system="You are a market research writer. Write a concise executive summary "
               "using ONLY the provided approved section content. No outside knowledge, "
               "no citations, no prose beyond the summary itself.",
        user=summary_prompt,
    )

    # The ask_json may return just the text or a validated result; extract the text
    if isinstance(summary_result, str):
        executive_summary = summary_result.strip()
    elif isinstance(summary_result, dict):
        executive_summary = summary_result.get("text", str(summary_result)).strip()
    else:
        executive_summary = str(summary_result).strip()

    # --- Build Markdown content ---
    lines = []

    # Title
    lines.append(f"# {report.topic}")
    lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(executive_summary)
    lines.append("")

    # Sections
    lines.append("## Sections")
    lines.append("")

    for i, section in enumerate(report.sections, 1):
        status_label = "✅ Approved" if section.passed else "❌ Unverified"
        lines.append(f"### {i}. {section.draft.title} [{status_label}]")
        lines.append("")
        lines.append(section.draft.content)
        lines.append("")
        lines.append(f"*Sources: {_format_source_list(section.sources)}*")
        lines.append("")

    # Unverified sections note
    if unverified_sections:
        lines.append("## Unverified Sections")
        lines.append("")
        lines.append("The following sections did not pass review after the maximum number "
                      "of rounds. These represent areas where the draft could not be "
                      "verified against the provided facts:")
        lines.append("")
        for i, section in enumerate(unverified_sections, 1):
            issue_summary = _format_issues(section.issues) if section.issues else "- no specific issues logged"
            lines.append(f"### {i}. {section.draft.title} (failed review)")
            lines.append("")
            lines.append(f"  Content: {section.draft.content}")
            lines.append("")
            lines.append(f"  Issues: {issue_summary}")
            lines.append("")
            lines.append(f"  Sources: {_format_source_list(section.sources)}")
            lines.append("")

    # Write the file
    slug = _slugify(report.topic)
    filepath = os.path.join(output_dir, f"{slug}.md")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Generated Markdown report: {filepath}")
    return filepath


def print_report_summary(report: Report) -> None:
    """Print a quick summary of the report to console."""
    passed = sum(1 for s in report.sections if s.passed)
    failed = sum(1 for s in report.sections if not s.passed)
    print(f"\nReport: {report.topic}")
    print(f"  Sections: {len(report.sections)} (passed: {passed}, failed: {failed})")
    print(f"  Sources: {len(report.sources)}")