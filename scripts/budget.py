"""How many eval runs fit in the free tier? Run this before spending quota.

    python -m scripts.budget --questions 15 --calls-per-question 3.5 --rpm 15 --rpd 500
    python -m scripts.budget --questions 80 --rpm 15            # --rpd omitted: shows a range of possibilities

Calls per question = LLM turns of the agent (one request each) plus any judge/faithfulness requests that
share the same model's quota. Measure it from a real run: `llm_turns_mean` in scores.json.
"""
import argparse
import math

UNKNOWN_RPD_SCENARIOS = [20, 100, 250, 500, 1000, 1500]


def plan(questions: int, calls_per_question: float, rpm: int, rpd: int, safety: float = 0.8) -> dict:
    """`safety` reserves part of the daily cap for retries (a retried attempt can count against the quota)."""
    calls_per_run = math.ceil(questions * calls_per_question)
    usable = int(rpd * safety)
    return {
        "calls_per_run": calls_per_run,
        "minutes_per_run": round(calls_per_run / rpm, 1),  # rate-limited by RPM; model time adds on top
        "runs_per_day": usable // calls_per_run,
        "usable_calls_per_day": usable,
        "fits_in_one_day": calls_per_run <= usable,
    }


def questions_that_fit(runs: int, calls_per_question: float, rpd: int, safety: float = 0.8) -> int:
    """Largest question count for which `runs` runs fit in one day."""
    return int(rpd * safety / runs / calls_per_question)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", type=int, required=True)
    ap.add_argument("--calls-per-question", type=float, default=3.5, help="planning guess until measured")
    ap.add_argument("--rpm", type=int, required=True)
    ap.add_argument("--rpd", type=int, default=None)
    ap.add_argument("--runs", type=int, default=1, help="runs you want in total, to compute days needed")
    ap.add_argument("--safety", type=float, default=0.8)
    a = ap.parse_args()

    scenarios = [a.rpd] if a.rpd else UNKNOWN_RPD_SCENARIOS
    if not a.rpd:
        print("RPD not given (unknown): showing a range. Measure it before trusting any row.\n")
    print(f"{a.questions} questions x {a.calls_per_question} calls = {math.ceil(a.questions * a.calls_per_question)} requests/run, "
          f"RPM {a.rpm}, {int(a.safety * 100)}% of RPD usable\n")
    print(f"{'RPD':>6} {'runs/day':>9} {'min/run':>8} {'days for ' + str(a.runs) + ' runs':>16} {'max Q for ' + str(a.runs) + ' runs in 1 day':>24}")
    for rpd in scenarios:
        p = plan(a.questions, a.calls_per_question, a.rpm, rpd, a.safety)
        days = math.ceil(a.runs / p["runs_per_day"]) if p["runs_per_day"] else "never"
        print(f"{rpd:>6} {p['runs_per_day']:>9} {p['minutes_per_run']:>8} {days:>16} "
              f"{questions_that_fit(a.runs, a.calls_per_question, rpd, a.safety):>24}")


if __name__ == "__main__":
    main()
