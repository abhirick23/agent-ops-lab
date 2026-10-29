"""Provider-neutral LLM interface so the agent can be tested with a mock."""
from typing import Any, Literal, Protocol

from pydantic import BaseModel


class ToolCall(BaseModel):
    name: str
    arguments: dict


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = []
    tool_name: str | None = None  # set when role == "tool"
    raw: Any = None  # provider-native content, replayed verbatim (e.g. Gemini thought signatures)


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = []
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = None


class LLMClient(Protocol):
    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...
