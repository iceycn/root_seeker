from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SqlTemplate:
    query_key: str
    query: str

    def render(self, params: dict[str, str | int | float]) -> str:
        return self.query.format(**params)


class SqlTemplateRegistry:
    def __init__(self, templates: list[SqlTemplate]):
        self._templates: dict[str, SqlTemplate] = {}
        for t in templates:
            if t.query_key in self._templates:
                raise ValueError(f"Duplicate query_key: {t.query_key}")
            self._templates[t.query_key] = t

    def get(self, query_key: str) -> SqlTemplate:
        try:
            return self._templates[query_key]
        except KeyError as e:
            raise KeyError(f"Unknown query_key: {query_key}") from e

