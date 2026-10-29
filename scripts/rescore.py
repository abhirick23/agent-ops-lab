"""Recompute Layer A checks, scores.json and summary.md for an existing run from its saved answers.

Use after changing evals/checks.py. raw.jsonl keeps the model's answers untouched; only the derived `checks`
field is rewritten.

    python -m scripts.rescore results/eval/<run_id>
"""
import json
import sys
from pathlib import Path

from evals.checks import check_row
from evals.dataset import load_corpus_index, load_dataset
from evals.runner import DONE, read_rows
from evals.scoring import aggregate, write_summary


def rescore(run_dir: Path) -> None:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    dataset = {r.id: r for r in load_dataset()}
    corpus_ids = set(load_corpus_index())
    latest = read_rows(run_dir / "raw.jsonl")
    for r in latest.values():
        if r["status"] == "ok":
            r["checks"] = check_row(dataset[r["id"]], r["answer"], r["n_llm_turns"], meta["max_steps"], corpus_ids)
    with (run_dir / "raw.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in latest.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    scores = aggregate(list(latest.values()), expected=meta.get("subset") or len(dataset))
    scores["meta"] = meta
    scores["complete"] = all(r["status"] in DONE for r in latest.values()) and len(latest) == scores["n_expected"]
    scores["incomplete_reason"] = None if scores["complete"] else "see status counts"
    (run_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8", newline="\n")
    write_summary(run_dir / "summary.md", scores)


if __name__ == "__main__":
    rescore(Path(sys.argv[1]))
    print("rescored", sys.argv[1])
