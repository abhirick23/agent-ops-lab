"""Eval runner: resumable, per-question timeout, clean exit on a daily-quota 429.

Each finished question is appended to raw.jsonl immediately, so a crash, Ctrl-C or quota exit never loses
finished work, and a rerun with the same run id skips questions already completed.
"""
import json
import os
import random
import threading
from pathlib import Path

from evals.checks import check_row
from evals.dataset import Row
from evals.retrieval import retrieval_metrics
from evals.scoring import aggregate, write_summary
from app.llm.resilience import ReplayMiss, is_daily_quota


class QuotaExhausted(Exception):
    pass


DONE = {"ok", "retrieval_only"}  # statuses that count as a finished question


def select_subset(rows: list[Row], n: int | None, seed: int) -> list[Row]:
    """Deterministic stratified subset of size n (all rows if n is None or >= len)."""
    if n is None or n >= len(rows):
        return list(rows)
    by_cat: dict[str, list[Row]] = {}
    for r in rows:
        by_cat.setdefault(r.category, []).append(r)
    exact = {c: n * len(v) / len(rows) for c, v in by_cat.items()}
    quotas = {c: int(x) for c, x in exact.items()}
    for c in sorted(exact, key=lambda c: exact[c] - quotas[c], reverse=True)[: n - sum(quotas.values())]:
        quotas[c] += 1  # largest-remainder rounding
    rng = random.Random(seed)
    chosen = {r.id for c, v in by_cat.items() for r in rng.sample(v, min(quotas[c], len(v)))}
    return [r for r in rows if r.id in chosen]


def call_with_timeout(fn, timeout_s: float):
    """Run fn() in a daemon thread. A stuck call is abandoned (it cannot be killed) so one question cannot
    block the run; the abandoned thread may still finish in the background."""
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(f"question exceeded {timeout_s:.0f}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def read_rows(raw_path: Path) -> dict[str, dict]:
    """Latest row per question id (a retried question appends a newer row)."""
    rows: dict[str, dict] = {}
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["id"]] = r
    return rows


def _append(raw_path: Path, row: dict) -> None:
    with raw_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def check_resume(out_dir: Path, meta: dict) -> None:
    """A run directory belongs to one setup; resuming under a different one would mix incomparable rows."""
    path = out_dir / "meta.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        keys = ["mode", "model", "judge_model", "prompt_version", "corpus_sha256", "max_steps", "seed", "subset", "rep"]
        diff = {k: (old.get(k), meta.get(k)) for k in keys if old.get(k) != meta.get(k)}
        if diff:
            raise SystemExit(f"cannot resume {out_dir}: setup changed (old, new): {diff}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")


def run_questions(rows: list[Row], agent, store, corpus_ids: set[str], out_dir: Path, meta: dict,
                  question_timeout_s: float = 240.0, log=print) -> dict:
    """Returns {"complete": bool, "reason": str|None}. Always writes scores.json and summary.md."""
    check_resume(out_dir, meta)
    raw_path = out_dir / "raw.jsonl"
    done = {i for i, r in read_rows(raw_path).items() if r["status"] in DONE}
    reason = None
    try:
        for n, row in enumerate(rows, 1):
            if row.id in done:
                continue
            out = {"id": row.id, "category": row.category, "subtype": row.subtype, "question": row.question,
                   "gold_paper_ids": row.gold_paper_ids, "expected_behavior": row.expected_behavior,
                   **{k: meta[k] for k in ("run_id", "mode", "model", "judge_model", "prompt_version",
                                          "corpus_sha256", "max_steps", "seed")},
                   "retrieval": retrieval_metrics(store, row)}
            if agent is None:  # retrieval-only run: no LLM involved
                out["status"] = "retrieval_only"
                _append(raw_path, out)
                continue
            try:
                res = call_with_timeout(lambda: agent.run(row.question, meta["max_steps"]), question_timeout_s)
            except TimeoutError as e:
                out.update(status="timeout", error=str(e))
            except ReplayMiss as e:
                out.update(status="replay_miss", error=str(e))
            except Exception as e:  # noqa: BLE001
                if is_daily_quota(e):
                    raise QuotaExhausted(str(e)) from e
                out.update(status="error", error=f"{type(e).__name__}: {str(e)[:300]}")
            else:
                n_turns = len(res.llm_ms_per_turn)
                out.update(
                    status="ok", answer=res.answer, source_ids=[s.id for s in res.sources],
                    steps=[{"turn": s.turn, "tool": s.tool, "arguments": s.arguments, "ok": s.ok} for s in res.steps],
                    n_llm_turns=n_turns, stopped_reason=res.stopped_reason, tokens=res.tokens.model_dump(),
                    latency_ms=res.latency_ms, llm_ms=sum(res.llm_ms_per_turn), wait_ms=sum(res.wait_ms_per_turn),
                    checks=check_row(row, res.answer, n_turns, meta["max_steps"], corpus_ids))
            _append(raw_path, out)
            log(f"[{n}/{len(rows)}] {row.id} {out['status']}")
    except QuotaExhausted as e:
        reason = f"daily quota exhausted for {meta['model']}: {str(e)[:200]}"
        log(f"STOPPING: {reason}\nFinished questions are saved; rerun with --run-id {meta['run_id']} after the quota resets.")
    except KeyboardInterrupt:
        reason = "interrupted"
        log("Interrupted; finished questions are saved.")

    latest = read_rows(raw_path)
    finished = [latest[r.id] for r in rows if r.id in latest]
    complete = reason is None and all(r.id in latest and latest[r.id]["status"] in DONE for r in rows)
    if reason is None and not complete:
        reason = "some questions failed (timeout/error/replay_miss); rerun to retry them"
    scores = aggregate(finished, expected=len(rows))
    scores["meta"] = meta
    scores["complete"] = complete
    scores["incomplete_reason"] = None if complete else reason
    (out_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8", newline="\n")
    write_summary(out_dir / "summary.md", scores)
    return {"complete": complete, "reason": reason}
