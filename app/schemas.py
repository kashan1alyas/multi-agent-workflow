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


class Report(BaseModel):
    """A complete market research report."""
    topic: str = Field(description="The research topic.")
    sections: List[SectionDraft] = Field(description="Drafted sections with content and sources.")
    sources: List[str] = Field(description="Deduplicated list of all source URLs used across all sections.")