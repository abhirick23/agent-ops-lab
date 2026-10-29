from scripts.budget import plan, questions_that_fit


def test_plan_counts_runs_per_day_with_safety_margin():
    p = plan(questions=15, calls_per_question=4, rpm=15, rpd=500)
    assert p["calls_per_run"] == 60 and p["usable_calls_per_day"] == 400
    assert p["runs_per_day"] == 6 and p["minutes_per_run"] == 4.0 and p["fits_in_one_day"]


def test_plan_says_when_a_run_does_not_fit():
    p = plan(questions=80, calls_per_question=4, rpm=5, rpd=20)
    assert p["runs_per_day"] == 0 and not p["fits_in_one_day"] and p["minutes_per_run"] == 64.0


def test_questions_that_fit():
    assert questions_that_fit(runs=5, calls_per_question=4, rpd=500) == 20
