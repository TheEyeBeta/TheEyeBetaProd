# Observability Operations

TheEyeBeta uses Prometheus for service metrics and blackbox health probes,
Alertmanager for alert routing, and Grafana dashboards under
`infra/grafana/dashboards`.

## Prometheus Files

- Scrape config: `infra/prometheus/prometheus.yml`
- Alert rules: `infra/prometheus/alerts.yml`
- Blackbox probes: `infra/prometheus/blackbox.yml`
- Main dashboard: `infra/grafana/dashboards/observability.json`

Prometheus runs in Docker with host networking because the trading services are
host systemd units bound to `127.0.0.1`. Blackbox-exporter remains on the Docker
bridge network and uses `host.docker.internal` for HTTP health probes.

## Service Metrics

The critical order-flow services expose `GET /metrics`:

| Service | Port | Metrics job |
| --- | ---: | --- |
| `risk-service` | 8007 | `theeye-risk-service` |
| `compliance-service` | 8008 | `theeye-compliance-service` |
| `master-orchestrator` | 7050 | `theeye-master-orchestrator` |
| `oms` | 7080 | `theeye-oms` |
| `broker-adapter-alpaca` | 7090 | `theeye-broker-adapter-alpaca` |

Every service emits:

- `theeye_http_request_count_total{service,method,path,status}`
- `theeye_http_request_latency_seconds_bucket{service,method,path,le}`
- `theeye_http_request_errors_total{service,method,path}`
- `theeye_queue_depth{service}`
- `theeye_service_info{service}`

## Validation

Run these checks after changing Prometheus configuration:

```bash
promtool check rules infra/prometheus/alerts.yml
tmp="$(mktemp)"
sed "s#/etc/prometheus/alerts.yml#$(pwd)/infra/prometheus/alerts.yml#" \
  infra/prometheus/prometheus.yml > "$tmp"
promtool check config "$tmp"
rm -f "$tmp"
```

The temporary config keeps the committed container mount path intact while
letting local `promtool` find the rule file.

## Alerts

Current rules cover:

- `ServiceHealthProbeDown`: blackbox `/health` probe failed for more than 2 minutes.
- `CriticalServiceMetricsMissing`: OMS, broker, or master-orchestrator stopped
  emitting metrics for more than 2 minutes.
- `HighErrorRate`: service 5xx rate is above 5% for 5 minutes.
- `OrderFlowLatencyHigh`: p95 latency above 2 seconds for the order-flow services.
- `QueueDepthHigh`: OMS, broker, or master-orchestrator has more than 25 in-flight handlers.
- `AuditChainBroken`: audit hash-chain verification probe failed.

## Dashboard

Open Grafana and select **TheEyeBeta Observability**. It shows:

- Service health in one view.
- Order-flow p95 latency.
- Audit chain verification status.
- Stale worker heartbeat count from `theeyebeta.worker_heartbeats`.
- Queue depth and service error rate.

## Manual Alert Test

To test Alertmanager routing without stopping a trading service, post a synthetic
alert directly:

```bash
starts_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ends_at="$(date -u -d '+5 minutes' +%Y-%m-%dT%H:%M:%SZ)"
curl -sS -XPOST http://127.0.0.1:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d "[{
    \"labels\": {
      \"alertname\": \"ManualObservabilityTest\",
      \"severity\": \"warning\",
      \"service\": \"observability\"
    },
    \"annotations\": {
      \"summary\": \"Manual observability alert test\"
    },
    \"startsAt\": \"$starts_at\",
    \"endsAt\": \"$ends_at\"
  }]"

curl -sS http://127.0.0.1:9093/api/v2/alerts | jq \
  '.[] | select(.labels.alertname == "ManualObservabilityTest")'
```

For a rule-path test, stop a non-production replica of OMS, broker, or
master-orchestrator and wait more than 2 minutes. The
`CriticalServiceMetricsMissing` rule should enter firing state once Prometheus
records `up == 0`.
