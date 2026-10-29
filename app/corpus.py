"""Corpus identity. Eval questions are written against one exact corpus file, so runs record its hash."""
import hashlib
from pathlib import Path

VERSION_FILENAME = "CORPUS_VERSION"


def corpus_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def version_path(corpus_path: str | Path) -> Path:
    return Path(corpus_path).with_name(VERSION_FILENAME)


def write_version(corpus_path: str | Path) -> str:
    digest = corpus_sha256(corpus_path)
    version_path(corpus_path).write_text(digest + "\n", encoding="utf-8", newline="\n")
    return digest


def corpus_info(corpus_path: str | Path) -> dict:
    """What an eval run should record: the actual hash, the frozen one, and whether they agree."""
    vp = version_path(corpus_path)
    frozen = vp.read_text(encoding="utf-8").strip() if vp.exists() else None
    actual = corpus_sha256(corpus_path) if Path(corpus_path).exists() else None
    return {"sha256": actual, "frozen_sha256": frozen, "matches_frozen": actual is not None and actual == frozen}
