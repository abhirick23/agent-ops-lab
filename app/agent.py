"""Tool-calling loop with a hard cap on LLM turns."""
import json
import re
import time

from pydantic import BaseModel

from app.llm.base import LLMClient, Message, ToolSpec
from app.llm.timing import pop_wait_ms
from app.prompts import load_prompt
from app.schemas import Source, Step, TokenUsage
from app.tools.base import ToolRegistry

STEP_LIMIT_ANSWER = (
    "I stopped before finishing: the step limit ({limit}) was reached while I was still gathering "
    "information, so I have no complete answer. Try a more specific question or raise max_steps."
)
PREVIEW_CHARS = 300
ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")


class AgentResult(BaseModel):
    answer: str
    sources: list[Source]
    steps: list[Step]
    tokens: TokenUsage
    stopped_reason: str  # "answered" | "max_steps"
    prompt_version: str = ""
    latency_ms: int = 0
    llm_ms_per_turn: list[int] = []
    wait_ms_per_turn: list[int] = []


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _collect_sources(output: dict, found: dict[str, Source]) -> None:
    items = output.get("results") or ([output["paper"]] if output.get("paper") else [])
    for item in items:
        found.setdefault(item["id"], Source(id=item["id"], title=item["title"], url=item.get("url", "")))


class Agent:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, max_steps: int = 5, prompt_version: str = "v1"):
        self.llm = llm
        self.prompt_version = prompt_version
        self.system_prompt = load_prompt(prompt_version)
        self.tools = tools
        self.max_steps = max_steps
        self._specs = [
            ToolSpec(name=t.name, description=t.description, parameters=t.parameters_schema()) for t in tools
        ]

    def run(self, question: str, max_steps: int | None = None) -> AgentResult:
        """One LLM call per step; at most `max_steps` calls."""
        limit = max_steps or self.max_steps
        t0 = time.perf_counter()
        messages = [Message(role="user", content=question)]
        steps: list[Step] = []
        retrieved: dict[str, Source] = {}
        usage = TokenUsage()
        llm_ms: list[int] = []
        wait_ms: list[int] = []

        def result(answer: str, sources: list[Source], reason: str) -> AgentResult:
            return AgentResult(answer=answer, sources=sources, steps=steps, tokens=usage, stopped_reason=reason,
                               prompt_version=self.prompt_version, latency_ms=_ms(t0), llm_ms_per_turn=llm_ms, wait_ms_per_turn=wait_ms)

        for turn in range(1, limit + 1):
            pop_wait_ms()  # drop any stale tally from earlier work on this thread
            t_llm = time.perf_counter()
            try:
                resp = self.llm.generate(self.system_prompt, messages, self._specs)
            finally:
                wall, waited = _ms(t_llm), pop_wait_ms()
            wait_ms.append(waited)
            llm_ms.append(max(0, wall - waited))
            usage.input_tokens += resp.input_tokens
            usage.output_tokens += resp.output_tokens

            if not resp.tool_calls:
                return result(resp.text, self._cited(resp.text, retrieved), "answered")
            if turn == limit:  # the model wants more tools but the budget is spent
                # resp.text here is usually "let me search..." filler, so never use it as the answer
                return result(STEP_LIMIT_ANSWER.format(limit=limit), list(retrieved.values()), "max_steps")

            messages.append(Message(role="assistant", content=resp.text, tool_calls=resp.tool_calls, raw=resp.raw))
            for call in resp.tool_calls:
                t_tool = time.perf_counter()
                ok, output = self.tools.execute(call.name, call.arguments)
                tool_ms = _ms(t_tool)
                payload = output.model_dump() if isinstance(output, BaseModel) else output
                if ok:
                    _collect_sources(payload, retrieved)
                text = json.dumps(payload)
                steps.append(Step(turn=turn, tool=call.name, arguments=call.arguments, ok=ok,
                                  output_preview=text[:PREVIEW_CHARS], llm_ms=llm_ms[-1], wait_ms=wait_ms[-1], tool_ms=tool_ms))
                messages.append(Message(role="tool", tool_name=call.name, content=text))

        raise AssertionError("unreachable: the last turn always returns")

    @staticmethod
    def _cited(answer: str, retrieved: dict[str, Source]) -> list[Source]:
        """Sources the answer actually cites; falls back to everything retrieved."""
        cited = [retrieved[i] for i in dict.fromkeys(ARXIV_ID.findall(answer)) if i in retrieved]
        return cited or list(retrieved.values())
