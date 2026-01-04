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
