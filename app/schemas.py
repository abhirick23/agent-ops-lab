"""Shared Pydantic models: corpus records and the public API contract."""
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class Paper(BaseModel):
    id: str
    title: str
    abstract: str
    authors: list[str] = []
    published: str = ""
    categories: list[str] = []
    url: str = ""


class Source(BaseModel):
    id: str
    title: str
    url: str


class Step(BaseModel):
    """One tool invocation made by the agent."""

    turn: int
    tool: str
    arguments: dict
    ok: bool
    output_preview: str


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    max_steps: int | None = Field(default=None, ge=1, le=10)


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    steps: list[Step]
    tokens: TokenUsage
    stopped_reason: Literal["answered", "max_steps"]
