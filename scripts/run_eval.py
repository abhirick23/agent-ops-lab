"""Run the eval set against one prompt version.

    python -m scripts.run_eval --prompt v1 --mode retrieval            # no LLM at all
    python -m scripts.run_eval --prompt v1 --mode replay               # reads the response cache only
    python -m scripts.run_eval --prompt v1 --mode live --subset 15     # calls Gemini (and fills the cache)

Output: results/eval/<run_id>/{raw.jsonl, scores.json, summary.md, meta.json}. Rerun with the same --run-id
to resume: finished questions are skipped. Exit code 0 = complete, 3 = stopped on the daily quota, 2 = other
questions failed or the run was interrupted.
"""
import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from app.agent import Agent
from app.config import get_settings
from app.corpus import corpus_info
from app.llm.gemini import GeminiClient
from app.llm.resilience import ReplayLLM, build_llm
from app.retrieval.embedder import SentenceTransformerEmbedder
from app.retrieval.store import PaperStore
from app.tools.papers import build_tools
from evals.dataset import load_corpus_index, load_dataset
from evals.runner import run_questions, select_subset

DEFAULT_CACHE = "evals/cache"


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", default=None, help="prompt version, e.g. v1 (default: PROMPT_VERSION)")
    ap.add_argument("--mode", choices=["live", "replay", "retrieval"], required=True)
    ap.add_argument("--subset", type=int, default=None, help="stratified subset of N questions")
    ap.add_argument("--seed", type=int, default=0, help="subset sampling seed")
    ap.add_argument("--run-id", default=None, help="reuse to resume a run")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=240.0, help="per-question wall-clock limit in seconds")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE)
    ap.add_argument("--out-root", default="results/eval")
    args = ap.parse_args(argv)

    s = get_settings()
    prompt = args.prompt or s.prompt_version
    max_steps = args.max_steps or s.max_steps
    info = corpus_info(s.corpus_path)
    if not info["matches_frozen"]:
        print(f"corpus {s.corpus_path} does not match data/CORPUS_VERSION; refusing to evaluate against it", file=sys.stderr)
        return 1

    rows = select_subset(load_dataset(), args.subset, args.seed)
    store = PaperStore(chromadb.EphemeralClient(), SentenceTransformerEmbedder(s.embedding_model), "eval_papers")
    store.load_corpus(s.corpus_path)

    model = None if args.mode == "retrieval" else s.gemini_model
    if args.mode == "live":
        if not s.gemini_api_key:
            print("GEMINI_API_KEY is not set", file=sys.stderr)
            return 1
        llm_settings = s.model_copy(update={"llm_cache_enabled": True, "llm_cache_dir": args.cache_dir})
        llm = build_llm(llm_settings, GeminiClient(s.gemini_api_key, s.gemini_model, s.llm_timeout_s))
    elif args.mode == "replay":
        llm = ReplayLLM(args.cache_dir, namespace=s.gemini_model)
    agent = None if args.mode == "retrieval" else Agent(llm, build_tools(store), max_steps, prompt)

    run_id = args.run_id or f"{prompt}-{args.mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    meta = {
        "run_id": run_id, "mode": args.mode, "model": model, "judge_model": None, "prompt_version": prompt,
        "corpus_sha256": info["sha256"], "max_steps": max_steps, "seed": args.seed, "subset": args.subset,
        "embedding_model": s.embedding_model, "llm_rpm": s.effective_rpm if args.mode == "live" else None,
        "cache_dir": args.cache_dir if args.mode != "retrieval" else None, "git_commit": git_commit(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out_dir = Path(args.out_root) / run_id
    print(f"run {run_id}: {len(rows)} questions, mode={args.mode}, prompt={prompt}, model={model}")
    outcome = run_questions(rows, agent, store, set(load_corpus_index(s.corpus_path)), out_dir, meta,
                            question_timeout_s=args.timeout)
    print(f"{'complete' if outcome['complete'] else 'INCOMPLETE: ' + str(outcome['reason'])}; see {out_dir / 'summary.md'}")
    if outcome["complete"]:
        return 0
    return 3 if "quota" in (outcome["reason"] or "") else 2


if __name__ == "__main__":
    sys.exit(main())
