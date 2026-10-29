"""Live contract tests for GeminiClient. Skipped by default; run manually with:

    pytest -m live

Needs GEMINI_API_KEY. Costs about 5 requests of free-tier quota (the limiter paces them), and
skips, rather than fails, if Google is overloaded after retries (503/504/timeouts).
"""
import pytest

from app.agent import Agent
from app.config import Settings
from app.llm.base import Message, ToolSpec
from app.llm.gemini import GeminiClient
from app.llm.resilience import build_llm, is_daily_quota, is_retryable
from app.tools.papers import build_tools

pytestmark = pytest.mark.live

WEATHER = ToolSpec(
    name="get_temperature",
    description="Current temperature in a city, in Celsius.",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)


@pytest.fixture(scope="module")
def settings():
    s = Settings(llm_cache_enabled=False)  # a cache hit would hide a broken client
    if not s.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set")
    return s


@pytest.fixture(scope="module")
def llm(settings):
    return build_llm(settings, GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_s))


def call(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        if is_retryable(e) or is_daily_quota(e):
            pytest.skip(f"Gemini unavailable (overloaded or daily quota spent): {str(e)[:200]}")
        raise


def test_plain_text_and_token_counts(llm):
    r = call(llm.generate, "Be terse.", [Message(role="user", content="Reply with one short greeting.")], [])
    assert r.text.strip()  # exact wording is the model's business; we test the client contract
    assert r.tool_calls == []
    assert r.input_tokens > 0 and r.output_tokens > 0


def test_tool_call_roundtrip_replays_provider_content(llm):
    """Function call -> tool result -> final text. Breaks if thought signatures are not replayed."""
    user = Message(role="user", content="What is the temperature in Paris? Use the tool.")
    first = call(llm.generate, "Use tools when needed.", [user], [WEATHER])
    assert [c.name for c in first.tool_calls] == ["get_temperature"]
    assert "paris" in first.tool_calls[0].arguments["city"].lower()

    history = [
        user,
        Message(role="assistant", content=first.text, tool_calls=first.tool_calls, raw=first.raw),
        Message(role="tool", tool_name="get_temperature", content='{"celsius": 17}'),
    ]
    second = call(llm.generate, "Use tools when needed.", history, [WEATHER])
    assert second.tool_calls == []
    assert "17" in second.text


def test_agent_end_to_end_on_tiny_corpus(settings, llm, store):
    r = call(Agent(llm, build_tools(store), max_steps=4).run, "Which paper revisits gradient boosting? Cite its id.")
    assert r.stopped_reason == "answered"
    assert r.steps and r.steps[0].tool in {"search_papers", "get_paper", "summarize_paper"}
    assert "2401.00002" in {s.id for s in r.sources}
    assert r.tokens.input_tokens > 0
