# Security

## Internal mTLS

The local Docker stack uses Caddy sidecars as the internal TLS reverse proxy for
service-to-service HTTP and gRPC traffic. In compose, the sidecar shares the
application container network namespace, listens on `443`, and proxies to the
application on `127.0.0.1:<service-port>`.

### Naming

Services are addressed through Caddy with the internal DNS suffix:

- `data-ingestion.theeyebeta.internal`
- `snapshot-packager.theeyebeta.internal`
- `llm-gateway.theeyebeta.internal`
- `admin-service.theeyebeta.internal`
- `agent-runtime.theeyebeta.internal`
- `audit-service.theeyebeta.internal`
- `backtest-engine.theeyebeta.internal`
- `master-orchestrator.theeyebeta.internal`
- `oms.theeyebeta.internal`
- `rnd-agent.theeyebeta.internal`
- `broker-adapter-alpaca.theeyebeta.internal`
- `guard-service.theeyebeta.internal`
- `risk-service.theeyebeta.internal`
- `compliance-service.theeyebeta.internal`
- `guard-service-grpc.theeyebeta.internal`
- `risk-service-grpc.theeyebeta.internal`
- `compliance-service-grpc.theeyebeta.internal`

All inter-service URLs should use `https://<name>.theeyebeta.internal`.
For gRPC clients, use the `*-grpc.theeyebeta.internal:443` names and require TLS.

The current compose stack wires sidecars for the application services that are
defined in `docker-compose.yml`: `data-ingestion`, `snapshot-packager`,
`llm-gateway`, and `admin-service`. The Caddyfile already contains routes for
the remaining internal services so they can be attached with the same sidecar
pattern when those containers are added to compose.

### Certificates

Caddy is configured in [infra/caddy/Caddyfile](../infra/caddy/Caddyfile) with:

- Caddy internal CA `local`
- 12 hour leaf certificate lifetime
- 24 hour intermediate lifetime
- automatic renewal at 25% remaining lifetime
- client certificate verification with the `pki_root` trust pool

The Caddy data volume is mounted read-only into application containers at
`/caddy`. Each service gets these environment variables:

- `CADDY_TLS_CA_PATH`
- `CADDY_TLS_CERT_PATH`
- `CADDY_TLS_KEY_PATH`
- `SSL_CERT_FILE`

Services that make HTTP or gRPC calls must configure their client libraries to:

- trust `CADDY_TLS_CA_PATH`
- present `CADDY_TLS_CERT_PATH` and `CADDY_TLS_KEY_PATH` as the client certificate
- call only the `*.theeyebeta.internal` Caddy names

Python `httpx` clients should pass:

```python
verify=os.environ["CADDY_TLS_CA_PATH"],
cert=(
    os.environ["CADDY_TLS_CERT_PATH"],
    os.environ["CADDY_TLS_KEY_PATH"],
)
```

Python gRPC clients should use `grpc.ssl_channel_credentials` with the Caddy CA
and client certificate/key loaded from the same environment paths.

### Plaintext Policy

Caddy listens only on TLS for the internal service names and requires verified
client certificates. Plain HTTP requests to Caddy are refused because no HTTP
listener is configured for the internal names.

Container-local health checks may still use `localhost` plaintext inside the
same container. That is not inter-service traffic.

Direct container-to-container plaintext bypasses are refused for the compose
services wired with sidecars because the application process binds to
`127.0.0.1` and the published/container-routable port is Caddy's TLS listener.
For future services, preserve that pattern: bind the app to localhost, add a
Caddy sidecar with `network_mode: service:<service>`, and put the
`*.theeyebeta.internal` network alias on the application service.

### Verification

After the stack is running, verify TLS handshakes:

```sh
docker compose exec caddy-llm-gateway sh -lc "apk add --no-cache tcpdump >/dev/null && tcpdump -ni eth0 port 443"
```

Trigger a request from a service container to a Caddy internal name. The capture
should show TLS handshakes and encrypted application data.

Verify plaintext refusal through Caddy:

```sh
docker compose exec admin-service sh -lc "wget -S -O- http://llm-gateway.theeyebeta.internal/health"
```

The request should fail because Caddy does not serve plaintext HTTP for internal
service names.

Verify mTLS refusal without a client cert:

```sh
docker compose exec admin-service sh -lc "wget --ca-certificate=$CADDY_TLS_CA_PATH -S -O- https://llm-gateway.theeyebeta.internal/health"
```

The TLS connection should fail unless the client presents a certificate signed
by the Caddy internal CA.
