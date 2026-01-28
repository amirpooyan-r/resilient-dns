# Upstream Transport

## Introduction

ResilientDNS forwards queries upstream using an explicitly selected transport.
The choice is deterministic and never inferred automatically.

## Supported Transports

### UDP (default)

- Low overhead and simple setup
- Susceptible to packet loss in unstable networks
- Large responses may be truncated

### TCP

- Reliable delivery for upstream queries
- Handles large responses without truncation
- Works in networks where UDP is filtered
- Uses RFC 7766 DNS-over-TCP framing

### Relay

- HTTPS batch transport (HTTP/1.1 friendly)
- Designed for unreliable or high-latency links
- Requires explicit Relay configuration and startup check (optional)

## Selecting the upstream transport

```bash
resilientdns \
  --upstream-transport tcp \
  --upstream-host 1.1.1.1 \
  --upstream-port 53
```

Supported values are `udp`, `tcp`, and `relay`.

For safety, the default bind address is `127.0.0.1`.

## Relay Upstream

Relay upstream uses a stateless JSON batch API. It is always explicit and never
selected automatically.

```bash
resilientdns \
  --upstream-transport relay \
  --relay-base-url https://relay.example.test \
  --relay-api-version 1
```

See `docs/relay.md` for the protocol specification and endpoint conventions.

## Failure Semantics

All upstream transports share identical resolver behavior:

- Strict timeouts
- No retries or fallback loops
- Serve-stale and SWR preserved
- Failures handled identically

## Design Principles

- Explicit transport selection
- No protocol guessing
- Correctness over throughput
- Failure visibility via metrics

## Non-Goals

- Automatic UDP → TCP fallback
- DoT / DoH
- Persistent TCP pooling
