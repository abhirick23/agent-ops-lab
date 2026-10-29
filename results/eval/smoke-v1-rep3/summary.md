# Eval run `smoke-v1-rep3`

## Setup

| Field | Value |
|---|---|
| mode | live |
| model | gemini-3.1-flash-lite |
| judge_model | None |
| prompt_version | v1 |
| corpus_sha256 | 34f78bcd1fca18cf7005211882678a357e9886d7fd2181237b31d6e4fa1bcfd2 |
| max_steps | 5 |
| seed | 0 |
| subset | 15 |
| embedding_model | sentence-transformers/all-MiniLM-L6-v2 |

Questions: 15/15 finished. Status counts: {'ok': 15}.

## Scores (mean with bootstrap 95% CI)

| Metric | Score [95% CI] | n | What it measures |
|---|---|---|---|
| retrieval_recall_at_5 | 1.000 [1.000, 1.000] | 7 | Gold papers found in the retriever's top 5 (answerable rows, question as the query) |
| retrieval_mrr_at_10 | 0.857 [0.714, 1.000] | 7 | Reciprocal rank of the first gold paper in the top 10 (answerable rows) |
| cited_ids_exist | 1.000 [1.000, 1.000] | 15 | Every arXiv id in the answer exists in the corpus |
| refusal_marker_unanswerable | 0.750 [0.250, 1.000] | 4 | Refusal wording present on unanswerable rows (crude regex) |
| exact_refusal_sentence_unanswerable | 0.000 [0.000, 0.000] | 4 | The exact v2 refusal sentence on unanswerable rows |
| refusal_marker_expected | 0.833 [0.500, 1.000] | 6 | Refusal wording on every row whose expected behaviour is to decline |
| refusal_marker_answerable | 0.000 [0.000, 0.000] | 7 | Refusal wording on answerable rows (over-refusal indicator) |
| canary_absent | 1.000 [1.000, 1.000] | 1 | Injection canary absent from the answer |
| within_step_cap | 1.000 [1.000, 1.000] | 15 | LLM turns <= max_steps |
| step_limit_hit | 0.133 [0.000, 0.333] | 15 | Run ended with stopped_reason=max_steps (all rows; expected on step-cap rows) |
| gold_cited_answerable | 0.738 [0.452, 0.952] | 7 | Fraction of gold ids cited in the answer (answerable rows) |

## Cost and latency (rows with status ok)

- Mean tokens per question: 4152; mean LLM turns: 2.93
- Model time ms: p50 7966, p95 43694
- Limiter/backoff wait ms: p50 0, p95 32672 (not model time)

## Caveats

- Layer A checks are crude string/set checks; they say nothing about answer quality.
- Rows with a non-ok status are excluded from the check metrics, so many failures can flatter the scores; read the status counts.
- With few questions per metric the intervals are wide; compare runs only through their intervals.
