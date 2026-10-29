"""Tool-calling loop with a hard cap on LLM turns."""
import json
import re

from pydantic import BaseModel

from app.llm.base import LLMClient, Message, ToolSpec
from app.schemas import Source, Step, TokenUsage
from app.tools.base import ToolRegistry

SYSTEM_PROMPT = """You answer questions about machine-learning papers using only the provided tools.
Use search_papers to find candidates, get_paper or summarize_paper for detail.
Cite papers by arXiv id in square brackets, e.g. [2401.01234].
If the tools return nothing relevant, say you could not find it instead of guessing."""

STEP_LIMIT_ANSWER = "I could not finish within the step limit."
PREVIEW_CHARS = 300
ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")


class AgentResult(BaseModel):
    answer: str
    sources: list[Source]
    steps: list[Step]
    tokens: TokenUsage
    stopped_reason: str  # "answered" | "max_steps"


def _collect_sources(output: dict, found: dict[str, Source]) -> None:
    items = output.get("results") or ([output["paper"]] if output.get("paper") else [])
    for item in items:
        found.setdefault(item["id"], Source(id=item["id"], title=item["title"], url=item.get("url", "")))


class Agent:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, max_steps: int = 5):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self._specs = [
            ToolSpec(name=t.name, description=t.description, parameters=t.parameters_schema()) for t in tools
        ]

    def run(self, question: str, max_steps: int | None = None) -> AgentResult:
        """One LLM call per step; at most `max_steps` calls."""
        limit = max_steps or self.max_steps
        messages = [Message(role="user", content=question)]
        steps: list[Step] = []
        retrieved: dict[str, Source] = {}
        usage = TokenUsage()

        for turn in range(1, limit + 1):
            resp = self.llm.generate(SYSTEM_PROMPT, messages, self._specs)
            usage.input_tokens += resp.input_tokens
            usage.output_tokens += resp.output_tokens

            if not resp.tool_calls:
                return AgentResult(
                    answer=resp.text, sources=self._cited(resp.text, retrieved), steps=steps,
                    tokens=usage, stopped_reason="answered",
                )
            if turn == limit:  # the model wants more tools but the budget is spent
                return AgentResult(
                    answer=resp.text or STEP_LIMIT_ANSWER, sources=list(retrieved.values()), steps=steps,
                    tokens=usage, stopped_reason="max_steps",
                )

            messages.append(Message(role="assistant", content=resp.text, tool_calls=resp.tool_calls, raw=resp.raw))
            for call in resp.tool_calls:
                ok, output = self.tools.execute(call.name, call.arguments)
                payload = output.model_dump() if isinstance(output, BaseModel) else output
                if ok:
                    _collect_sources(payload, retrieved)
                text = json.dumps(payload)
                steps.append(Step(turn=turn, tool=call.name, arguments=call.arguments, ok=ok,
                                  output_preview=text[:PREVIEW_CHARS]))
                messages.append(Message(role="tool", tool_name=call.name, content=text))

        raise AssertionError("unreachable: the last turn always returns")

    @staticmethod
    def _cited(answer: str, retrieved: dict[str, Source]) -> list[Source]:
        """Sources the answer actually cites; falls back to everything retrieved."""
        cited = [retrieved[i] for i in dict.fromkeys(ARXIV_ID.findall(answer)) if i in retrieved]
        return cited or list(retrieved.values())
