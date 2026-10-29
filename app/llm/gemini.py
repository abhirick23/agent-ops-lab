from google import genai
from google.genai import types

from app.llm.base import LLMResponse, Message, ToolCall, ToolSpec


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout_s: float = 60.0):
        # Without an explicit timeout the SDK waits forever on a stalled connection.
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        self._model = model

    @staticmethod
    def _to_contents(messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m.content)]))
            elif m.role == "assistant":
                if m.raw is not None:
                    contents.append(m.raw)
                else:
                    parts = [types.Part(text=m.content)] if m.content else []
                    parts += [types.Part.from_function_call(name=c.name, args=c.arguments) for c in m.tool_calls]
                    contents.append(types.Content(role="model", parts=parts))
            else:
                part = types.Part.from_function_response(name=m.tool_name, response={"result": m.content})
                # parallel tool results must share one Content
                if contents and contents[-1].role == "user" and contents[-1].parts[0].function_response:
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
        return contents

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        declarations = [
            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self._client.models.generate_content(
            model=self._model, contents=self._to_contents(messages), config=config
        )
        usage = resp.usage_metadata
        candidate = resp.candidates[0].content if resp.candidates else None
        parts = (candidate.parts or []) if candidate else []
        return LLMResponse(
            text="".join(p.text for p in parts if p.text and not p.thought),
            tool_calls=[
                ToolCall(name=p.function_call.name, arguments=dict(p.function_call.args or {}))
                for p in parts
                if p.function_call
            ],
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0,
            raw=candidate,
        )
