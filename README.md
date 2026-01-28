# ResilientDNS

**ResilientDNS** is an open-source DNS cache and forwarder designed for
**unreliable, high-latency, and low-quality network environments**.

It aims to provide correct, resilient DNS resolution for local networks
while minimizing upstream dependencies and unnecessary HTTPS traffic.

Docs: https://amirpooyan-r.github.io/resilient-dns/

---

## Motivation

In some regions and network conditions, DNS resolution is unreliable due to:

- Packet loss and unstable UDP/TCP DNS
- DNS hijacking or tampering
- Intermittent or degraded HTTPS connectivity
- Partial or unreliable HTTP/2 support
- Legacy devices (routers, TVs, IoT, embedded systems) that do not support DNS-over-HTTPS (DoH)

While DoH improves security and integrity, many environments cannot rely on
stable or efficient HTTPS connections, and aggressive prefetching can make
things worse on slow links.

**ResilientDNS** focuses on *practical resilience* rather than ideal conditions.

---

## Project Goals

ResilientDNS is designed to:

- Accept **standard DNS** queries from LAN devices (UDP today; TCP planned)
- Provide a **smart local DNS cache**
  - TTL-aware positive caching
  - Negative caching (NXDOMAIN / NODATA)
  - Serve-stale behavior for resilience
- Reduce upstream dependency using:
  - Controlled, budgeted prefetch
  - Request deduplication
  - Batched upstream resolution
- Work reliably over **HTTP/1.1**
  - No hard dependency on HTTP/2
- Remain protocol-correct and transparent to clients

---

## Key Behaviors (Implemented)

- TTL-aware caching
- Negative caching (NXDOMAIN / NODATA)
- Serve-stale support
- Stale-while-revalidate (SWR)
- SingleFlight deduplication (misses + refresh)
- Lightweight in-process metrics counters

## Batch Refresh (v0.10.0)

Batch refresh is a **best-effort** background scheduler that keeps hot cache
entries fresh without blocking foreground queries. It uses a **bounded queue**,
fixed concurrency, and deduplication. Scanning is deterministic (no jitter),
and refresh work never changes foreground query semantics.

Key properties:
- Best-effort (no retries, no fallback)
- Bounded queue + fixed worker count
- Dedupe via queued/inflight tracking
- Deterministic scanning
- Never blocks foreground cache hits
- Popularity uses cache-hit counts (fresh or stale-served), resets on replace/evict, capped
- Optional recency window via decay seconds
- Refresh outcomes: success (updated), fail (attempted but failed), skipped (no attempt)

Configuration (defaults shown):

```bash
resilientdns \
  --refresh-enabled \
  --refresh-ahead-seconds 30 \
  --refresh-popularity-threshold 5 \
  --refresh-popularity-decay-seconds 0 \
  --refresh-tick-ms 500 \
  --refresh-batch-size 50 \
  --refresh-concurrency 5 \
  --refresh-queue-max 1024
```

### Warmup List (v0.11.0)

Warmup is a best-effort startup preload of refresh jobs from a text file.
It respects the bounded queue and dedupe rules; extra entries are dropped
once the queue is full. No retries or fallback are added.

Format (one per line):

```
# comments allowed
example.com A
example.net AAAA
```

Config (defaults shown):

```bash
resilientdns \
  --refresh-warmup-enabled \
  --refresh-warmup-file ./warmup.txt \
  --refresh-warmup-limit 200
```

## Operational Profiles (v0.12.0)

For recommended settings and rationale, see `docs/profiles.md`.

```bash
# Conservative / Home
resilientdns --listen-host 0.0.0.0 --listen-port 53 --upstream-transport udp --upstream-timeout 2.0 --max-inflight 128

# High-throughput / Lab
resilientdns --listen-host 0.0.0.0 --listen-port 5353 --upstream-transport udp --upstream-timeout 1.5 --max-inflight 1024 --refresh-enabled

# Relay-heavy
resilientdns --listen-host 0.0.0.0 --listen-port 53 --upstream-transport relay --relay-base-url https://relay.example.test --upstream-timeout 4.0 --max-inflight 256
```

## Upstream behavior

- Supports UDP and TCP upstream forwarding (explicit selection, no guessing)
- CLI flag: `--upstream-transport` `udp|tcp` (default: `udp`)
- TCP upstream uses safe connection reuse (pool) with one in-flight per connection (no pipelining)
- Upstream concurrency limits (`max_inflight`) are fail-fast (no queuing)
- No automatic UDP↔TCP fallback and no retry storms
- Failures preserve serve-stale / SWR semantics

```bash
resilientdns \
  --upstream-transport tcp \
  --upstream-host 1.1.1.1 \
  --upstream-port 53
```

## Configuration

- `max_entries`: Maximum cache entries (0 = unlimited)
- Eviction happens on insert (put), to keep the read path fast
- Eviction order: fully expired entries first, then LRU

### Metrics

- `cache_entries`: Current number of cache entries (gauge)
- `evictions_total`: Entries evicted due to capacity enforcement

## Observability

ResilientDNS exposes a read-only metrics HTTP endpoint. Metrics are deterministic and low overhead.

- Endpoints: `/metrics`, `/healthz`, `/readyz`, `/cache/stats`
- Drops are distinct from upstream errors
- Metrics semantics are documented
- `docs/observability.md`
- `docs/upstream.md`

```bash
resilientdns \
  --metrics-host 127.0.0.1 \
  --metrics-port 9100
```

---

## Quickstart (Local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]  # or: pip install -e .
```

Run the server:

```bash
resilientdns --listen-port 5353
```

Test a query:

```bash
dig @127.0.0.1 -p 5353 example.com A
```

---

## Non-Goals

This project explicitly does **not** aim to:

- Circumvent censorship or filtering
- Provide anonymity or traffic obfuscation
- Break DNS protocol behavior on the LAN side
- Act as a VPN, proxy, or tunneling solution
- Enable illegal or unethical use cases

ResilientDNS focuses on **reliability, correctness, and performance**.

---

## High-Level Architecture

```text
LAN Devices
|
| Standard DNS (UDP / TCP)
v
ResilientDNS (Python)
|
| HTTPS (batched, HTTP/1.1 friendly)
v
Remote Relay
|
| DoH
v
Upstream DNS Resolver
```

- LAN devices remain completely unaware of DoH
- Upstream communication is controlled, batched, and minimized
- Serve-stale behavior allows continued operation during outages

---

## Relay Upstream

ResilientDNS supports a **Relay upstream** as an explicit upstream transport option.
A Relay is a remote HTTP batch DNS
resolver belonging to the ResilientDNS project. Relays may be:

- Serverless (e.g., Cloudflare Worker)
- Self-hosted (Docker, VM, VPN, etc.)

The Relay protocol is defined in `docs/relay.md`. Relay implementations may
live in separate repositories.

Relay startup validation uses `GET /v1/info` and supports require/warn/off
modes for explicit failure handling.

“The Relay is a logical component of ResilientDNS and is not a network gateway, router, NAT, or VPN device.”
---

## Project Status

🚧 **Early development / MVP phase**

This repository is under active development and is intended as:

- A learning and research project
- A production-quality engineering portfolio
- A foundation for experimenting with resilient DNS designs

Interfaces, internals, and layouts may evolve as the project matures.

---

## Repository Structure (Current and Planned)

The repository is structured to remain **clean, scalable, and multi-language friendly**:

```text
resilient-dns/
├─ src/
│  └─ resilientdns/                # Python LAN DNS resolver (core product)
│
├─ tests/                          # Unit and integration tests
│  └─ fake_relay/                  # Test-only Relay implementation used by contract tests
│
├─ docs/                           # Architecture, design notes, documentation
│
├─ tools/                          # Client-side utilities and diagnostics
│  ├─ dns-check/                   # DNS testing and validation tools
│  ├─ trace/                       # Resolution tracing and debugging tools
│  └─ benchmark/                   # Performance and latency benchmarks
│
└─ infra/                          # Optional infrastructure and automation
   ├─ docker/                      # Containerization assets
   └─ github-actions/              # CI/CD workflows
```

This layout intentionally separates:
- **Core resolver logic**
- **Relay protocol specification and test harnesses**
- **Supporting tools**
- **Infrastructure concerns**

---

## License

This project is licensed under the **Apache License 2.0**.

See the `LICENSE` file for details.
