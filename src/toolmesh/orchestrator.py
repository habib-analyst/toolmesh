"""The orchestrator: routes, scope-checks, resolves, and executes plans.

Three execution strategies are provided so the benchmark can measure them
against each other:

- ``sequential``: plan order, one call at a time, no scope enforcement.
- ``naive_parallel``: every call runs against the same start-of-batch
  snapshot; writes are buffered and committed at batch end (the classic
  lost-update / stale-read failure mode). No scope enforcement.
- ``toolmesh``: scope enforcement first (out-of-scope calls denied), then
  dry-run effect simulation, conflict resolution into waves, and wave-by-wave
  execution. Within a wave, batch semantics are provably equivalent to
  sequential semantics because the wave is conflict-free by construction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .model import PlannedCall
from .registry import Registry
from .resolver import resolve
from .scopes import AgentContext
from .workspace import Workspace


@dataclass
class RunOutcome:
    final: Workspace
    steps: int
    executed: int = 0
    denied: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    violations: int = 0  # out-of-scope calls that were actually executed
    audit: list[dict[str, Any]] = field(default_factory=list)
    wall_ms: float = 0.0


_DELETED = object()


def _run_batch(calls, base: Workspace) -> int:
    """Batch semantics: every call sees the same snapshot; writes commit after.

    ``calls`` is a list of (PlannedCall, ToolSpec). Returns executed count.
    """
    start = base.snapshot()
    pending: list[dict[str, Any]] = []
    for call, spec in calls:
        scratch = base.copy()
        spec.func(scratch, dict(call.args))
        snap = scratch.snapshot()
        diff: dict[str, Any] = {}
        for key in set(start) | set(snap):
            if key not in snap:
                diff[key] = _DELETED
            elif start.get(key) != snap.get(key):
                diff[key] = snap[key]
        pending.append(diff)
    for diff in pending:
        for key, value in diff.items():
            if value is _DELETED:
                base.delete(key)
            else:
                base.set(key, value)
    return len(calls)


class Orchestrator:
    def __init__(self, registry: Registry):
        self.registry = registry

    # -- shared helpers ----------------------------------------------------
    def _route(self, plan: list[PlannedCall]):
        return [self.registry.route(c.capability) for c in plan]

    def _violations(self, plan, specs, agent: AgentContext) -> int:
        return sum(
            1
            for spec in specs
            if spec is not None and not agent.permits(spec)
        )

    # -- strategies --------------------------------------------------------
    def run_sequential(self, plan, agent, initial: Workspace) -> RunOutcome:
        t0 = time.perf_counter()
        ws = initial.copy()
        specs = self._route(plan)
        out = RunOutcome(final=ws, steps=0)
        for call, spec in zip(plan, specs):
            if spec is None:
                out.audit.append({"event": "no_tool", "call": call.call_id})
                continue
            spec.func(ws, dict(call.args))
            out.executed += 1
            out.steps += 1
            if not agent.permits(spec):
                out.violations += 1
            out.audit.append({"event": "executed", "call": call.call_id, "tool": spec.name})
        out.wall_ms = (time.perf_counter() - t0) * 1000
        return out

    def run_naive_parallel(self, plan, agent, initial: Workspace) -> RunOutcome:
        t0 = time.perf_counter()
        ws = initial.copy()
        specs = self._route(plan)
        pairs = [(c, s) for c, s in zip(plan, specs) if s is not None]
        out = RunOutcome(final=ws, steps=1 if pairs else 0)
        out.executed = _run_batch(pairs, ws)
        out.violations = self._violations(plan, specs, agent)
        for call, spec in pairs:
            out.audit.append({"event": "executed_parallel", "call": call.call_id, "tool": spec.name})
        out.wall_ms = (time.perf_counter() - t0) * 1000
        return out

    def run_toolmesh(self, plan, agent, initial: Workspace) -> RunOutcome:
        t0 = time.perf_counter()
        ws = initial.copy()
        specs = self._route(plan)
        out = RunOutcome(final=ws, steps=0)

        # 1) Permission scoping: deny out-of-scope calls before anything runs.
        kept_plan: list[PlannedCall] = []
        kept_specs = []
        for call, spec in zip(plan, specs):
            if spec is None:
                out.rejected.append((call.call_id, f"no tool for capability {call.capability!r}"))
                out.audit.append({"event": "no_tool", "call": call.call_id})
                continue
            if not agent.permits(spec):
                missing = sorted(agent.missing_scopes(spec))
                out.denied.append(call.call_id)
                out.audit.append(
                    {"event": "scope_denied", "call": call.call_id, "missing": missing}
                )
                continue
            kept_plan.append(call)
            kept_specs.append(spec)

        # 2) Dry-run simulation + conflict resolution into waves.
        resolution = resolve(kept_plan, kept_specs, ws)
        for call, reason in resolution.rejected:
            out.rejected.append((call.call_id, reason))
            out.audit.append({"event": "rejected", "call": call.call_id, "reason": reason})
        for conflict in resolution.conflicts:
            out.audit.append({"event": "conflict_resolved", "detail": conflict})

        # 3) Execute wave by wave; batch semantics inside a wave are safe.
        for i, wave in enumerate(resolution.waves):
            pairs = [(rc.call, rc.spec) for rc in wave]
            out.executed += _run_batch(pairs, ws)
            out.steps += 1
            out.audit.append(
                {"event": "wave_executed", "wave": i, "calls": [c.call_id for c, _ in pairs]}
            )
        out.wall_ms = (time.perf_counter() - t0) * 1000
        return out

    def run(self, plan, agent, initial: Workspace, strategy: str) -> RunOutcome:
        fn = {
            "sequential": self.run_sequential,
            "naive_parallel": self.run_naive_parallel,
            "toolmesh": self.run_toolmesh,
        }[strategy]
        return fn(plan, agent, initial)
