import pytest
from pydantic import ValidationError

from app.tools.papers import (
    GetPaperOutput,
    SearchPapersInput,
    SearchPapersOutput,
    SummarizeOutput,
)


def test_search_papers_output_model(tools):
    ok, out = tools.execute("search_papers", {"query": "gradient boosting trees", "k": 2})
    assert ok
    assert isinstance(out, SearchPapersOutput)
    assert out.results[0].id == "2401.00002"
    assert len(out.results) == 2
    assert len(out.results[0].snippet) <= 300


def test_search_papers_defaults_k(tools):
    ok, out = tools.execute("search_papers", {"query": "language models"})
    assert ok and len(out.results) == 3  # corpus has 3 papers, default k=5


@pytest.mark.parametrize("args", [{}, {"query": ""}, {"query": "x", "k": 0}, {"query": "x", "k": 11}])
def test_search_papers_rejects_bad_input(tools, args):
    ok, out = tools.execute("search_papers", args)
    assert not ok
    assert out["error"] == "invalid arguments"


def test_input_model_validation_direct():
    with pytest.raises(ValidationError):
        SearchPapersInput(query="x", k="many")


def test_get_paper_found(tools):
    ok, out = tools.execute("get_paper", {"paper_id": "2401.00001"})
    assert ok and isinstance(out, GetPaperOutput)
    assert out.found and out.paper.title.startswith("Efficient Transformers")


def test_get_paper_not_found_is_not_an_error(tools):
    ok, out = tools.execute("get_paper", {"paper_id": "0000.00000"})
    assert ok and not out.found and out.paper is None


def test_summarize_limits_sentences(tools):
    ok, out = tools.execute("summarize_paper", {"paper_id": "2401.00001", "max_sentences": 1})
    assert ok and isinstance(out, SummarizeOutput)
    assert out.summary == "We study attention mechanisms for long context language models."


def test_summarize_missing_paper(tools):
    ok, out = tools.execute("summarize_paper", {"paper_id": "0000.00000"})
    assert ok and not out.found and out.summary == ""


def test_unknown_tool(tools):
    ok, out = tools.execute("delete_everything", {})
    assert not ok
    assert "search_papers" in out["available"]


def test_parameters_schema_has_no_title(tools):
    schemas = {t.name: t.parameters_schema() for t in tools}
    assert "title" not in schemas["search_papers"]
    assert schemas["get_paper"]["required"] == ["paper_id"]
