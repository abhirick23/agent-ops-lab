from evals.dataset import load_corpus_index, load_dataset, validate


def test_dataset_is_valid_against_the_frozen_corpus():
    rows = load_dataset()
    assert validate(rows, load_corpus_index()) == []


def test_dataset_mix_and_adversarial_subtypes():
    rows = load_dataset()
    assert len(rows) == 80
    adv = {r.subtype for r in rows if r.category == "adversarial"}
    assert adv == {"injection", "false_premise", "fabrication", "off_topic", "step_cap"}
    assert {r.subtype for r in rows if r.category == "answerable"} == {"single", "multi"}


def test_validator_catches_bad_gold_and_snippet():
    rows = load_dataset()
    corpus = load_corpus_index()
    bad = rows[0].model_copy(update={"gold_paper_ids": ["9999.99999"], "support": {"9999.99999": "x"}})
    assert any("not in corpus" in e for e in validate([bad] + rows[1:], corpus))
    wrong = rows[0].model_copy(update={"support": {rows[0].gold_paper_ids[0]: "text that is not in the abstract"}})
    assert any("not found" in e for e in validate([wrong] + rows[1:], corpus))
