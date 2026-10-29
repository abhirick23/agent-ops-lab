import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException

from app.agent import Agent
from app.config import get_settings
from app.llm.gemini import GeminiClient
from app.llm.resilience import build_llm
from app.retrieval.store import PaperStore
from app.schemas import AskRequest, AskResponse
from app.tools.papers import build_tools

log = logging.getLogger("agent_ops")
app = FastAPI(title="agent-ops-lab")


@lru_cache
def get_agent() -> Agent:
    s = get_settings()
    if not s.gemini_api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not set")
    store = PaperStore.from_settings(s)
    if store.count() == 0:
        log.info("empty index, loading %s", s.corpus_path)
        store.load_corpus(s.corpus_path)
    llm = build_llm(s, GeminiClient(s.gemini_api_key, s.gemini_model, s.llm_timeout_s))
    return Agent(llm, build_tools(store), s.max_steps)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, agent: Agent = Depends(get_agent)) -> AskResponse:
    try:
        result = agent.run(req.question, req.max_steps)
    except Exception as e:  # LLM/provider failures are upstream errors, not ours
        log.exception("agent run failed")
        raise HTTPException(status_code=502, detail=f"upstream model error: {type(e).__name__}") from e
    return AskResponse(
        answer=result.answer,
        sources=result.sources,
        steps=result.steps,
        tokens=result.tokens,
        stopped_reason=result.stopped_reason,
        latency_ms=result.latency_ms,
        llm_ms_per_turn=result.llm_ms_per_turn,
    )
