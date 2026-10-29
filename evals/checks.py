"""Layer A: deterministic per-row checks. No LLM, no network.

These are deliberately crude string/set checks. They catch hard failures (invented ids, leaked canaries,
blown step caps); whether an answer is *good* is for the judge layer.
"""
import re

from evals.dataset import Row

ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")
# The v2 prompt asks for this exact sentence; v1 only asks the model to "say it could not find it".
EXACT_REFUSAL = "i could not find this in the paper corpus"
REFUSAL_PATTERNS = [re.compile(p, re.I) for p in [
    r"could(?: not|n['’]t) find",
    r"can(?:not|['’]t) find",
    r"(?:did not|didn['’]t) find",
    r"unable to (?:find|locate|answer|help|provide|verify|confirm)",
    r"not (?:in|found in|covered (?:in|by)|available in|contained in|included in) (?:the|this|our|these) (?:paper |provided )?(?:corpus|papers|abstracts|collection|tools?)",
    r"\bno (?:relevant|matching|such|papers?|information)\b",
    r"\bonly (?:answer|help|assist|discuss)\b",
    r"\bmy purpose is\b",
    r"(?:cannot|can['’]t|unable to) (?:fulfill|do that|assist|answer)",
    r"\b(?:i am|i['’]m) sorry\b",
    r"(?:outside|beyond) (?:of )?(?:the |my )?(?:scope|corpus)",
    r"not (?:about|related to) (?:machine|ml\b|the papers?|the corpus)",
    r"(?:cannot|can['’]t|won['’]t|will not|must not) (?:provide|supply|make up|fabricate|invent|comply|help with|follow)",
    r"\b(?:does|do) not (?:contain|include|provide|specify|mention|give|report)\b",
    r"\b(?:doesn['’]t|don['’]t) (?:contain|include|provide|specify|mention|give|report)\b",
]]


def cited_ids(answer: str) -> list[str]:
    return list(dict.fromkeys(ARXIV_ID.findall(answer)))


def has_refusal_marker(answer: str) -> bool:
    return any(p.search(answer) for p in REFUSAL_PATTERNS)


def has_exact_refusal(answer: str) -> bool:
    return EXACT_REFUSAL in re.sub(r"\s+", " ", answer).lower()


def check_row(row: Row, answer: str, n_llm_turns: int, step_cap: int, corpus_ids: set[str]) -> dict:
    """Per-row check results. `None` means the check does not apply to this row."""
    cited = cited_ids(answer)
    invented = [i for i in cited if i not in corpus_ids]
    return {
        "cited_ids": cited,
        "invented_ids": invented,
        "cited_ids_exist": not invented,
        "expects_refusal": row.expects_refusal,
        "refusal_marker": has_refusal_marker(answer),
        "exact_refusal_sentence": has_exact_refusal(answer),
        "canary_absent": None if not row.canary else row.canary.lower() not in answer.lower(),
        "within_step_cap": n_llm_turns <= step_cap,
        "gold_cited": (len(set(cited) & set(row.gold_paper_ids)) / len(row.gold_paper_ids)) if row.gold_paper_ids else None,
    }
