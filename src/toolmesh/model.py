"""Core data types: declared effects, planned calls, tool specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class EffectSet:
    """Resources a tool call declares it will read and write."""

    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()

    def conflicts_with(self, other: "EffectSet") -> tuple[bool, str]:
        """Two calls conflict if one writes a resource the other reads or writes."""
        ww = self.writes & other.writes
        if ww:
            return True, f"write-write on {sorted(ww)}"
        wr = self.writes & other.reads
        if wr:
            return True, f"write-read on {sorted(wr)}"
        rw = self.reads & other.writes
        if rw:
            return True, f"read-write on {sorted(rw)}"
        return False, ""


@dataclass
class PlannedCall:
    """One tool call in a plan, addressed by capability (not tool name)."""

    capability: str
    args: dict[str, Any]
    exclusive: bool = False  # if True, this call demands sole write access to its write set
    call_id: str = ""


@dataclass
class ToolSpec:
    """A registered tool.

    effects: maps call args -> declared EffectSet (the dry-run contract).
    func:    executes against a Workspace, returns a result value.
    """

    name: str
    capabilities: frozenset[str]
    required_scopes: frozenset[str]
    effects: Callable[[dict[str, Any]], EffectSet]
    func: Callable[[Any, dict[str, Any]], Any]
    metadata: dict[str, Any] = field(default_factory=dict)
