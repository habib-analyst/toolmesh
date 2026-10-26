"""Dynamic tool registry with capability-based routing."""

from __future__ import annotations

from .model import ToolSpec


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._by_capability: dict[str, list[str]] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec
        for cap in spec.capabilities:
            self._by_capability.setdefault(cap, []).append(spec.name)

    def unregister(self, name: str) -> None:
        spec = self._tools.pop(name, None)
        if spec is None:
            return
        for cap in spec.capabilities:
            self._by_capability[cap] = [n for n in self._by_capability[cap] if n != name]

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def route(self, capability: str) -> ToolSpec | None:
        """Capability-based routing: first registered tool offering the capability."""
        names = self._by_capability.get(capability)
        if not names:
            return None
        return self._tools[names[0]]

    def tools_for(self, capability: str) -> list[ToolSpec]:
        return [self._tools[n] for n in self._by_capability.get(capability, [])]

    def names(self) -> list[str]:
        return sorted(self._tools)
