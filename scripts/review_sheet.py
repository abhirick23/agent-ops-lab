"""Write evals/REVIEW.md: a seeded sample of dataset rows with the evidence for each gold id, for human review."""
import random
import textwrap
from pathlib import Path

from evals.dataset import load_corpus_index, load_dataset


def main(n: int = 15, seed: int = 7) -> None:
    rows, corpus = load_dataset(), load_corpus_index()
    # stratified: answerable-heavy because gold ids are what a wrong row would corrupt
    quota = {"answerable": 8, "unanswerable": 3, "adversarial": 4}
    rng = random.Random(seed)
    sample = []
    for cat, k in quota.items():
        sample += rng.sample([r for r in rows if r.category == cat], k)
    out = ["# Dataset review sample", "",
           f"{len(sample)} rows drawn with seed {seed}. For each answerable row check that every gold paper really answers the "
           "question and that no other corpus paper should be added. Mark each row OK / FIX.", ""]
    for r in sample:
        out += [f"## {r.id} ({r.category}/{r.subtype}) - expected: `{r.expected_behavior}`", "",
                f"**Q:** {r.question}", ""]
        for pid in r.gold_paper_ids:
            p = corpus[pid]
            out.append(f"- gold `{pid}` *{p['title']}*")
            if pid in r.support:
                out.append(f"  - evidence: \"{r.support[pid]}\"")
        if r.canary:
            out.append(f"- canary: `{r.canary}`")
        out += [f"- notes: {textwrap.shorten(r.notes, 200)}", "- verdict: [ ] OK  [ ] FIX", ""]
    Path("evals/REVIEW.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
    print("wrote evals/REVIEW.md with", len(sample), "rows")


if __name__ == "__main__":
    main()
