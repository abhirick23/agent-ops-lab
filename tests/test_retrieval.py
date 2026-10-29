import json
import uuid

import chromadb

from app.retrieval.store import PaperStore
from tests.conftest import PAPERS, HashEmbedder


def test_search_ranks_relevant_paper_first(store):
    hits = store.search("sparse attention for long context language models", k=3)
    assert hits[0].paper.id == "2401.00001"
    assert hits[0].score >= hits[-1].score


def test_search_respects_k(store):
    assert len(store.search("language models", k=2)) == 2


def test_search_k_larger_than_corpus(store):
    assert len(store.search("anything", k=50)) == len(PAPERS)


def test_search_empty_index_returns_nothing():
    empty = PaperStore(chromadb.EphemeralClient(), HashEmbedder(), f"t_{uuid.uuid4().hex}")
    assert empty.search("x") == []


def test_get_roundtrips_metadata(store):
    p = store.get("2401.00003")
    assert p == PAPERS[2]


def test_get_missing_returns_none(store):
    assert store.get("9999.99999") is None


def test_add_is_idempotent(store):
    store.add(PAPERS)
    assert store.count() == len(PAPERS)


def test_load_corpus_from_jsonl(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n".join(json.dumps(p.model_dump()) for p in PAPERS) + "\n", encoding="utf-8")
    s = PaperStore(chromadb.EphemeralClient(), HashEmbedder(), f"t_{uuid.uuid4().hex}")
    assert s.load_corpus(path) == len(PAPERS)
    assert s.count() == len(PAPERS)


class ReverseReranker:
    """Scores docs so that the one the embedder ranked last comes first."""

    def __init__(self):
        self.seen = 0

    def score(self, query, docs):
        self.seen = len(docs)
        return [float(i) for i in range(len(docs))]


def test_reranker_reorders_and_widens_pool():
    rr = ReverseReranker()
    client, name = chromadb.EphemeralClient(), f"t_{uuid.uuid4().hex}"
    s = PaperStore(client, HashEmbedder(), name, reranker=rr)
    s.add(PAPERS)
    plain = PaperStore(client, HashEmbedder(), name).search("long context attention", k=1)
    reranked = s.search("long context attention", k=1)
    assert rr.seen == len(PAPERS)  # candidate pool was wider than k
    assert reranked[0].paper.id != plain[0].paper.id
