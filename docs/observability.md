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
- Any other path: 404

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

A request can be dropped without being an upstream error. Errors imply an upstream attempt was made.

## Tuning Guidance

- Set `max_inflight` to protect upstreams under burst load and to bound concurrent work.
- A high `dropped_total` with low `*_errors_total` usually indicates admission policy pressure, not upstream instability.
- A high `*_errors_total` indicates upstream failures after an attempt was made and should be investigated separately.
- Use `upstream_tcp_reuses_total` to evaluate TCP pool effectiveness; higher reuse generally means fewer connects.
- Start with small limits and tune explicitly for unreliable networks to keep failure modes predictable.

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
