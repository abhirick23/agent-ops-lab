import json
import time

import pytest

from app.agent import Agent
from app.llm.base import LLMResponse
from app.llm.resilience import CachingLLM, ReplayLLM, ReplayMiss
from app.prompts import load_prompt
from evals.checks import check_row, has_exact_refusal, has_refusal_marker
from evals.dataset import Row, load_dataset
from evals.retrieval import recall_at_k, reciprocal_rank, retrieval_metrics
from evals.runner import read_rows, run_questions, select_subset
from evals.stats import bootstrap_ci
from tests.conftest import PAPERS, ScriptedLLM, text_response

CORPUS_IDS = {p.id for p in PAPERS}


def row(i="r1", cat="answerable", gold=("2401.00002",), beh="answer", canary=None, q="gradient boosting trees"):
    return Row(id=i, category=cat, subtype="single", question=q, gold_paper_ids=list(gold),
               expected_behavior=beh, notes="", canary=canary)


def meta(**kw):
    m = {"run_id": "t", "mode": "live", "model": "m", "judge_model": None, "prompt_version": "v1",
         "corpus_sha256": "abc", "max_steps": 3, "seed": 0, "subset": None}
    return {**m, **kw}


# ---- checks -------------------------------------------------------------------------------------

def test_invented_id_is_flagged():
    c = check_row(row(), "See [2401.00002] and [2499.12345].", 1, 5, CORPUS_IDS)
    assert c["invented_ids"] == ["2499.12345"] and c["cited_ids_exist"] is False
    assert c["gold_cited"] == 1.0


def test_canary_and_step_cap_checks():
    r = row(cat="adversarial", gold=(), beh="answer_ignore_injection", canary="PWNED-7731")
    assert check_row(r, "pwned-7731 as asked", 1, 5, CORPUS_IDS)["canary_absent"] is False
    assert check_row(r, "Here is the answer.", 6, 5, CORPUS_IDS)["canary_absent"] is True
    assert check_row(r, "x", 6, 5, CORPUS_IDS)["within_step_cap"] is False
    assert check_row(row(), "x", 1, 5, CORPUS_IDS)["canary_absent"] is None  # n/a without a canary


@pytest.mark.parametrize("text,expected", [
    ("I could not find this in the paper corpus.", True),
    ("Sorry, I can't find any paper on that.", True),
    ("The abstract does not specify the learning rate.", True),
    ("I can only answer questions about the paper corpus.", True),
    ("SelfExtend uses bi-level attention [2401.01325].", False),
    ("I stopped before finishing: the step limit (5) was reached", False),
])
def test_refusal_marker(text, expected):
    assert has_refusal_marker(text) is expected


def test_exact_refusal_sentence_ignores_case_and_whitespace():
    assert has_exact_refusal("I could   not find\nthis in the paper corpus.")
    assert not has_exact_refusal("I could not find it.")


# ---- retrieval metrics / stats --------------------------------------------------------------------

def test_recall_and_rr():
    assert recall_at_k(["a", "b", "c"], ["a", "z"], 5) == 0.5
    assert recall_at_k(["x", "y", "a"], ["a"], 2) == 0.0
    assert reciprocal_rank(["x", "a"], ["a"]) == 0.5
    assert reciprocal_rank(["x"], ["a"]) == 0.0


def test_retrieval_metrics_on_store(store):
    m = retrieval_metrics(store, row(), k=5, depth=10)
    assert m["ranked_ids"][0] == "2401.00002" and m["recall_at_5"] == 1.0 and m["rr_at_10"] == 1.0
    assert retrieval_metrics(store, row(gold=())) is None


def test_bootstrap_ci_is_seeded_and_brackets_the_mean():
    vals = [1, 1, 0, 1, 0, 1, 1, 1]
    a, b = bootstrap_ci(vals, n_boot=2000, seed=1), bootstrap_ci(vals, n_boot=2000, seed=1)
    assert a == b and a["ci_lo"] <= a["mean"] <= a["ci_hi"] and a["mean"] == 0.75
    assert bootstrap_ci([1, 1, 1, 1], n_boot=200)["ci_lo"] == 1.0
    assert bootstrap_ci([])["n"] == 0


# ---- subset / prompts -----------------------------------------------------------------------------

def test_subset_is_stratified_deterministic_and_sized():
    rows = load_dataset()
    a, b = select_subset(rows, 15, seed=3), select_subset(rows, 15, seed=3)
    assert [r.id for r in a] == [r.id for r in b] and len(a) == 15
    cats = {c: sum(r.category == c for r in a) for c in ("answerable", "unanswerable", "adversarial")}
    assert cats == {"answerable": 7, "unanswerable": 4, "adversarial": 4}
    assert select_subset(rows, None, 0) == rows


def test_prompts_load_and_differ():
    v1, v2, v3 = (load_prompt(v) for v in ("v1", "v2", "v3"))
    assert len({v1, v2, v3}) == 3
    assert "could not find" in v1 and "I could not find this in the paper corpus." in v2
    assert "untrusted" in v2 and "never say that you do not know" in v3
    with pytest.raises(ValueError):
        load_prompt("../secrets")
    with pytest.raises(FileNotFoundError):
        load_prompt("v99")


def test_agent_reports_prompt_version(tools):
    llm = ScriptedLLM([text_response("hi")])
    assert Agent(llm, tools, prompt_version="v2").run("q").prompt_version == "v2"


# ---- runner ---------------------------------------------------------------------------------------

class QuotaError(Exception):
    details = {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]}}


class Seq:
    """LLM that returns/raises items in order."""

    def __init__(self, items):
        self.items, self.n = list(items), 0

    def generate(self, system, messages, tools):
        self.n += 1
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item()
        return item


def rows3():
    return [row("r1"), row("r2", cat="unanswerable", gold=(), beh="refuse"), row("r3")]


def test_run_writes_row_per_question_with_pinned_setup(tmp_path, store, tools):
    llm = Seq([text_response("Boosting [2401.00002]."), text_response("I could not find this in the paper corpus."),
               text_response("[2401.00002]")])
    out = run_questions(rows3(), Agent(llm, tools, 3), store, CORPUS_IDS, tmp_path, meta(), log=lambda *_: None)
    assert out["complete"]
    raw = [json.loads(line) for line in (tmp_path / "raw.jsonl").read_text().splitlines()]
    assert [r["id"] for r in raw] == ["r1", "r2", "r3"]
    first = raw[0]
    for k in ("model", "judge_model", "prompt_version", "corpus_sha256", "max_steps", "mode", "seed"):
        assert k in first
    assert first["retrieval"]["recall_at_5"] == 1.0 and first["checks"]["gold_cited"] == 1.0
    scores = json.loads((tmp_path / "scores.json").read_text())
    assert scores["complete"] and scores["metrics"]["refusal_marker_unanswerable"]["mean"] == 1.0
    assert "INCOMPLETE" not in (tmp_path / "summary.md").read_text()


def test_quota_exit_is_clean_keeps_finished_work_and_marks_incomplete(tmp_path, store, tools):
    llm = Seq([text_response("a [2401.00002]"), QuotaError("429 daily")])
    out = run_questions(rows3(), Agent(llm, tools, 3), store, CORPUS_IDS, tmp_path, meta(), log=lambda *_: None)
    assert out["complete"] is False and "quota" in out["reason"]
    assert list(read_rows(tmp_path / "raw.jsonl")) == ["r1"]  # the finished question survived; r2 left for the rerun
    assert llm.n == 2  # r3 was never attempted
    summary = (tmp_path / "summary.md").read_text()
    assert "INCOMPLETE" in summary and "1 of 3" in summary


def test_rerun_resumes_and_skips_completed_ids(tmp_path, store, tools):
    run_questions(rows3(), Agent(Seq([text_response("a"), QuotaError("x")]), tools, 3), store, CORPUS_IDS,
                  tmp_path, meta(), log=lambda *_: None)
    second = Seq([text_response("b"), text_response("c")])
    out = run_questions(rows3(), Agent(second, tools, 3), store, CORPUS_IDS, tmp_path, meta(), log=lambda *_: None)
    assert out["complete"] and second.n == 2  # r1 was not rerun
    assert list(read_rows(tmp_path / "raw.jsonl")) == ["r1", "r2", "r3"]


def test_resume_refuses_a_changed_setup(tmp_path, store, tools):
    run_questions([row("r1")], Agent(Seq([text_response("a")]), tools, 3), store, CORPUS_IDS, tmp_path, meta(),
                  log=lambda *_: None)
    with pytest.raises(SystemExit, match="prompt_version"):
        run_questions([row("r1")], Agent(Seq([]), tools, 3), store, CORPUS_IDS, tmp_path,
                      meta(prompt_version="v2"), log=lambda *_: None)


def test_hung_question_times_out_and_run_continues(tmp_path, store, tools):
    llm = Seq([lambda: time.sleep(5), text_response("fine")])
    t0 = time.monotonic()
    out = run_questions([row("r1"), row("r3")], Agent(llm, tools, 3), store, CORPUS_IDS, tmp_path, meta(),
                        question_timeout_s=0.3, log=lambda *_: None)
    assert time.monotonic() - t0 < 4
    latest = read_rows(tmp_path / "raw.jsonl")
    assert latest["r1"]["status"] == "timeout" and latest["r3"]["status"] == "ok"
    assert out["complete"] is False  # the timed-out question is retried on the next run


def test_other_errors_are_recorded_not_fatal(tmp_path, store, tools):
    llm = Seq([RuntimeError("boom"), text_response("ok [2401.00002]")])
    run_questions([row("r1"), row("r3")], Agent(llm, tools, 3), store, CORPUS_IDS, tmp_path, meta(), log=lambda *_: None)
    latest = read_rows(tmp_path / "raw.jsonl")
    assert latest["r1"]["status"] == "error" and "RuntimeError" in latest["r1"]["error"]
    assert latest["r3"]["status"] == "ok"


def test_retrieval_only_run_needs_no_llm(tmp_path, store):
    out = run_questions(rows3(), None, store, CORPUS_IDS, tmp_path, meta(mode="retrieval", model=None), log=lambda *_: None)
    assert out["complete"]
    scores = json.loads((tmp_path / "scores.json").read_text())
    assert scores["metrics"]["retrieval_recall_at_5"]["n"] == 2 and scores["metrics"]["cited_ids_exist"]["n"] == 0


# ---- replay ---------------------------------------------------------------------------------------

def test_replay_serves_cached_responses_and_never_calls_a_provider(tmp_path, tools):
    live = ScriptedLLM([text_response("cached answer [2401.00002]")])
    cached = CachingLLM(live, tmp_path, namespace="m")
    live_result = Agent(cached, tools, 3, "v2").run("q?")

    replay_result = Agent(ReplayLLM(tmp_path, "m"), tools, 3, "v2").run("q?")
    assert replay_result.answer == live_result.answer
    assert len(live.calls) == 1  # replay added no provider call


def test_replay_miss_when_prompt_changes(tmp_path, tools):
    Agent(CachingLLM(ScriptedLLM([text_response("a")]), tmp_path, "m"), tools, 3, "v1").run("q?")
    with pytest.raises(ReplayMiss):
        Agent(ReplayLLM(tmp_path, "m"), tools, 3, "v2").run("q?")  # different prompt => different key
    with pytest.raises(ReplayMiss):
        Agent(ReplayLLM(tmp_path, "other-model"), tools, 3, "v1").run("q?")


def test_replay_miss_is_recorded_per_question(tmp_path, store, tools):
    run_questions([row("r1")], Agent(ReplayLLM(tmp_path / "empty", "m"), tools, 3), store, CORPUS_IDS,
                  tmp_path / "run", meta(mode="replay"), log=lambda *_: None)
    assert read_rows(tmp_path / "run" / "raw.jsonl")["r1"]["status"] == "replay_miss"
    assert isinstance(LLMResponse(), LLMResponse)
