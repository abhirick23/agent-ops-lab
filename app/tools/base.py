from typing import Callable

from pydantic import BaseModel, ValidationError


class Tool:
    """A callable with Pydantic-validated input and output."""

    def __init__(
        self,
        name: str,
        description: str,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        fn: Callable[[BaseModel], BaseModel],
    ):
        self.name = name
        self.description = description
        self.input_model = input_model
        self.output_model = output_model
        self._fn = fn

    def run(self, raw_args: dict) -> BaseModel:
        """Raises pydantic.ValidationError on bad arguments."""
        args = self.input_model.model_validate(raw_args)
        return self.output_model.model_validate(self._fn(args).model_dump())

    def parameters_schema(self) -> dict:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def __iter__(self):
        return iter(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def execute(self, name: str, raw_args: dict) -> tuple[bool, BaseModel | dict]:
        """Returns (ok, output). Failures come back as {"error": ...} for the model to read."""
        tool = self._tools.get(name)
        if tool is None:
            return False, {"error": f"unknown tool '{name}'", "available": self.names()}
        try:
            return True, tool.run(raw_args)
        except ValidationError as e:
            return False, {
                "error": "invalid arguments",
                "details": [f"{'.'.join(map(str, d['loc']))}: {d['msg']}" for d in e.errors()],
            }
