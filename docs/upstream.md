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

## Selecting the upstream transport

```bash
resilientdns \
  --upstream-transport tcp \
  --upstream-host 1.1.1.1 \
  --upstream-port 53
```

Supported values are `udp` and `tcp`.

For safety, the default bind address is `127.0.0.1`.

## Relay Upstream (Planned)

ResilientDNS will support a relay upstream using a stateless JSON batch API.
See `docs/relay.md` for the protocol specification and endpoint conventions.

## Failure Semantics

UDP and TCP upstream share identical resolver behavior:

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
