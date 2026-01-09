# Observability

ResilientDNS follows a logs-first approach: logs capture behavior, and metrics
provide low-overhead trend visibility.

## Metrics HTTP Endpoint

The metrics endpoint is a small, dependency-free HTTP server that exposes
read-only counters for operational insight.

For safety, the default bind address is `127.0.0.1`.

### Enabling the endpoint

```bash
resilientdns \
  --metrics-host 127.0.0.1 \
  --metrics-port 9100
```

### Endpoints

- GET `/metrics`: plain text lines of `name value`, sorted by name
- GET `/healthz`: returns `ok`
- GET `/readyz`: returns `ok` when ready; otherwise 503
- GET `/cache/stats`: JSON cache statistics
- Any other path: 404 not found

Example response:

```text
cache_entries 42
evictions_total 3
```

### Metrics Semantics

| Metric | Meaning |
| --- | --- |
| `cache_entries` | Current cache size (gauge). |
| `evictions_total` | Entries evicted due to capacity enforcement. |
| `dropped_total` | Packets or responses dropped due to capacity/size limits. |
| `malformed_total` | Malformed DNS packets observed. |

## Upstream Metrics Semantics

- `upstream_requests_total`: number of actual upstream attempts (after inflight admission).
- `dropped_total`: requests dropped due to policy or saturation (e.g. `max_inflight`, oversize responses). Drops are not upstream failures.
- `upstream_udp_errors_total`: UDP upstream failures (timeouts or exceptions after an attempt was made).
- `upstream_tcp_errors_total`: TCP upstream failures (connect, read/write errors, protocol violations, oversize drops).
- `upstream_tcp_reuses_total`: number of times an existing TCP upstream connection was reused from the pool.
- `upstream_relay_requests_total`: relay upstream HTTP requests.
- `upstream_relay_http_4xx_total`: relay HTTP 4xx responses.
- `upstream_relay_http_5xx_total`: relay HTTP 5xx responses.
- `upstream_relay_timeouts_total`: relay timeouts.
- `upstream_relay_client_errors_total`: relay HTTP client/transport/request failures (connect/timeouts/TLS/non-2xx/decode failures/etc.).
- `upstream_relay_protocol_errors_total`: relay response shape/contract violations after a successful HTTP exchange and JSON decoding.

Client errors reflect transport-side failures before a valid Relay response is
received (including non-2xx or decode failures). Protocol errors indicate the
Relay responded with 200 and valid JSON, but the response was invalid or
incompatible.

A request can be dropped without being an upstream error. Errors imply an upstream attempt was made.

## Reasoned Drop and Error Metrics

These counters are additive and do not replace existing totals.

- `dropped_max_inflight_total`: drops due to admission limits.
- `dropped_oversize_total`: drops due to oversize requests or responses.
- `dropped_malformed_total`: drops due to malformed DNS packets.
- `dropped_policy_total`: drops due to other policy enforcement.
- `upstream_udp_timeouts_total`: UDP upstream timeouts.
- `upstream_tcp_timeouts_total`: TCP upstream timeouts.
- `upstream_tcp_connect_errors_total`: TCP connection failures.
- `upstream_tcp_protocol_errors_total`: TCP read/write/protocol errors and oversize protocol drops.

## Tuning Guidance

- Set `max_inflight` to protect upstreams under burst load and to bound concurrent work.
- A high `dropped_total` with low `*_errors_total` usually indicates admission policy pressure, not upstream instability.
- A high `*_errors_total` indicates upstream failures after an attempt was made and should be investigated separately.
- Use `upstream_tcp_reuses_total` to evaluate TCP pool effectiveness; higher reuse generally means fewer connects.
- Start with small limits and tune explicitly for unreliable networks to keep failure modes predictable.

## Readiness vs Liveness

- `/healthz` is liveness only and returns 200 if the process is running.
- `/readyz` is readiness and returns 200 only after DNS listeners and the metrics server are ready.

## Additional Metrics

- `resilientdns_build_info{version="<package_version>"}`: constant build label for the running version.
- `resilientdns_uptime_seconds`: process uptime in seconds (monotonic).

## Cache Clear (SIGHUP)

- Sending `SIGHUP` clears the in-memory cache without stopping the server.
- An INFO log line is emitted on clear.
- `cache_clears_total` increments on each clear.

### Design Principles

- Read-only endpoint
- Fail-safe behavior (errors drop requests without side effects)
- Low overhead
- Deterministic output ordering
- Explicit enablement

### Operational Notes

- Bind to `127.0.0.1` by default
- Consider firewall rules when exposing externally
- Use a local scraper or sidecar to collect metrics
