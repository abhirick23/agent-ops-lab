from pathlib import Path

from app.corpus import corpus_info, corpus_sha256, write_version

ROOT = Path(__file__).resolve().parent.parent


def test_committed_corpus_matches_frozen_version():
    """Fails if data/corpus.jsonl changes without re-freezing: eval questions depend on it."""
    info = corpus_info(ROOT / "data" / "corpus.jsonl")
    assert info["frozen_sha256"], "data/CORPUS_VERSION is missing"
    assert info["matches_frozen"], "corpus.jsonl changed; re-freeze with `python -m scripts.fetch_corpus`"


def test_write_version_and_detect_change(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"id": "1"}\n', encoding="utf-8")
    digest = write_version(corpus)
    assert digest == corpus_sha256(corpus) and len(digest) == 64
    assert corpus_info(corpus)["matches_frozen"]
    corpus.write_text('{"id": "2"}\n', encoding="utf-8")
    info = corpus_info(corpus)
    assert not info["matches_frozen"] and info["frozen_sha256"] == digest


def test_info_without_version_file(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("x", encoding="utf-8")
    assert corpus_info(corpus)["frozen_sha256"] is None
    assert not corpus_info(corpus)["matches_frozen"]


def test_info_with_missing_corpus(tmp_path):
    assert corpus_info(tmp_path / "nope.jsonl") == {"sha256": None, "frozen_sha256": None, "matches_frozen": False}
