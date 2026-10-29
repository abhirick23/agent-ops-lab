"""Retriever-only metrics against gold paper ids. No LLM, so these can run on every PR.

The query is the raw question text. The agent may rewrite it before searching, so this measures the
retriever on the question as asked, not the agent's actual search behaviour.
"""
from evals.dataset import Row


def recall_at_k(ranked_ids: list[str], gold: list[str], k: int = 5) -> float:
    return len(set(ranked_ids[:k]) & set(gold)) / len(gold)


def reciprocal_rank(ranked_ids: list[str], gold: list[str]) -> float:
    for rank, pid in enumerate(ranked_ids, 1):
        if pid in gold:
            return 1.0 / rank
    return 0.0


def retrieval_metrics(store, row: Row, k: int = 5, depth: int = 10) -> dict | None:
    """recall@k over the top k; reciprocal rank over the top `depth` (so MRR is MRR@10, not truncated at k)."""
    if not row.gold_paper_ids:
        return None
    ranked = [h.paper.id for h in store.search(row.question, k=depth)]
    return {"ranked_ids": ranked, f"recall_at_{k}": recall_at_k(ranked, row.gold_paper_ids, k),
            f"rr_at_{depth}": reciprocal_rank(ranked, row.gold_paper_ids)}
