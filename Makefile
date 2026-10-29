ifeq ($(OS),Windows_NT)
VENV_PY := .venv/Scripts/python.exe
else
VENV_PY := .venv/bin/python
endif

.PHONY: setup corpus index test run

setup:  ## create .venv (Python 3.10+) and install the project with dev extras
	python -m venv .venv
	$(VENV_PY) -m pip install -e ".[dev]"
	@test -f .env || cp .env.example .env

corpus:  ## fetch ~200 arXiv abstracts into data/corpus.jsonl
	$(VENV_PY) -m scripts.fetch_corpus

index:  ## embed the corpus into the local Chroma index
	$(VENV_PY) -m scripts.build_index

test:  ## run pytest and write results/coverage.txt
	@mkdir -p results
	$(VENV_PY) -m pytest --cov=app --cov-report=term-missing | tee results/coverage.txt

run:  ## start the API on http://localhost:8000
	$(VENV_PY) -m uvicorn app.main:app --reload
