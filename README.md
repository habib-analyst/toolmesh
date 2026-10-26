# toolmesh

**Parallel tool calls are where agents corrupt state.** When a plan fires
several tool calls at once, two of them write the same resource, a reader sees
a stale snapshot, or a call the agent was never permitted to make slips in.
toolmesh is a multi-tool orchestrator that fixes this *before anything runs*:
it **simulates the plan's declared effects (a dry run)**, resolves conflicts
by ordering, serializing, or rejecting with a reason, enforces permission
scopes, and only then executes — in parallel wherever the simulation proves
it safe.

## What it does

- **Dynamic tool registry** — tools register at runtime with the capabilities
  they offer; unregistering removes them from routing immediately.
- **Capability-based routing** — plans name capabilities (`math.increment`),
  not tools; the router resolves each call to a registered tool.
- **Permission scoping** — every tool declares required scopes, every agent
  carries granted scopes. Out-of-scope calls are **denied and logged** before
  execution, never executed.
- **Dry-run effect simulation** — each tool declares its read/write effect
  set. The resolver first runs every call against a throwaway copy of the
  workspace and rejects any call whose *actual* writes exceed its
  *declared* writes.
- **Conflict resolution** — write-write and write-read conflicts between
  planned calls are resolved by serializing them into ordered execution
  waves (plan order preserved); calls in the same wave are conflict-free by
  construction and run in parallel. A call flagged `exclusive` that
  write-conflicts with another planned call is **rejected with a reason**
  (first writer wins).
- **Audit log** — every denial, rejection, detected conflict, and executed
  wave is recorded.

## Measured results

Synthetic workflow suite: 150 tasks (30 each of clean, write-write conflict,
write-read chain, scope injection, exclusive race), deterministic seed 42.
"Correct" = final workspace exactly equals the intended state (ordered,
permission-filtered, exclusive first-wins reference). Steps = execution
batches (lower = more parallelism).

| Strategy | Correct | Accuracy | Steps | Permission violations |
|---|---|---|---|---|
| Naive parallel (all at once) | 30/150 | 0.20 | 150 | 30 |
| Sequential (plan order, no scopes) | 90/150 | 0.60 | 558 | 30 |
| **toolmesh** | **150/150** | **1.00** | **257** | **0** |

Per family, naive parallel fails *every* conflicted task (lost updates on
write-write, stale reads on write-read, executed admin deletes, lost
exclusive races). Sequential is correct wherever order alone is enough but
still executes out-of-scope calls and loses exclusive races. toolmesh denied
all 30 out-of-scope calls and rejected all 30 exclusive losers, at 257 steps:
54% fewer steps than sequential, while keeping full parallelism on
conflict-free plans (30 steps for 30 clean tasks — one wave each).

Full numbers: `results.json`. Method and honest limits: `PAPER.md`.

## Quick start

```bash
pip install -e .
python -m toolmesh.benchmark   # regenerates results.json
pytest                         # 12 tests
```

```python
from toolmesh import AgentContext, Orchestrator, PlannedCall, Workspace, default_registry

orch = Orchestrator(default_registry())
agent = AgentContext("agent-1", frozenset({"read", "write"}))
plan = [
    PlannedCall("math.increment", {"key": "n", "by": 2}, call_id="a"),
    PlannedCall("math.increment", {"key": "n", "by": 3}, call_id="b"),
]
out = orch.run(plan, agent, Workspace({"n": 0}), strategy="toolmesh")
assert out.final.get("n") == 5   # serialized by the resolver, not lost
```

## Layout

- `src/toolmesh/model.py` — effect sets, planned calls, tool specs
- `src/toolmesh/registry.py` — dynamic registry + capability routing
- `src/toolmesh/scopes.py` — agent permission scopes
- `src/toolmesh/resolver.py` — dry-run simulation + conflict resolution
- `src/toolmesh/orchestrator.py` — the three execution strategies + audit log
- `src/toolmesh/benchmark.py` — the measured suite above

## License

MIT — Habib Ur Rehman
