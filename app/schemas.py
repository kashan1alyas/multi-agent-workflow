from pydantic import BaseModel, Field
from typing import List


class Fact(BaseModel):
    """A verified fact extracted from search results."""
    claim: str = Field(description="The concrete verifiable fact.")
    source_url: str = Field(description="The exact URL where this fact was found.")


class ResearchResult(BaseModel):
    """Structured result from a research query."""
    question: str = Field(description="The original research question.")
    facts: List[Fact] = Field(description="List of verified facts with sources.")

class Section(BaseModel):
    title: str = Field(description="Short title for this section.")
    question: str = Field(description="The research question to answer.")
    search_query: str = Field(description="Short search query (5-10 words) optimized for web search engines.")


class Plan(BaseModel):
    topic: str
    sections: list[Section]


class SectionDraft(BaseModel):
    """A drafted section with title, content, and source URLs."""
    title: str = Field(description="Short title for this section.")
    content: str = Field(description="1-3 short paragraphs drafted from the provided facts.")
    source_urls: List[str] = Field(description="List of source URLs actually used in the content.")


class Issue(BaseModel):
    """A claim or fact problem found in a drafted section."""
    claim: str = Field(description="The claim sentence or number that has an issue.")
    problem: str = Field(description="Description of the problem (e.g. 'number not found in facts').")


class Review(BaseModel):
    """Review result for a drafted section."""
    passed: bool = Field(description="True if no issues were found.")
    issues: List[Issue] = Field(description="List of issues found in the draft.")


class SectionResult(BaseModel):
    """Result for a single pipeline section."""
    draft: SectionDraft = Field(description="The drafted section content.")
    passed: bool = Field(description="True if the draft was approved after review.")
    issues: List[Issue] = Field(description="List of issues found (empty if passed=True).")
    sources: List[str] = Field(description="Source URLs used for this section.")


class Report(BaseModel):
    """A complete market research report."""
    topic: str = Field(description="The research topic.")
    sections: List[SectionResult] = Field(description="Per-section results with draft, pass/fail, and sources.")
    sources: List[str] = Field(description="Deduplicated list of all source URLs used across all sections.")