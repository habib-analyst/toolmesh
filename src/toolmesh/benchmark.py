"""Benchmark: naive parallel vs sequential vs toolmesh on a synthetic
workflow suite with planted conflicts, scope injections, and exclusive
write races.

Intended final state is defined by a reference executor with the semantics
a careful operator would want: plan order, permission-filtered (out-of-scope
calls never happen), exclusive-write first-wins. A strategy is "correct" on
a task when its final workspace equals the intended one exactly.

Run:  python -m toolmesh.benchmark [tasks_per_family] [seed]
Writes results.json next to the repo root (or ./results.json).
"""

from __future__ import annotations

import json
import random
import sys
import time
from dataclasses import dataclass

from .model import PlannedCall
from .orchestrator import Orchestrator
from .scopes import AgentContext
from .tools import default_registry
from .workspace import Workspace

AGENT = AgentContext(agent_id="bench-agent", granted_scopes=frozenset({"read", "write"}))


@dataclass
class Task:
    family: str
    initial: dict
    plan: list[PlannedCall]
    intended: dict


def _call(cid, capability, args, exclusive=False):
    return PlannedCall(capability=capability, args=args, exclusive=exclusive, call_id=cid)


def reference_final(task_initial: dict, plan: list[PlannedCall], orch: Orchestrator) -> dict:
    """Intended semantics: ordered, permission-filtered, exclusive first-wins."""
    ws = Workspace(task_initial)
    accepted_writes: list[tuple[PlannedCall, set]] = []
    for call in plan:
        spec = orch.registry.route(call.capability)
        if spec is None or not AGENT.permits(spec):
            continue
        writes = set(spec.effects(dict(call.args)).writes)
        skip = False
        for prev_call, prev_writes in accepted_writes:
            if writes & prev_writes and (call.exclusive or prev_call.exclusive):
                skip = True
                break
        if skip:
            continue
        spec.func(ws, dict(call.args))
        accepted_writes.append((call, writes))
    return ws.snapshot()


def gen_clean(rng: random.Random, idx: int) -> Task:
    n = rng.randint(4, 8)
    plan, initial = [], {}
    for i in range(n):
        key = f"k{idx}_{i}"
        plan.append(_call(f"c{i}", "store.set", {"key": key, "value": rng.randint(0, 99)}))
    return Task("clean", initial, plan, {})


def gen_ww(rng: random.Random, idx: int) -> Task:
    counter = f"counter{idx}"
    initial = {counter: 0}
    plan = [_call("w0", "math.increment", {"key": counter, "by": rng.randint(1, 5)})]
    plan.append(_call("w1", "math.increment", {"key": counter, "by": rng.randint(1, 5)}))
    plan.append(_call("w2", "store.set", {"key": f"other{idx}", "value": 7}))
    if rng.random() < 0.5:
        plan.append(_call("w3", "math.increment", {"key": counter, "by": rng.randint(1, 5)}))
    return Task("write_write", initial, plan, {})


def gen_wr(rng: random.Random, idx: int) -> Task:
    src, dst = f"src{idx}", f"dst{idx}"
    initial = {src: 0}
    plan = [
        _call("r0", "store.set", {"key": src, "value": rng.randint(10, 99)}),
        _call("r1", "store.copy", {"src": src, "dst": dst}),
        _call("r2", "math.increment", {"key": dst, "by": 1}),
    ]
    return Task("write_read", initial, plan, {})


def gen_scope(rng: random.Random, idx: int) -> Task:
    keep, drop = f"keep{idx}", f"drop{idx}"
    initial = {keep: 1, drop: 2}
    plan = [
        _call("s0", "store.set", {"key": keep, "value": 42}),
        _call("s1", "store.delete", {"key": drop}),  # needs admin; agent lacks it
        _call("s2", "store.set", {"key": f"extra{idx}", "value": 3}),
    ]
    return Task("scope_injection", initial, plan, {})


def gen_exclusive(rng: random.Random, idx: int) -> Task:
    key = f"lock{idx}"
    initial = {}
    plan = [
        _call("x0", "store.set", {"key": key, "value": "first"}, exclusive=True),
        _call("x1", "store.set", {"key": key, "value": "second"}, exclusive=True),
        _call("x2", "store.set", {"key": f"free{idx}", "value": 1}),
    ]
    return Task("exclusive", initial, plan, {})


FAMILIES = [gen_clean, gen_ww, gen_wr, gen_scope, gen_exclusive]
STRATEGIES = ["naive_parallel", "sequential", "toolmesh"]


def build_suite(tasks_per_family: int, seed: int, orch: Orchestrator) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []
    for gen in FAMILIES:
        for i in range(tasks_per_family):
            task = gen(rng, i)
            task.intended = reference_final(task.initial, task.plan, orch)
            tasks.append(task)
    return tasks


def main() -> None:
    tasks_per_family = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    orch = Orchestrator(default_registry())
    tasks = build_suite(tasks_per_family, seed, orch)

    results: dict = {
        "suite": {
            "tasks": len(tasks),
            "tasks_per_family": tasks_per_family,
            "families": sorted({t.family for t in tasks}),
            "seed": seed,
        },
        "strategies": {},
    }
    for strategy in STRATEGIES:
        agg = {
            "tasks_correct": 0,
            "total_steps": 0,
            "total_executed": 0,
            "permission_violations": 0,
            "scope_denied": 0,
            "rejected": 0,
            "wall_ms_total": 0.0,
            "by_family": {},
        }
        for task in tasks:
            out = orch.run(task.plan, AGENT, Workspace(task.initial), strategy)
            correct = out.final.snapshot() == task.intended
            agg["tasks_correct"] += int(correct)
            agg["total_steps"] += out.steps
            agg["total_executed"] += out.executed
            agg["permission_violations"] += out.violations
            agg["scope_denied"] += len(out.denied)
            agg["rejected"] += len(out.rejected)
            agg["wall_ms_total"] += out.wall_ms
            fam = agg["by_family"].setdefault(
                task.family, {"correct": 0, "tasks": 0, "steps": 0}
            )
            fam["correct"] += int(correct)
            fam["tasks"] += 1
            fam["steps"] += out.steps
        agg["accuracy"] = round(agg["tasks_correct"] / len(tasks), 4)
        agg["wall_ms_total"] = round(agg["wall_ms_total"], 2)
        results["strategies"][strategy] = agg

    print(json.dumps(results, indent=2))
    with open("results.json", "w") as fh:
        json.dump(results, fh, indent=2)


if __name__ == "__main__":
    main()
