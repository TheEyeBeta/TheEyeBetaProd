# Alerting

## Delivery channels

Configure in admin-service `settings.py` / sops:

- `ALERT_TELEGRAM_BOT_TOKEN`
- `ALERT_TELEGRAM_CHAT_ID`
- `ALERT_EMAIL_TO` (optional SMTP)

## Grafana / Prometheus rules

| Alert | Severity | Condition |
|-------|----------|-----------|
| admin-service down | CRITICAL | health fail > 2 min |
| circuit breaker open | WARNING | open > 30 min |
| worker heartbeat stale | WARNING | 2× expected interval |
| audit chain stale | CRITICAL | last verify > 25 h |
| postgres connections | WARNING | > 80% max |
| NATS disconnected | CRITICAL | > 5 min |
| emergency halt active | CRITICAL | manual ack required |
| daily loss 80% | WARNING | approaching `max_daily_loss_usd` |
| daily loss 100% | CRITICAL | auto halt |

## Metrics source

Scrape `GET /metrics` on admin-service (:7200) when Prometheus middleware is deployed.
