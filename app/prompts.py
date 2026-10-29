"""Versioned system prompts: prompts/<version>.txt, selected by PROMPT_VERSION."""
import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_VERSION = re.compile(r"v\d+")


def load_prompt(version: str) -> str:
    if not _VERSION.fullmatch(version):
        raise ValueError(f"invalid prompt version {version!r} (expected e.g. 'v1')")
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file for version {version!r}: {path}")
    return path.read_text(encoding="utf-8").strip()
