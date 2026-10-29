import pytest
from fastapi.testclient import TestClient

from app.agent import Agent
from app.config import Settings
from app.main import app, get_agent
from tests.conftest import ScriptedLLM, text_response, tool_call_response


@pytest.fixture
def make_client(tools):
    def _make(responses):
        llm = ScriptedLLM(responses)
        app.dependency_overrides[get_agent] = lambda: Agent(llm, tools, max_steps=3)
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def test_health(make_client):
    r = make_client([]).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ask_happy_path(make_client):
    c = make_client([
        tool_call_response("search_papers", {"query": "boosting"}),
        text_response("See [2401.00002]."),
    ])
    r = c.post("/ask", json={"question": "tell me about boosting"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "See [2401.00002]."
    assert body["sources"] == [{"id": "2401.00002", "title": "Gradient Boosting Revisited",
                                "url": "http://arxiv.org/abs/2401.00002"}]
    assert body["steps"][0]["tool"] == "search_papers"
    assert body["tokens"] == {"input_tokens": 30, "output_tokens": 13, "total_tokens": 43}
    assert body["stopped_reason"] == "answered"


def test_ask_reports_max_steps(make_client):
    c = make_client([tool_call_response("search_papers", {"query": "x"}) for _ in range(5)])
    body = c.post("/ask", json={"question": "q", "max_steps": 2}).json()
    assert body["stopped_reason"] == "max_steps"


@pytest.mark.parametrize("payload", [
    {},
    {"question": ""},
    {"question": "x" * 2001},
    {"question": 123},
    {"question": "ok", "max_steps": 0},
    {"question": "ok", "max_steps": 11},
])
def test_ask_validation_errors(make_client, payload):
    assert make_client([]).post("/ask", json=payload).status_code == 422


def test_ask_upstream_failure_is_502(make_client, tools):
    class Boom:
        def generate(self, *a, **k):
            raise RuntimeError("429 rate limited")

    app.dependency_overrides[get_agent] = lambda: Agent(Boom(), tools)
    r = TestClient(app).post("/ask", json={"question": "q"})
    assert r.status_code == 502
    assert "RuntimeError" in r.json()["detail"]
    assert "429" not in r.json()["detail"]  # provider message is logged, not leaked


def test_ask_without_api_key_is_503(monkeypatch):
    from app import main

    main.get_agent.cache_clear()
    monkeypatch.setattr(main, "get_settings", lambda: Settings(gemini_api_key="", _env_file=None))
    r = TestClient(app).post("/ask", json={"question": "q"})
    assert r.status_code == 503
    main.get_agent.cache_clear()
