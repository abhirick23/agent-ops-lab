import time

from app.agent import STEP_LIMIT_ANSWER, Agent
from tests.conftest import ScriptedLLM, text_response, tool_call_response


def test_answers_directly_without_tools(tools):
    llm = ScriptedLLM([text_response("Hello.")])
    r = Agent(llm, tools).run("hi")
    assert r.answer == "Hello."
    assert r.steps == [] and r.sources == []
    assert r.stopped_reason == "answered"
    assert (r.tokens.input_tokens, r.tokens.output_tokens) == (20, 8)


def test_search_then_answer_with_citation(tools):
    llm = ScriptedLLM([
        tool_call_response("search_papers", {"query": "gradient boosting"}),
        text_response("Boosting is revisited in [2401.00002]."),
    ])
    r = Agent(llm, tools).run("what about boosting?")
    assert [s.tool for s in r.steps] == ["search_papers"]
    assert r.steps[0].ok and r.steps[0].turn == 1
    assert [s.id for s in r.sources] == ["2401.00002"]  # only the cited paper, not all 3 retrieved
    assert r.tokens.input_tokens == 30 and r.tokens.output_tokens == 13
    assert r.stopped_reason == "answered"


def test_uncited_answer_falls_back_to_all_retrieved(tools):
    llm = ScriptedLLM([
        tool_call_response("search_papers", {"query": "language models", "k": 3}),
        text_response("Several papers cover this."),
    ])
    r = Agent(llm, tools).run("q")
    assert len(r.sources) == 3


def test_tool_result_is_fed_back_to_model(tools):
    llm = ScriptedLLM([
        tool_call_response("get_paper", {"paper_id": "2401.00001"}),
        text_response("done"),
    ])
    Agent(llm, tools).run("q")
    last = llm.calls[1][-1]
    assert last.role == "tool" and last.tool_name == "get_paper"
    assert "Efficient Transformers" in last.content
    assert [t.name for t in llm.tool_specs] == ["search_papers", "get_paper", "summarize_paper"]


def test_invalid_tool_args_are_reported_to_model_not_raised(tools):
    llm = ScriptedLLM([
        tool_call_response("search_papers", {"k": 3}),
        text_response("sorry"),
    ])
    r = Agent(llm, tools).run("q")
    assert not r.steps[0].ok
    assert "invalid arguments" in llm.calls[1][-1].content
    assert r.stopped_reason == "answered"


def test_unknown_tool_does_not_crash(tools):
    llm = ScriptedLLM([tool_call_response("rm_rf", {}), text_response("ok")])
    r = Agent(llm, tools).run("q")
    assert not r.steps[0].ok


def test_max_steps_stops_a_looping_model(tools):
    llm = ScriptedLLM([tool_call_response("search_papers", {"query": "x"}) for _ in range(10)])
    r = Agent(llm, tools, max_steps=3).run("q")
    assert r.stopped_reason == "max_steps"
    assert len(llm.calls) == 3  # exactly 3 LLM calls, never more
    assert len(r.steps) == 2  # the final turn's tool calls are not executed
    assert r.answer == STEP_LIMIT_ANSWER.format(limit=3)
    assert r.tokens.input_tokens == 30  # usage still counted for the capped run


def test_per_call_max_steps_overrides_default(tools):
    llm = ScriptedLLM([tool_call_response("search_papers", {"query": "x"}) for _ in range(10)])
    r = Agent(llm, tools, max_steps=5).run("q", max_steps=1)
    assert len(llm.calls) == 1 and r.stopped_reason == "max_steps" and r.steps == []


def test_answer_on_final_allowed_turn_is_not_capped(tools):
    llm = ScriptedLLM([
        tool_call_response("search_papers", {"query": "x"}),
        text_response("final"),
    ])
    r = Agent(llm, tools, max_steps=2).run("q")
    assert r.stopped_reason == "answered" and r.answer == "final"


def test_max_steps_answer_is_clear_fallback_not_model_filler(tools):
    filler = tool_call_response("search_papers", {"query": "x"})
    filler.text = "Let me search for that..."
    r = Agent(ScriptedLLM([filler, filler]), tools, max_steps=2).run("q")
    assert r.stopped_reason == "max_steps"
    assert "Let me search" not in r.answer
    assert "step limit (2)" in r.answer and "no complete answer" in r.answer


def test_latency_is_recorded_per_turn_and_per_step(tools):
    llm = ScriptedLLM([
        tool_call_response("search_papers", {"query": "x"}),
        text_response("done"),
    ])
    slow = llm.generate

    def delayed(*a, **k):
        time.sleep(0.03)
        return slow(*a, **k)

    llm.generate = delayed
    r = Agent(llm, tools).run("q")
    assert len(r.llm_ms_per_turn) == 2 and all(ms >= 25 for ms in r.llm_ms_per_turn)
    assert r.steps[0].llm_ms == r.llm_ms_per_turn[0]
    assert r.steps[0].tool_ms >= 0
    assert r.latency_ms >= sum(r.llm_ms_per_turn)


def test_latency_recorded_on_max_steps_too(tools):
    llm = ScriptedLLM([tool_call_response("search_papers", {"query": "x"}) for _ in range(3)])
    r = Agent(llm, tools, max_steps=2).run("q")
    assert len(r.llm_ms_per_turn) == 2 and r.latency_ms >= 0


def test_limiter_wait_is_reported_separately_from_model_time(tools):
    from app.llm.timing import record_wait

    llm = ScriptedLLM([tool_call_response("search_papers", {"query": "x"}), text_response("done")])
    inner = llm.generate

    def throttled(*a, **k):
        record_wait(0.2)  # as if the rate limiter had slept 200 ms
        time.sleep(0.2)
        return inner(*a, **k)

    llm.generate = throttled
    r = Agent(llm, tools).run("q")
    assert r.wait_ms_per_turn == [200, 200]
    assert all(ms < 100 for ms in r.llm_ms_per_turn)  # the sleep is not counted as model time
    assert r.steps[0].wait_ms == 200
    assert r.latency_ms >= 400


def test_no_wait_reported_without_limiter(tools):
    r = Agent(ScriptedLLM([text_response("hi")]), tools).run("q")
    assert r.wait_ms_per_turn == [0]
