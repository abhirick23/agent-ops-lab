# agent-ops-lab

> **Personal project.** A learning lab for LLM-ops practices (evals, CI gates, tracing, monitoring, cost, drift, incident drills). It is **not** production experience, and nothing here has served real users.

A small tool-calling agent over a corpus of ~200 arXiv abstracts (cs.CL, cs.LG), built with FastAPI, ChromaDB, local sentence-transformers embeddings and the Gemini free tier. This is **Module 1: the service**. Later modules add evaluation, CI, tracing, monitoring and so on.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Python 3.10+
pip install -e ".[dev]"
cp .env.example .env                                   # add a free GEMINI_API_KEY

python -m scripts.fetch_corpus                         # -> data/corpus.jsonl
python -m scripts.build_index                          # -> data/chroma (optional; /ask indexes on first use)
uvicorn app.main:app --reload

curl -X POST localhost:8000/ask -H 'content-type: application/json' \
     -d '{"question": "Which papers study reasoning in LLMs?"}'
pytest --cov=app                                       # no network, no API key needed
```

## Layout

| Path | What |
|---|---|
| `app/main.py` | `POST /ask`, `GET /health` |
| `app/agent.py` | Tool-calling loop; hard cap on LLM turns (`max_steps`, default 5, per-request override 1–10) |
| `app/llm/` | `LLMClient` protocol + `GeminiClient`. Tests use a scripted mock |
| `app/tools/` | `search_papers`, `get_paper`, `summarize_paper` (extractive), each with Pydantic input/output |
| `app/retrieval/` | ChromaDB store, local embedder, optional cross-encoder reranker (`USE_RERANKER=true`) |
| `scripts/fetch_corpus.py` | Reproducible corpus: fixed query + date window, seeded sample (`--seed 42`) |
| `tests/` | pytest, LLM and embedder mocked |

## `/ask` response

```json
{
  "answer": "… [2401.06805]",
  "sources": [{"id": "2401.06805", "title": "…", "url": "http://arxiv.org/abs/2401.06805"}],
  "steps": [{"turn": 1, "tool": "search_papers", "arguments": {"query": "…"}, "ok": true, "output_preview": "…"}],
  "tokens": {"input_tokens": 812, "output_tokens": 96, "total_tokens": 908},
  "stopped_reason": "answered"
}
```

`stopped_reason` is `max_steps` when the model still wanted tools on its last allowed turn. Sources are the papers the answer cites by id, falling back to everything retrieved. Provider errors return 502, a missing key returns 503.

## Claims, how measured, where the data is

| Claim | How measured | Data |
|---|---|---|
| Test suite passes, 91% line coverage of `app/` | `pytest --cov=app` (44 tests) | run locally; CI arrives in module 3 |
| Retrieval returns on-topic papers on the real embedder | manual spot check only, **not** a measured quality number | module 2 will measure it |

Later modules add rows here (with raw outputs under `results/`).

## Corpus windows

`scripts/fetch_corpus.py` pools up to 50 papers per category (cs.CL, cs.LG) from each submission-date window below, then draws 200 with `random.Random(seed=42)` over the sorted pool ids. Result for the committed file: 37/36/36/28/33/30 papers from Jan/Mar/May/Jul/Sep/Nov 2024.

| Window | Dates (2024) |
|---|---|
| 1 | 01 Jan – 29 Feb |
| 2 | 01 Mar – 30 Apr |
| 3 | 01 May – 30 Jun |
| 4 | 01 Jul – 31 Aug |
| 5 | 01 Sep – 31 Oct |
| 6 | 01 Nov – 31 Dec |

Changing `WINDOWS`, `--pool` or `--seed` changes the corpus. arXiv's own ordering can shift slightly over time, so a re-fetch may differ from the committed file.

## Known limits

- `GeminiClient` is covered only by message-conversion unit tests. It has not been exercised against the live API in the test suite.
- The corpus is a small slice, not a representative sample of arXiv. Papers are the earliest 50 per category in each date window (arXiv returns date-ascending), so they cluster at the start of each window (see below).
- `summarize_paper` is extractive (first sentences), so it costs no tokens.

## License

MIT
