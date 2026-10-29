import hashlib
import math
import re
import uuid

import chromadb
import pytest

from app.llm.base import LLMResponse, Message, ToolCall, ToolSpec
from app.retrieval.store import PaperStore
from app.schemas import Paper
from app.tools.papers import build_tools


class HashEmbedder:
    """Deterministic bag-of-words embedder: no model download, similar words => similar vectors."""

    DIM = 128

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.DIM
            for w in re.findall(r"[a-z]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class ScriptedLLM:
    """Replays a fixed list of responses and records what it was sent."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.calls: list[list[Message]] = []
        self.tool_specs: list[ToolSpec] = []

    def generate(self, system, messages, tools):
        self.calls.append(list(messages))
        self.tool_specs = tools
        return self.responses.pop(0)


def tool_call_response(name: str, arguments: dict, tokens=(10, 5)) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name=name, arguments=arguments)],
                       input_tokens=tokens[0], output_tokens=tokens[1])


def text_response(text: str, tokens=(20, 8)) -> LLMResponse:
    return LLMResponse(text=text, input_tokens=tokens[0], output_tokens=tokens[1])


PAPERS = [
    Paper(id="2401.00001", title="Efficient Transformers for Long Context",
          abstract="We study attention mechanisms for long context language models. Sparse attention cuts cost. We evaluate on benchmarks.",
          authors=["A. One", "B. Two"], published="2024-01-02", categories=["cs.CL"],
          url="http://arxiv.org/abs/2401.00001"),
    Paper(id="2401.00002", title="Gradient Boosting Revisited",
          abstract="Gradient boosting with decision trees remains strong on tabular data. We revisit regularization.",
          authors=["C. Three"], published="2024-01-03", categories=["cs.LG"],
          url="http://arxiv.org/abs/2401.00002"),
    Paper(id="2401.00003", title="Retrieval Augmented Generation Survey",
          abstract="Retrieval augmented generation grounds language models in documents. We compare retrievers and rerankers.",
          authors=["D. Four"], published="2024-01-04", categories=["cs.CL", "cs.LG"],
          url="http://arxiv.org/abs/2401.00003"),
]


@pytest.fixture
def store():
    s = PaperStore(chromadb.EphemeralClient(), HashEmbedder(), f"t_{uuid.uuid4().hex}")
    s.add(PAPERS)
    return s


@pytest.fixture
def tools(store):
    return build_tools(store)
