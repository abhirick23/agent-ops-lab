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

With `make`: `make setup corpus index test run` (`make test` also writes `results/coverage.txt`).
Without `make` (Windows): `.\scripts\tasks.ps1 setup|corpus|index|test|live|run`, same steps.

**Live tests** call the real Gemini API and are skipped by default: `pytest -m live` (or `make live`). They need `GEMINI_API_KEY`, use a few requests of free-tier quota, and skip rather than fail if Google is overloaded.

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
  "steps": [{"turn": 1, "tool": "search_papers", "arguments": {"query": "…"}, "ok": true, "output_preview": "…", "llm_ms": 1210, "wait_ms": 0, "tool_ms": 35}],
  "tokens": {"input_tokens": 812, "output_tokens": 96, "total_tokens": 908},
  "stopped_reason": "answered",
  "latency_ms": 2140,
  "llm_ms_per_turn": [1210, 840],
  "wait_ms_per_turn": [0, 0],
  "wait_ms": 0
}
```

`stopped_reason` is `max_steps` when the model still wanted tools on its last allowed turn; the `answer` is then a fixed message saying the step limit was hit (never the model's partial text). `latency_ms` is the wall-clock total. `llm_ms_per_turn` is model time per LLM call; time spent in our own rate limiter and retry backoff is reported separately as `wait_ms_per_turn` / `wait_ms`, so latency percentiles don't just measure the limiter. Each step carries its turn's `llm_ms` and `wait_ms` plus its own `tool_ms`. Sources are the papers the answer cites by id, falling back to everything retrieved. Provider errors return 502, a missing key returns 503.

## Claims, how measured, where the data is

| Claim | How measured | Data |
|---|---|---|
| Test suite passes, coverage of `app/` as in the file | `pytest --cov=app` (86 tests, LLM mocked) | `results/coverage.txt` |
| `GeminiClient` works against the live API (plain text, tool-call round trip, agent loop) | `pytest -m live`, run manually: 3 passed on `gemini-3.1-flash-lite` on 2026-10-29 | `tests/test_live_gemini.py`; one earlier raw `/ask` on `gemini-3.6-flash` in `results/real_ask_gemini-3.6-flash.txt` |
| Free-tier request limits per model | back-to-back tiny requests until a 429 names the quota (`scripts/probe_limits.py`); Google does not publish them | `results/free_tier_limits.json` |
| The corpus is frozen and reproducible | SHA-256 in `data/CORPUS_VERSION`, checked by a test; a fresh `fetch_corpus` run reproduced the same hash | `data/CORPUS_VERSION` |
| Retrieval returns on-topic papers on the real embedder | manual spot check only, **not** a measured quality number | module 2 will measure it |

Later modules add rows here (with raw outputs under `results/`).

### Measured free-tier limits (author's key, 2026-10-29)

| Model | Requests/min | Requests/day | Note |
|---|---|---|---|
| `gemini-3.1-flash-lite` (default) | 15 | not measured | passes the live tests, including a tool-call round trip |
| `gemini-3.6-flash` | 5 | **20** | daily quota exhausted during development; only usable for a handful of calls a day |
| `gemini-3.5-flash` | 5 | not measured | |
| `gemini-3-flash-preview` | 5 | not measured | |
| `gemini-3.8-flash` | not measured | not measured | returned 504 (overloaded) |

Per-minute limits come from `scripts/probe_limits.py` (`results/free_tier_limits.json`). The per-day figure for `gemini-3.6-flash` came from the 429 body once the quota ran out (`results/free_tier_daily_quota.json`); I did not deliberately burn the other models' daily quotas, so theirs are unknown. `LLM_RPM` defaults to the per-minute column for the configured model (5 for unknown models); set `LLM_RPM` to override. Limits and availability change, so re-run the probe.

**Consequence for evals:** with a daily cap in the tens of requests on some models, live end-to-end runs are a scarce resource. That is the reason replay-from-cache and retrieval-only evals are the CI path (see Eval design).

Retry policy: 429/5xx and network timeouts are retried with exponential backoff, honouring the server's `retryDelay` up to 120 s. A per-day quota 429, or a requested wait over 120 s, fails immediately instead of blocking a request for hours (an earlier version of this code would have slept for about 23 hours; a live test run caught it).

## Corpus freeze

`data/CORPUS_VERSION` holds the SHA-256 of `data/corpus.jsonl`. Eval questions are written against this exact file, so `app.corpus.corpus_info()` returns the actual hash, the frozen hash and whether they match, for eval runs to record; `GET /health` reports it too. `.gitattributes` stops git from rewriting the file's line endings, and `fetch_corpus` writes LF on every OS. A test fails if the corpus changes without re-freezing.

## Eval design (modules 2–3)

A single question takes about 4 LLM calls and 40 s at 5 requests/min, so an 80-question end-to-end run is roughly 70 minutes before any judge calls. Evals are therefore split:

| Eval | Needs Gemini? | Runs |
|---|---|---|
| Retrieval-only (recall@k, MRR against gold paper ids) | no | every PR |
| End-to-end, **replay** (reads only from the response cache) | no | every PR (deterministic) |
| End-to-end, **live** smoke subset (~15 questions) | yes | on demand |
| End-to-end, **live** full set | yes | only when chosen |

The cache and the corpus hash make replay runs reproducible. Latency reporting keeps limiter wait apart from model time (`wait_ms` vs `llm_ms`).

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

- The `GeminiClient` live tests are manual (`pytest -m live`), so CI will not catch a provider-side change. Gemini model availability changed during development (`gemini-2.5-flash` returned 404; `gemini-3.8-flash` was overloaded).
- A worst-case single LLM call can take minutes: up to 5 attempts at `LLM_TIMEOUT_S` each, plus backoff.
- The corpus is a small slice, not a representative sample of arXiv. Papers are the earliest 50 per category in each date window (arXiv returns date-ascending), so they cluster at the start of each window (see Corpus windows).
- `summarize_paper` is extractive (first sentences), so it costs no tokens.

## License

MIT
