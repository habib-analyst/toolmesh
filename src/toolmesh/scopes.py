"""Permission scoping: agents hold granted scopes; tools require scopes."""

from __future__ import annotations

from dataclasses import dataclass

from .model import ToolSpec


@dataclass(frozen=True)
class AgentContext:
    agent_id: str
    granted_scopes: frozenset[str]

    def missing_scopes(self, spec: ToolSpec) -> frozenset[str]:
        return spec.required_scopes - self.granted_scopes

    def permits(self, spec: ToolSpec) -> bool:
        return not self.missing_scopes(spec)
