"""search_papers, get_paper and summarize_paper."""
import re

from pydantic import BaseModel, Field

from app.retrieval.store import PaperStore
from app.schemas import Paper
from app.tools.base import Tool, ToolRegistry


class SearchPapersInput(BaseModel):
    query: str = Field(min_length=1, description="Natural-language search query.")
    k: int = Field(default=5, ge=1, le=10, description="Number of papers to return.")


class SearchResult(BaseModel):
    id: str
    title: str
    snippet: str
    score: float
    url: str


class SearchPapersOutput(BaseModel):
    results: list[SearchResult]


class GetPaperInput(BaseModel):
    paper_id: str = Field(min_length=1, description="arXiv id, e.g. '2401.01234'.")


class GetPaperOutput(BaseModel):
    found: bool
    paper: Paper | None = None


class SummarizeInput(BaseModel):
    paper_id: str = Field(min_length=1, description="arXiv id, e.g. '2401.01234'.")
    max_sentences: int = Field(default=2, ge=1, le=5)


class SummarizeOutput(BaseModel):
    found: bool
    id: str
    title: str = ""
    summary: str = ""


SNIPPET_CHARS = 300


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def build_tools(store: PaperStore) -> ToolRegistry:
    def search(args: SearchPapersInput) -> SearchPapersOutput:
        hits = store.search(args.query, args.k)
        return SearchPapersOutput(
            results=[
                SearchResult(
                    id=h.paper.id,
                    title=h.paper.title,
                    snippet=h.paper.abstract[:SNIPPET_CHARS],
                    score=round(h.score, 4),
                    url=h.paper.url,
                )
                for h in hits
            ]
        )

    def get(args: GetPaperInput) -> GetPaperOutput:
        paper = store.get(args.paper_id)
        return GetPaperOutput(found=paper is not None, paper=paper)

    def summarize(args: SummarizeInput) -> SummarizeOutput:
        paper = store.get(args.paper_id)
        if paper is None:
            return SummarizeOutput(found=False, id=args.paper_id)
        summary = " ".join(_sentences(paper.abstract)[: args.max_sentences])
        return SummarizeOutput(found=True, id=paper.id, title=paper.title, summary=summary)

    return ToolRegistry(
        [
            Tool("search_papers", "Semantic search over the paper corpus. Returns ids, titles and snippets.",
                 SearchPapersInput, SearchPapersOutput, search),
            Tool("get_paper", "Fetch the full abstract and metadata of one paper by arXiv id.",
                 GetPaperInput, GetPaperOutput, get),
            Tool("summarize_paper", "Extractive summary (first sentences of the abstract) of one paper by id.",
                 SummarizeInput, SummarizeOutput, summarize),
        ]
    )
