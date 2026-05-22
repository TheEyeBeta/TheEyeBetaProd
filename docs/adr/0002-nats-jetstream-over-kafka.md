# ADR 0002: NATS JetStream over Kafka as the Messaging Backbone

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §3.2](../architecture.md#32-communication-patterns)

---

## Context

theeyebeta requires asynchronous messaging for three distinct patterns:

1. **Ephemeral pub/sub** — live market tick fan-out to multiple consumers (agent-runtime, snapshot-packager). Fire-and-forget; late consumers miss old messages by design.
2. **Durable at-least-once queues** — backtest job dispatch, order events, research proposal submission. Messages must survive restarts and be acknowledged.
3. **Request/reply** — low-latency synchronous-style calls between services where HTTP would add unnecessary overhead (e.g. guard-service signal approval).

The system runs on a single Mac mini. Operational simplicity is a hard constraint.

---

## Decision

We will use **NATS 2 with JetStream** for all messaging.

- Core NATS for ephemeral pub/sub (market ticks, real-time status).
- JetStream for durable consumers, exactly-once delivery semantics, and replay.
- NATS request/reply (built-in) for synchronous-style inter-service calls.

Python client: `nats-py` (asyncio-native).

---

## Consequences

### Positive
- Single binary (~20 MB), single port (4222), HTTP monitoring at 8222.
- JetStream provides Kafka-like durability (subjects, consumers, ACKs, replay) without Kafka's operational footprint (ZooKeeper/KRaft, brokers, topic partitions, consumer group rebalancing).
- Core NATS request/reply replaces a full HTTP round-trip for internal RPC with sub-millisecond overhead.
- Built-in monitoring endpoint (`/jsz`, `/connz`, `/varz`) integrates directly with Prometheus via otel-collector.
- JetStream stores data in `/data` volume — trivially backed up alongside Postgres.

### Negative
- No schema registry. We must enforce message schemas via Pydantic at publish and subscribe points — discipline not tooling.
- No Kafka-style consumer group rebalancing UI (Kafka UI, Redpanda Console). Monitoring is curl-based.
- NATS JetStream is less battle-tested than Kafka at very high throughputs (> 1 M msg/s). We do not approach that scale.
- Single-node JetStream: no replication. Planned mitigation: JetStream cluster on replica Mac mini (future).

### Neutral
- NATS subjects are dot-separated strings (`market.tick.AAPL`, `orders.filled.*`). Wildcard subscriptions (`market.tick.>`) are powerful but require naming discipline.

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **Apache Kafka** | Requires ZooKeeper or KRaft; 3-broker minimum for HA; JVM heap; > 1 GB RAM overhead; no request/reply primitive |
| **RabbitMQ** | AMQP complexity; weaker time-series replay story; fewer modern async Python clients |
| **Redis Streams** | Redis is already in the stack for cache; mixing cache and durable messaging into one process creates single-point-of-failure for both workloads |
| **AWS SQS/SNS** | Cloud-vendor dependency; cannot run locally without LocalStack |
| **gRPC streaming** | Peer-to-peer; no fan-out; requires service discovery; high boilerplate |

---

## References

- [NATS JetStream documentation](https://docs.nats.io/nats-concepts/jetstream)
- [nats-py async client](https://github.com/nats-io/nats.py)
- [docker-compose.yml — nats service](../../docker-compose.yml)
