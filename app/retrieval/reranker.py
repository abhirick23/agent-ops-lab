from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, docs: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def score(self, query: str, docs: list[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return [float(s) for s in self._model.predict([(query, d) for d in docs])]
