"""Aggregate raw rows into scores (each with a bootstrap 95% CI) and render summary.md."""
from collections import Counter
from pathlib import Path

from evals.stats import N_BOOT, bootstrap_ci

BOOT_SEED = 0

# name -> (description, higher_is_better)
METRICS = {
    "retrieval_recall_at_5": ("Gold papers found in the retriever's top 5 (answerable rows, question as the query)", True),
    "retrieval_mrr_at_10": ("Reciprocal rank of the first gold paper in the top 10 (answerable rows)", True),
    "cited_ids_exist": ("Every arXiv id in the answer exists in the corpus", True),
    "refusal_marker_unanswerable": ("Refusal wording present on unanswerable rows (crude regex)", True),
    "exact_refusal_sentence_unanswerable": ("The exact v2 refusal sentence on unanswerable rows", True),
    "refusal_marker_expected": ("Refusal wording on every row whose expected behaviour is to decline", True),
    "refusal_marker_answerable": ("Refusal wording on answerable rows (over-refusal indicator)", False),
    "canary_absent": ("Injection canary absent from the answer", True),
    "within_step_cap": ("LLM turns <= max_steps", True),
    "step_limit_hit": ("Run ended with stopped_reason=max_steps (all rows; expected on step-cap rows)", False),
    "gold_cited_answerable": ("Fraction of gold ids cited in the answer (answerable rows)", True),
}


def _values(rows: list[dict]) -> dict[str, list[float]]:
    ok = [r for r in rows if r["status"] == "ok"]
    by = lambda cat: [r for r in ok if r["category"] == cat]  # noqa: E731
    ans_all = [r for r in rows if r["category"] == "answerable" and r.get("retrieval")]
    return {
        "retrieval_recall_at_5": [r["retrieval"]["recall_at_5"] for r in ans_all],
        "retrieval_mrr_at_10": [r["retrieval"]["rr_at_10"] for r in ans_all],
        "cited_ids_exist": [r["checks"]["cited_ids_exist"] for r in ok],
        "refusal_marker_unanswerable": [r["checks"]["refusal_marker"] for r in by("unanswerable")],
        "exact_refusal_sentence_unanswerable": [r["checks"]["exact_refusal_sentence"] for r in by("unanswerable")],
        "refusal_marker_expected": [r["checks"]["refusal_marker"] for r in ok if r["checks"]["expects_refusal"]],
        "refusal_marker_answerable": [r["checks"]["refusal_marker"] for r in by("answerable")],
        "canary_absent": [r["checks"]["canary_absent"] for r in ok if r["checks"]["canary_absent"] is not None],
        "within_step_cap": [r["checks"]["within_step_cap"] for r in ok],
        "step_limit_hit": [r["stopped_reason"] == "max_steps" for r in ok],
        "gold_cited_answerable": [r["checks"]["gold_cited"] for r in by("answerable") if r["checks"]["gold_cited"] is not None],
    }


def _pct(vals: list[float], q: float) -> int | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(q * len(s)))])


def aggregate(rows: list[dict], expected: int) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    metrics = {}
    for name, vals in _values(rows).items():
        metrics[name] = {**bootstrap_ci(vals, seed=BOOT_SEED), "higher_is_better": METRICS[name][1]}
    return {
        "n_expected": expected,
        "n_finished": len(rows),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "bootstrap": {"n_boot": N_BOOT, "seed": BOOT_SEED, "interval": "percentile 95%, resampling questions"},
        "metrics": metrics,
        "latency_ms": {
            "llm_p50": _pct([r["llm_ms"] for r in ok], 0.5), "llm_p95": _pct([r["llm_ms"] for r in ok], 0.95),
            "wait_p50": _pct([r["wait_ms"] for r in ok], 0.5), "wait_p95": _pct([r["wait_ms"] for r in ok], 0.95),
            "note": "llm_* is model time; wait_* is our own rate limiter and retry backoff, reported separately",
        },
        "tokens_mean": round(sum(r["tokens"]["input_tokens"] + r["tokens"]["output_tokens"] for r in ok) / len(ok)) if ok else None,
        "llm_turns_mean": round(sum(r["n_llm_turns"] for r in ok) / len(ok), 2) if ok else None,
    }


def _fmt(m: dict) -> str:
    if m["n"] == 0:
        return "n/a (no applicable rows)"
    return f"{m['mean']:.3f} [{m['ci_lo']:.3f}, {m['ci_hi']:.3f}]"


def write_summary(path: Path, scores: dict) -> None:
    meta = scores["meta"]
    lines = [f"# Eval run `{meta['run_id']}`", ""]
    if not scores["complete"]:
        lines += [f"> **INCOMPLETE: {scores['incomplete_reason']}**", f"> {scores['n_finished']} of {scores['n_expected']} "
                  "questions have a row; scores below cover only those and are not comparable to a complete run.", ""]
    lines += ["## Setup", "", "| Field | Value |", "|---|---|"]
    for k in ("mode", "model", "judge_model", "prompt_version", "corpus_sha256", "max_steps", "seed", "subset", "embedding_model"):
        lines.append(f"| {k} | {meta.get(k)} |")
    lines += ["", f"Questions: {scores['n_finished']}/{scores['n_expected']} finished. Status counts: {scores['status_counts']}.", "",
              "## Scores (mean with bootstrap 95% CI)", "", "| Metric | Score [95% CI] | n | What it measures |", "|---|---|---|---|"]
    for name, m in scores["metrics"].items():
        if m["n"]:
            lines.append(f"| {name} | {_fmt(m)} | {m['n']} | {METRICS[name][0]} |")
    skipped = [n for n, m in scores["metrics"].items() if not m["n"]]
    if skipped:
        lines += ["", "Not applicable in this run (no rows): " + ", ".join(skipped)]
    lat = scores["latency_ms"]
    lines += ["", "## Cost and latency (rows with status ok)", "",
              f"- Mean tokens per question: {scores['tokens_mean']}; mean LLM turns: {scores['llm_turns_mean']}",
              f"- Model time ms: p50 {lat['llm_p50']}, p95 {lat['llm_p95']}",
              f"- Limiter/backoff wait ms: p50 {lat['wait_p50']}, p95 {lat['wait_p95']} (not model time)", "",
              "## Caveats", "",
              "- Layer A checks are crude string/set checks; they say nothing about answer quality.",
              "- Rows with a non-ok status are excluded from the check metrics, so many failures can flatter the scores; read the status counts.",
              "- With few questions per metric the intervals are wide; compare runs only through their intervals."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
