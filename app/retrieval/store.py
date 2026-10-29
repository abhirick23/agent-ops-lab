"""ChromaDB-backed paper store. Embeddings are computed here, not by Chroma."""
import json
from pathlib import Path

import chromadb
from pydantic import BaseModel

from app.config import Settings
from app.retrieval.embedder import Embedder, SentenceTransformerEmbedder
from app.retrieval.reranker import CrossEncoderReranker, Reranker
from app.schemas import Paper

RERANK_POOL_FACTOR = 4


class Hit(BaseModel):
    paper: Paper
    score: float


def _to_metadata(p: Paper) -> dict:
    return {
        "title": p.title,
        "authors": "; ".join(p.authors),
        "published": p.published,
        "categories": ",".join(p.categories),
        "url": p.url,
    }


def _from_row(id_: str, document: str, meta: dict) -> Paper:
    return Paper(
        id=id_,
        title=meta["title"],
        abstract=document,
        authors=[a for a in meta["authors"].split("; ") if a],
        published=meta["published"],
        categories=[c for c in meta["categories"].split(",") if c],
        url=meta["url"],
    )


class PaperStore:
    def __init__(
        self,
        client: chromadb.ClientAPI,
        embedder: Embedder,
        collection_name: str = "papers",
        reranker: Reranker | None = None,
    ):
        self.embedder = embedder
        self.reranker = reranker
        self.collection = client.get_or_create_collection(
            collection_name, metadata={"hnsw:space": "cosine"}
        )

    @classmethod
    def from_settings(cls, s: Settings) -> "PaperStore":
        reranker = CrossEncoderReranker(s.reranker_model) if s.use_reranker else None
        return cls(
            chromadb.PersistentClient(path=s.chroma_dir),
            SentenceTransformerEmbedder(s.embedding_model),
            s.collection_name,
            reranker,
        )

    def count(self) -> int:
        return self.collection.count()

    def add(self, papers: list[Paper], batch_size: int = 64) -> None:
        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]
            docs = [f"{p.title}. {p.abstract}" for p in batch]
            self.collection.upsert(
                ids=[p.id for p in batch],
                documents=[p.abstract for p in batch],
                embeddings=self.embedder.embed(docs),
                metadatas=[_to_metadata(p) for p in batch],
            )

    def load_corpus(self, path: str | Path) -> int:
        with open(path, encoding="utf-8") as f:
            papers = [Paper(**json.loads(line)) for line in f if line.strip()]
        self.add(papers)
        return len(papers)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        if self.count() == 0:
            return []
        pool = k * RERANK_POOL_FACTOR if self.reranker else k
        res = self.collection.query(
            query_embeddings=self.embedder.embed([query]),
            n_results=min(pool, self.count()),
        )
        hits = [
            Hit(paper=_from_row(id_, doc, meta), score=1.0 - dist)
            for id_, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]
        if self.reranker and hits:
            scores = self.reranker.score(
                query, [f"{h.paper.title}. {h.paper.abstract}" for h in hits]
            )
            hits = [Hit(paper=h.paper, score=s) for h, s in zip(hits, scores)]
            hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def get(self, paper_id: str) -> Paper | None:
        res = self.collection.get(ids=[paper_id])
        if not res["ids"]:
            return None
        return _from_row(res["ids"][0], res["documents"][0], res["metadatas"][0])
