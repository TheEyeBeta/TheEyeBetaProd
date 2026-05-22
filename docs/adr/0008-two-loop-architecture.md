# ADR 0008: Two-Loop Architecture (Executors and Explorers)

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §3.3](../architecture.md#33-the-two-loop-cycle), [ADR 0002](0002-nats-jetstream-over-kafka.md)

---

## Context

Algorithmic trading + research systems typically conflate two fundamentally different time-horizon concerns:

- **Execution concerns** (ms–s): React to live market data, generate signals, enforce risk limits, submit orders, receive fills. Latency is a first-class constraint. Errors are expensive.
- **Research concerns** (min–h): Explore hypotheses, backtest strategies, synthesise LLM-assisted proposals, update models. Throughput matters; latency does not. Errors are recoverable.

When these concerns share the same code paths and data pipelines, a slow research task can delay a time-sensitive execution decision, and an execution error can corrupt a long-running research computation.

Part 6.1 of the architecture document defines the separation.

---

## Decision

We will partition all services into two explicitly named loops:

**Fast Loop — Executors** (latency-sensitive, stateless per tick):
`data-ingestion → agent-runtime → guard-service → master-orchestrator → risk-service → oms → broker-adapter-alpaca`

**Slow Loop — Explorers** (throughput-oriented, long-running):
`snapshot-packager → backtest-engine → rnd-agent → llm-gateway → (proposal) → master-orchestrator`

`master-orchestrator` is the **only** bridge between loops. It accepts proposals from the slow loop and decides whether to route them to the fast loop for execution.

### Invariants

1. A slow-loop service **must never** block a fast-loop service. They communicate only via NATS (fire-and-forget from slow to fast) through master-orchestrator.
2. Fast-loop services **must not** call slow-loop services synchronously. Any feedback from fast→slow travels as an event (NATS subject `execution.report.*`).
3. `master-orchestrator` maintains the circuit-breaker state. If the fast loop is degraded, it rejects all incoming proposals from the slow loop until health recovers.

---

## Consequences

### Positive
- **Latency isolation**: A 60-second LLM call in rnd-agent never delays a guard-service signal validation.
- **Independent scaling**: Fast-loop services can be given dedicated CPU affinity; slow-loop services can be deprioritised during market hours.
- **Clear failure domains**: A crash in backtest-engine does not affect live trading. A crash in oms does not affect ongoing research.
- **Testability**: Each loop can be tested in isolation. The fast loop is fully testable with mock market data; the slow loop is testable with pre-recorded snapshots.
- **Reasoning clarity**: Developers immediately understand the latency expectation of any service from which loop it belongs to.

### Negative
- `master-orchestrator` becomes a coordination bottleneck and a critical path component. It must be highly available.
- Proposals from the slow loop have a propagation delay before they affect execution. This is intentional but must be clearly communicated to operators.
- The two-loop boundary (what goes in each loop) requires discipline to maintain as the system evolves. Adding a "quick research" feature risks blurring the separation.

### Neutral
- `admin-service`, `compliance-service`, and `audit-service` are outside both loops — they observe and record but do not participate in signal or proposal flow.
- The NATS subject namespace enforces the boundary: `market.*`, `signal.*`, `order.*` are fast-loop subjects; `research.*`, `backtest.*`, `proposal.*` are slow-loop subjects.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **Single unified pipeline** | Research tasks pollute the execution latency path; one slow LLM call delays all downstream signals |
| **Separate processes per concern, no shared broker** | Loses the ability to replay events; complicates the master-orchestrator coordination role |
| **Event sourcing with a single log (Kafka/Redpanda)** | Heavier infrastructure; the two-loop boundary is better expressed at the service level than at the topic level |
| **Microservices with synchronous HTTP only** | Request/reply pattern forces fast-loop services to wait for slow-loop responses; no durable replay |

---

## References

- [docs/architecture.md §3.3 — The Two-Loop Cycle](../architecture.md#33-the-two-loop-cycle)
- [README.md — Two-Loop Architecture diagram](../../README.md#the-two-loop-architecture)
- [ADR 0002 — NATS JetStream](0002-nats-jetstream-over-kafka.md)
