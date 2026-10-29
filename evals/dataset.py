"""Eval dataset: loading and validation against the frozen corpus."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DATASET_PATH = Path("evals/dataset.jsonl")
CORPUS_PATH = Path("data/corpus.jsonl")

Category = Literal["answerable", "unanswerable", "adversarial"]
# Behaviours where the right response is to decline rather than to answer.
REFUSAL_BEHAVIORS = {"refuse", "refuse_fabrication", "decline_off_topic", "decline_injection"}


class Row(BaseModel):
    id: str
    category: Category
    subtype: str
    question: str
    gold_paper_ids: list[str]
    expected_behavior: str
    notes: str
    support: dict[str, str] = {}  # gold id -> verbatim snippet from its title/abstract that justifies it
    canary: str | None = None

    @property
    def expects_refusal(self) -> bool:
        return self.expected_behavior in REFUSAL_BEHAVIORS


def load_dataset(path: Path = DATASET_PATH) -> list[Row]:
    with Path(path).open(encoding="utf-8") as f:
        return [Row.model_validate_json(line) for line in f if line.strip()]


def load_corpus_index(path: Path = CORPUS_PATH) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8") as f:
        return {p["id"]: p for p in map(json.loads, filter(str.strip, f))}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def validate(rows: list[Row], corpus: dict[str, dict]) -> list[str]:
    """Returns a list of problems (empty = valid). Checks shape, ids, and that every gold id is justified
    by a snippet that really occurs in that paper's title or abstract."""
    errors: list[str] = []
    ids = [r.id for r in rows]
    if len(set(ids)) != len(ids):
        errors.append("duplicate row ids")
    counts = {c: sum(r.category == c for r in rows) for c in ("answerable", "unanswerable", "adversarial")}
    if counts != {"answerable": 40, "unanswerable": 20, "adversarial": 20}:
        errors.append(f"category counts {counts}")
    for r in rows:
        for pid in r.gold_paper_ids:
            if pid not in corpus:
                errors.append(f"{r.id}: gold id {pid} not in corpus")
        if r.category == "answerable":
            if not r.gold_paper_ids:
                errors.append(f"{r.id}: answerable row without gold ids")
            if set(r.support) != set(r.gold_paper_ids):
                errors.append(f"{r.id}: support must cover exactly the gold ids")
        if r.category == "unanswerable" and r.gold_paper_ids:
            errors.append(f"{r.id}: unanswerable row must not have gold ids")
        for pid, snippet in r.support.items():
            p = corpus.get(pid)
            if p and _norm(snippet) not in _norm(p["title"] + " " + p["abstract"]):
                errors.append(f"{r.id}: support snippet for {pid} not found in title/abstract: {snippet!r}")
        if r.subtype == "injection" and not r.canary:
            errors.append(f"{r.id}: injection row without a canary")
        if r.canary and r.canary not in r.question:
            errors.append(f"{r.id}: canary not present in the question")
    return errors
