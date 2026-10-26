"""An in-memory key/value workspace that tools act on."""

from __future__ import annotations

import copy
from typing import Any


class Workspace:
    def __init__(self, initial: dict[str, Any] | None = None):
        self._data: dict[str, Any] = copy.deepcopy(initial or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def copy(self) -> "Workspace":
        return Workspace(self._data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Workspace) and self._data == other._data

    def __repr__(self) -> str:
        return f"Workspace({self._data!r})"
