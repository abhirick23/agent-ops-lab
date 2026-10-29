"""GeminiClient message conversion, tested without the network."""
from app.llm.base import Message, ToolCall
from app.llm.gemini import GeminiClient


def test_tool_roundtrip_conversion():
    msgs = [
        Message(role="user", content="q"),
        Message(role="assistant", tool_calls=[ToolCall(name="a", arguments={"x": 1}), ToolCall(name="b", arguments={})]),
        Message(role="tool", tool_name="a", content="ra"),
        Message(role="tool", tool_name="b", content="rb"),
    ]
    contents = GeminiClient._to_contents(msgs)
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [p.function_call.name for p in contents[1].parts] == ["a", "b"]
    # parallel tool results are merged into a single Content
    assert [p.function_response.name for p in contents[2].parts] == ["a", "b"]


def test_raw_content_is_replayed_verbatim():
    sentinel = GeminiClient._to_contents([Message(role="user", content="x")])[0]
    contents = GeminiClient._to_contents([Message(role="assistant", raw=sentinel)])
    assert contents[0] is sentinel
