# Operational Profiles

These profiles are opinionated starting points for common deployment shapes.
They are **deterministic, bounded, and fail-fast**: no retries, no upstream
fallback, and no unbounded queues.

Notes on names:
- CLI flags are shown as `--flag-name`.
- Settings labeled **Config key** correspond to `resilientdns.config.Config` fields
  (not exposed as CLI flags in v0.12.0). Use these when embedding or wrapping the
  server programmatically.

---

## Conservative / Home

**Intended environment:** single home gateway or small LAN, modest traffic, and
limited memory. Prioritizes safety and stability over throughput.

**Tradeoffs:** lower concurrency and smaller cache reduce memory and CPU, but may
increase cache misses during bursts.

### Recommended values

**Listener**
- `--listen-host 0.0.0.0`
- `--listen-port 53`

**Upstream (UDP)**
- `--upstream-transport udp`
- `--upstream-host 1.1.1.1`
- `--upstream-port 53`
- `--upstream-timeout 2.0`
- `--max-inflight 128` (fail-fast cap for concurrent client queries)
- **Config key:** `udp_max_workers = 16`

**Cache**
- **Config key:** `cache_max_entries = 10000`
- `--negative-ttl 60` (negative cache TTL)

**Serve-stale / SWR**
- `--serve-stale-max 300`
- `--refresh-enabled` **disabled** (omit the flag)

**Refresh knobs** (inactive while refresh is disabled)
- `--refresh-ahead-seconds 30`
- `--refresh-popularity-threshold 5`
- `--refresh-popularity-decay-seconds 0`
- `--refresh-tick-ms 500`
- `--refresh-batch-size 50`
- `--refresh-queue-max 1024`
- `--refresh-concurrency 5`

**Warmup knobs** (disabled)
- `--refresh-warmup-enabled` **disabled** (omit the flag)
- `--refresh-warmup-file ./warmup-home.txt`
- `--refresh-warmup-limit 200`

### Example command line

```bash
resilientdns \
  --listen-host 0.0.0.0 \
  --listen-port 53 \
  --upstream-transport udp \
  --upstream-host 1.1.1.1 \
  --upstream-port 53 \
  --upstream-timeout 2.0 \
  --max-inflight 128 \
  --serve-stale-max 300 \
  --negative-ttl 60
```

---

## High-throughput / Lab

**Intended environment:** lab, test rigs, or busy networks where throughput and
cache hit rate matter more than minimizing background work.

**Tradeoffs:** higher memory usage and more background refresh traffic in
exchange for lower latency and fewer cache misses.

### Recommended values

**Listener**
- `--listen-host 0.0.0.0`
- `--listen-port 5353`

**Upstream (UDP)**
- `--upstream-transport udp`
- `--upstream-host 1.1.1.1`
- `--upstream-port 53`
- `--upstream-timeout 1.5`
- `--max-inflight 1024` (fail-fast cap for concurrent client queries)
- **Config key:** `udp_max_workers = 64`

**Cache**
- **Config key:** `cache_max_entries = 200000`
- `--negative-ttl 30`

**Serve-stale / SWR**
- `--serve-stale-max 120`
- `--refresh-enabled`

**Refresh knobs**
- `--refresh-ahead-seconds 60`
- `--refresh-popularity-threshold 10`
- `--refresh-popularity-decay-seconds 300`
- `--refresh-tick-ms 250`
- `--refresh-batch-size 200`
- `--refresh-queue-max 4096`
- `--refresh-concurrency 20`

**Warmup knobs**
- `--refresh-warmup-enabled`
- `--refresh-warmup-file ./warmup-lab.txt`
- `--refresh-warmup-limit 1000`

### Example command line

```bash
resilientdns \
  --listen-host 0.0.0.0 \
  --listen-port 5353 \
  --upstream-transport udp \
  --upstream-host 1.1.1.1 \
  --upstream-port 53 \
  --upstream-timeout 1.5 \
  --max-inflight 1024 \
  --serve-stale-max 120 \
  --negative-ttl 30 \
  --refresh-enabled \
  --refresh-ahead-seconds 60 \
  --refresh-popularity-threshold 10 \
  --refresh-popularity-decay-seconds 300 \
  --refresh-tick-ms 250 \
  --refresh-batch-size 200 \
  --refresh-queue-max 4096 \
  --refresh-concurrency 20 \
  --refresh-warmup-enabled \
  --refresh-warmup-file ./warmup-lab.txt \
  --refresh-warmup-limit 1000
```

---

## Relay-heavy (Worker relay upstream)

**Intended environment:** networks where UDP/TCP upstream is unreliable or
blocked, but HTTPS to a Relay is stable. Uses the Relay transport explicitly.

**Tradeoffs:** Relay batching adds some latency, and very tight limits can reduce
throughput. Values below favor bounded load and steady behavior.

### Recommended values

**Listener**
- `--listen-host 0.0.0.0`
- `--listen-port 53`

**Upstream (Relay)**
- `--upstream-transport relay`
- `--relay-base-url https://relay.example.test`
- `--relay-api-version 1`
- `--relay-startup-check require`
- `--relay-auth-token relay-token` (if your relay requires auth)
- `--upstream-timeout 4.0`
- `--max-inflight 256` (fail-fast cap for concurrent client queries)

**Relay limits**
- `--relay-max-items 16`
- `--relay-max-request-bytes 32768`
- `--relay-per-item-max-wire-bytes 2048`
- `--relay-max-response-bytes 131072`

**Cache**
- **Config key:** `cache_max_entries = 50000`
- `--negative-ttl 60`

**Serve-stale / SWR**
- `--serve-stale-max 600`
- `--refresh-enabled`

**Refresh knobs**
- `--refresh-ahead-seconds 20`
- `--refresh-popularity-threshold 20`
- `--refresh-popularity-decay-seconds 600`
- `--refresh-tick-ms 1000`
- `--refresh-batch-size 20`
- `--refresh-queue-max 512`
- `--refresh-concurrency 4`

**Warmup knobs**
- `--refresh-warmup-enabled`
- `--refresh-warmup-file ./warmup-relay.txt`
- `--refresh-warmup-limit 200`

### Example command line

```bash
resilientdns \
  --listen-host 0.0.0.0 \
  --listen-port 53 \
  --upstream-transport relay \
  --relay-base-url https://relay.example.test \
  --relay-api-version 1 \
  --relay-startup-check require \
  --relay-auth-token relay-token \
  --upstream-timeout 4.0 \
  --max-inflight 256 \
  --serve-stale-max 600 \
  --negative-ttl 60 \
  --refresh-enabled \
  --refresh-ahead-seconds 20 \
  --refresh-popularity-threshold 20 \
  --refresh-popularity-decay-seconds 600 \
  --refresh-tick-ms 1000 \
  --refresh-batch-size 20 \
  --refresh-queue-max 512 \
  --refresh-concurrency 4 \
  --refresh-warmup-enabled \
  --refresh-warmup-file ./warmup-relay.txt \
  --refresh-warmup-limit 200 \
  --relay-max-items 16 \
  --relay-max-request-bytes 32768 \
  --relay-per-item-max-wire-bytes 2048 \
  --relay-max-response-bytes 131072
```

---

## Warmup file format (example)

Warmup files are plain text with `qname qtype` per line. Comments (`#`) and
blank lines are ignored.

```
# warmup example
example.com A
example.com AAAA
example.org MX
```
