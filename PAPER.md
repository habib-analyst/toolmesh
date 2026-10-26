# toolmesh: Conflict Resolution for Parallel Agent Tool Calls by Dry-Run Effect Simulation

Habib Ur Rehman — 2026

## Problem

Agent frameworks happily execute a plan's tool calls in parallel. Parallelism
is safe only when the calls do not interfere, and in practice they do: two
calls write the same resource (lost update), a call reads a resource another
call is writing (stale read), or a call executes that the agent had no
permission to make. Runtime locking fixes some of this after the fact, and
human preview/approval fixes it slowly. Neither inspects the whole plan
before execution.

## Method

Every tool in toolmesh declares, per call, an **effect set**: the resources
it will read and write. A plan is a list of calls addressed by *capability*
against a dynamic registry; each tool also declares required permission
scopes, and each agent carries granted scopes.

The `toolmesh` strategy processes a plan in three phases:

1. **Scope gate.** Calls whose tool requires scopes the agent lacks are
   denied and logged. They never execute.
2. **Dry-run simulation.** Each remaining call is executed once against a
   throwaway copy of the workspace; the actual written keys are diffed
   against the declared write set. A call that writes anything undeclared —
   or crashes in simulation — is rejected as unsafe.
3. **Conflict resolution.** Pairwise effect conflicts (write-write,
   write-read, read-write on a shared resource) are resolved by assigning
   calls to execution **waves**: a call enters the earliest wave strictly
   after every earlier call it conflicts with, preserving plan order. A call
   flagged `exclusive` that write-conflicts with another planned call is
   rejected (first writer wins, reason recorded). Within a wave, calls are
   conflict-free by construction, so batch execution (shared snapshot,
   buffered writes) is provably equivalent to sequential execution for that
   wave.

Two baselines share the same tools and plans: **naive parallel** (one batch
for the whole plan, no scope gate) and **sequential** (plan order, no scope
gate).

## Benchmark

A deterministic generator (seed 42) builds 150 tasks in five families of 30:
`clean` (disjoint keys), `write_write` (2–3 increments on one counter),
`write_read` (set → copy → increment chain), `scope_injection` (an
admin-scope delete planted in a plan run by a read/write agent), and
`exclusive` (two exclusive writes racing on one key). The intended final
state is computed by a reference executor with ordered, permission-filtered,
exclusive-first-wins semantics. Metrics: tasks whose final state matches the
intended state exactly, total execution steps (batches), and permission
violations (out-of-scope calls actually executed).

## Results (measured, this repo's `results.json`)

| Strategy | Correct | Accuracy | Steps | Violations |
|---|---|---|---|---|
| Naive parallel | 30/150 | 0.20 | 150 | 30 |
| Sequential | 90/150 | 0.60 | 558 | 30 |
| toolmesh | 150/150 | 1.00 | 257 | 0 |

Per family: naive parallel scores 0/30 on every conflicted family and 30/30
only on `clean`. Sequential scores 30/30 on `clean`, `write_write`, and
`write_read` but 0/30 on `scope_injection` (it executes the admin delete) and
0/30 on `exclusive` (last writer wins instead of first). toolmesh scores
30/30 on all five families, denying all 30 out-of-scope calls and rejecting
all 30 exclusive losers. On steps, toolmesh uses 257 vs sequential's 558
(−54%): it keeps single-wave parallelism on all 30 clean tasks (30 steps)
while paying serialization only where conflicts are planted (write_write:
77 steps for 30 tasks; write_read: 90 — a pure chain cannot parallelize).

## Honest limits

- **Declared effects are a contract, not a proof.** The dry run catches
  tools whose writes exceed their declaration *on the simulated state*; a
  tool whose write set depends on state in ways the simulation does not
  exercise could still misbehave. The simulation runs each call against the
  plan's *initial* state, not against every intermediate state.
- **The workspace is an in-memory key/value store.** Real tools hit APIs,
  files, and databases with latency, partial failure, and effects that
  cannot be diffed from a snapshot. The wave/batch model would need
  per-tool effect adapters and compensation for irreversible actions.
- **No LLM is in the loop.** Plans are generated synthetically; the
  benchmark measures the orchestration layer, not plan quality. Wall-clock
  times in `results.json` are for a tiny in-memory suite and are not a
  latency claim — the meaningful efficiency metric here is steps.
- **Exclusive rejection is first-wins.** Priority-aware or value-aware
  arbitration (e.g., keep the write from the higher-trust agent) is future
  work, as is merging compatible writes instead of serializing them.

## Reproduce

```bash
pip install -e .
python -m toolmesh.benchmark 30 42   # writes results.json
pytest                               # 12 tests, all passing
```
