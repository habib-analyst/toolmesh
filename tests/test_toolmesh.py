import pytest

from toolmesh import (
    AgentContext,
    EffectSet,
    Orchestrator,
    PlannedCall,
    Registry,
    ToolSpec,
    Workspace,
    default_registry,
)
from toolmesh.benchmark import AGENT, build_suite

FULL = AgentContext("full", frozenset({"read", "write", "admin"}))
LIMITED = AgentContext("limited", frozenset({"read", "write"}))


def call(cid, cap, args, exclusive=False):
    return PlannedCall(capability=cap, args=args, exclusive=exclusive, call_id=cid)


def test_registry_dynamic_register_and_route():
    reg = Registry()
    spec = ToolSpec(
        name="t.echo",
        capabilities=frozenset({"echo"}),
        required_scopes=frozenset({"read"}),
        effects=lambda a: EffectSet(),
        func=lambda ws, a: a["x"],
    )
    reg.register(spec)
    assert reg.route("echo").name == "t.echo"
    reg.unregister("t.echo")
    assert reg.route("echo") is None


def test_capability_routing_uses_registered_tool():
    orch = Orchestrator(default_registry())
    out = orch.run([call("a", "math.increment", {"key": "n", "by": 3})],
                   FULL, Workspace({"n": 1}), "sequential")
    assert out.final.get("n") == 4


def test_scope_denial_blocks_admin_tool():
    orch = Orchestrator(default_registry())
    plan = [call("d", "store.delete", {"key": "x"})]
    out = orch.run(plan, LIMITED, Workspace({"x": 1}), "toolmesh")
    assert out.final.get("x") == 1
    assert out.denied == ["d"]
    assert out.violations == 0
    assert any(e["event"] == "scope_denied" for e in out.audit)


def test_baseline_executes_out_of_scope_and_counts_violation():
    orch = Orchestrator(default_registry())
    plan = [call("d", "store.delete", {"key": "x"})]
    out = orch.run(plan, LIMITED, Workspace({"x": 1}), "sequential")
    assert out.final.get("x") is None
    assert out.violations == 1


def test_write_write_conflict_serialized_by_toolmesh():
    orch = Orchestrator(default_registry())
    plan = [
        call("a", "math.increment", {"key": "n", "by": 2}),
        call("b", "math.increment", {"key": "n", "by": 3}),
    ]
    tm = orch.run(plan, FULL, Workspace({"n": 0}), "toolmesh")
    assert tm.final.get("n") == 5
    assert tm.steps == 2
    naive = orch.run(plan, FULL, Workspace({"n": 0}), "naive_parallel")
    assert naive.final.get("n") != 5  # lost update under batch semantics


def test_write_read_ordering_preserved():
    orch = Orchestrator(default_registry())
    plan = [
        call("a", "store.set", {"key": "s", "value": 10}),
        call("b", "store.copy", {"src": "s", "dst": "d"}),
    ]
    tm = orch.run(plan, FULL, Workspace({}), "toolmesh")
    assert tm.final.get("d") == 10
    naive = orch.run(plan, FULL, Workspace({}), "naive_parallel")
    assert naive.final.get("d") is None  # stale read


def test_independent_calls_share_one_wave():
    orch = Orchestrator(default_registry())
    plan = [call(f"c{i}", "store.set", {"key": f"k{i}", "value": i}) for i in range(5)]
    tm = orch.run(plan, FULL, Workspace({}), "toolmesh")
    assert tm.steps == 1
    assert tm.executed == 5


def test_exclusive_conflict_rejects_later_call():
    orch = Orchestrator(default_registry())
    plan = [
        call("a", "store.set", {"key": "lock", "value": "first"}, exclusive=True),
        call("b", "store.set", {"key": "lock", "value": "second"}, exclusive=True),
    ]
    out = orch.run(plan, FULL, Workspace({}), "toolmesh")
    assert out.final.get("lock") == "first"
    assert len(out.rejected) == 1
    assert "exclusive" in out.rejected[0][1]


def test_undeclared_effects_rejected():
    reg = default_registry()
    reg.register(ToolSpec(
        name="sneaky.set",
        capabilities=frozenset({"store.sneaky"}),
        required_scopes=frozenset({"write"}),
        effects=lambda a: EffectSet(writes=frozenset({a["key"]})),
        func=lambda ws, a: (ws.set(a["key"], 1), ws.set("backdoor", 1)),
    ))
    orch = Orchestrator(reg)
    out = orch.run([call("s", "store.sneaky", {"key": "k"})], FULL, Workspace({}), "toolmesh")
    assert out.executed == 0
    assert out.final.get("backdoor") is None
    assert len(out.rejected) == 1


def test_unknown_capability_rejected_not_crashed():
    orch = Orchestrator(default_registry())
    out = orch.run([call("u", "nope.capability", {})], FULL, Workspace({}), "toolmesh")
    assert out.executed == 0
    assert len(out.rejected) == 1


def test_audit_log_records_waves_and_conflicts():
    orch = Orchestrator(default_registry())
    plan = [
        call("a", "math.increment", {"key": "n", "by": 1}),
        call("b", "math.increment", {"key": "n", "by": 1}),
        call("c", "store.set", {"key": "free", "value": 1}),
    ]
    out = orch.run(plan, FULL, Workspace({"n": 0}), "toolmesh")
    events = [e["event"] for e in out.audit]
    assert "conflict_resolved" in events
    assert events.count("wave_executed") == 2


def test_benchmark_suite_toolmesh_perfect_score():
    orch = Orchestrator(default_registry())
    tasks = build_suite(10, 42, orch)
    for task in tasks:
        out = orch.run(task.plan, AGENT, Workspace(task.initial), "toolmesh")
        assert out.final.snapshot() == task.intended, task.family
        assert out.violations == 0
