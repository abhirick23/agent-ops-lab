"""Embed data/corpus.jsonl into the local Chroma index. Run: python -m scripts.build_index"""
from app.config import get_settings
from app.retrieval.store import PaperStore

s = get_settings()
store = PaperStore.from_settings(s)
n = store.load_corpus(s.corpus_path)
print(f"indexed {n} papers, collection size {store.count()}")
