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