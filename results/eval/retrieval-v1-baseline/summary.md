# Eval run `retrieval-v1-baseline`

## Setup

| Field | Value |
|---|---|
| mode | retrieval |
| model | None |
| judge_model | None |
| prompt_version | v1 |
| corpus_sha256 | 34f78bcd1fca18cf7005211882678a357e9886d7fd2181237b31d6e4fa1bcfd2 |
| max_steps | 5 |
| seed | 0 |
| subset | None |
| embedding_model | sentence-transformers/all-MiniLM-L6-v2 |

Questions: 80/80 finished. Status counts: {'retrieval_only': 80}.

## Scores (mean with bootstrap 95% CI)

| Metric | Score [95% CI] | n | What it measures |
|---|---|---|---|
| retrieval_recall_at_5 | 0.979 [0.946, 1.000] | 40 | Gold papers found in the retriever's top 5 (answerable rows, question as the query) |
| retrieval_mrr_at_10 | 0.931 [0.869, 0.981] | 40 | Reciprocal rank of the first gold paper in the top 10 (answerable rows) |

Not applicable in this run (no rows): cited_ids_exist, refusal_marker_unanswerable, exact_refusal_sentence_unanswerable, refusal_marker_expected, refusal_marker_answerable, canary_absent, within_step_cap, step_limit_hit, gold_cited_answerable

## Cost and latency (rows with status ok)

- Mean tokens per question: None; mean LLM turns: None
- Model time ms: p50 None, p95 None
- Limiter/backoff wait ms: p50 None, p95 None (not model time)

## Caveats

- Layer A checks are crude string/set checks; they say nothing about answer quality.
- Rows with a non-ok status are excluded from the check metrics, so many failures can flatter the scores; read the status counts.
- With few questions per metric the intervals are wide; compare runs only through their intervals.
