"""Dry-run effect simulation and conflict resolution.

The resolver never touches the real workspace. It first *simulates* the plan
on a throwaway copy to verify that each tool's declared effects match what it
actually does, then partitions the plan into conflict-free execution waves:

- calls with no declared-effect conflict share a wave (safe to run in parallel);
- conflicting calls are serialized into later waves, preserving plan order;
- a call flagged ``exclusive`` that write-conflicts with another planned call
  is rejected outright (the earlier call wins) with a recorded reason;
- a call whose actual effects exceed its declaration is rejected as unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import EffectSet, PlannedCall, ToolSpec
from .workspace import Workspace


@dataclass
class ResolvedCall:
    call: PlannedCall
    spec: ToolSpec
    effects: EffectSet


@dataclass
class Resolution:
    waves: list[list[ResolvedCall]] = field(default_factory=list)
    rejected: list[tuple[PlannedCall, str]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def _actual_writes(spec: ToolSpec, call: PlannedCall, base: Workspace) -> set[str]:
    """Run the call on a scratch copy and diff keys to find real writes."""
    scratch = base.copy()
    before = scratch.snapshot()
    spec.func(scratch, dict(call.args))
    after = scratch.snapshot()
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return changed


def resolve(
    plan: list[PlannedCall],
    specs: list[ToolSpec | None],
    initial: Workspace,
) -> Resolution:
    """Simulate + resolve a plan into waves. ``specs`` aligns with ``plan``."""
    res = Resolution()
    accepted: list[ResolvedCall] = []

    for call, spec in zip(plan, specs):
        if spec is None:
            res.rejected.append((call, f"no tool registered for capability {call.capability!r}"))
            continue
        declared = spec.effects(dict(call.args))
        # Dry-run verification: the tool must do only what it declared.
        try:
            actual = _actual_writes(spec, call, initial)
        except Exception as exc:  # a tool that crashes in simulation is unsafe to run
            res.rejected.append((call, f"dry-run simulation failed: {exc}"))
            continue
        undeclared = actual - set(declared.writes)
        if undeclared:
            res.rejected.append(
                (call, f"effect declaration violated: wrote undeclared {sorted(undeclared)}")
            )
            continue
        accepted.append(ResolvedCall(call=call, spec=spec, effects=declared))

    # Exclusive conflicts: first exclusive/plain writer wins; a later call that
    # write-conflicts with an exclusive call (or vice versa) is rejected.
    kept: list[ResolvedCall] = []
    for rc in accepted:
        reject_reason = None
        for prev in kept:
            conflict, why = rc.effects.conflicts_with(prev.effects)
            if conflict and (rc.call.exclusive or prev.call.exclusive) and (
                rc.effects.writes & prev.effects.writes
            ):
                reject_reason = (
                    f"exclusive write conflict with call {prev.call.call_id or '?'}: {why}"
                )
                break
        if reject_reason:
            res.rejected.append((rc.call, reject_reason))
        else:
            kept.append(rc)

    # Wave partition preserving plan order: each call goes into the earliest
    # wave that is strictly later than every earlier call it conflicts with.
    # By construction it then conflicts with no member of its own wave.
    wave_of: dict[int, int] = {}
    for idx, rc in enumerate(kept):
        earliest = 0
        for jdx, prev in enumerate(kept[:idx]):
            conflict, why = rc.effects.conflicts_with(prev.effects)
            if conflict:
                earliest = max(earliest, wave_of[jdx] + 1)
                entry = f"{prev.call.call_id or '?'} vs {rc.call.call_id or '?'}: {why}"
                if entry not in res.conflicts:
                    res.conflicts.append(entry)
        wave_of[idx] = earliest
        while len(res.waves) <= earliest:
            res.waves.append([])
        res.waves[earliest].append(rc)

    return res
