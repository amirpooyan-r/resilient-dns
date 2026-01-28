# Operations

This page covers production-oriented setup checks, common troubleshooting, and
known-good launch commands.

## Production checklist

### Listen host/port

- `--listen-host` defaults to `127.0.0.1` (local only). Use `0.0.0.0` for LAN
  access and restrict at the network boundary.
- `--listen-port 53` is standard but requires elevated privileges on many
  systems. Use a high port (e.g., 5353) if you cannot bind to 53.

### Upstream selection and timeout

- Choose explicitly with `--upstream-transport udp|tcp|relay`.
- UDP/TCP are direct and unbatched. Relay uses HTTPS batching and requires
  `--relay-base-url` and `--relay-api-version`.
- Timeouts are strict; there are no retries or automatic fallback:
  - LAN or nearby resolvers: `--upstream-timeout 1.0` to `2.0`
  - Relay over the public Internet: `--upstream-timeout 3.0` to `5.0`

### `max_inflight` sizing (fail-fast)

- `--max-inflight` caps concurrent client queries and fails fast when exceeded.
- Start conservatively (128–256) for home, higher (512–1024) for lab throughput.
- If you see drops or SERVFAIL during bursts, raise `--max-inflight` or reduce
  incoming load.

### Metrics exposure safety

- Metrics are disabled by default (`--metrics-port 0`).
- If enabled, bind to localhost or a trusted management network:
  `--metrics-host 127.0.0.1 --metrics-port 9100`.
- The endpoint is read-only and unauthenticated; do not expose it publicly.

### Refresh and warmup safe defaults

- Refresh is **off** by default. Enable it only when you can afford background
  traffic and want steadier cache freshness: `--refresh-enabled`.
- Safe starter knobs: `--refresh-ahead-seconds 30`,
  `--refresh-popularity-threshold 5`, `--refresh-batch-size 50`.
- Refresh requires at least one worker when enabled:
  `--refresh-concurrency >= 1`.
- Warmup is best-effort and bounded; it only does work if refresh is enabled.
  Use a small file and a modest limit:
  `--refresh-warmup-enabled --refresh-warmup-file ./warmup.txt --refresh-warmup-limit 200`.

## Troubleshooting

### SERVFAIL spikes

Likely causes:
- Upstream timeouts: increase `--upstream-timeout` slightly or validate upstream reachability.
- Fail-fast cap too low: raise `--max-inflight` for bursty workloads.

What to check:
- Metrics counters for upstream failures (if metrics are enabled)
- Logs for `UPSTREAM TIMEOUT` or `UPSTREAM ERROR`

### Cache not refreshing

Likely causes:
- `--refresh-enabled` not set (refresh is off by default).
- `--refresh-popularity-threshold` too high for your traffic profile.
- `--refresh-popularity-decay-seconds` too small, expiring popularity too quickly.
- `--refresh-ahead-seconds` too small to catch entries before expiry.

### Warmup didn’t do anything

Likely causes:
- Refresh is disabled (warmup requires `--refresh-enabled`).
- Warmup queue is full (`--refresh-queue-max` too small for the file size).
- Duplicate entries in the warmup file are dropped by dedupe logic.

### Relay startup check failures

Modes:
- `--relay-startup-check require`: fail fast on any startup check error.
- `--relay-startup-check warn`: log a warning and continue.
- `--relay-startup-check off`: skip the startup check.

Common causes:
- Relay unreachable or timeout (`/info` not reachable within `--upstream-timeout`).
- Authentication missing/invalid (`--relay-auth-token`).
- API version mismatch (`--relay-api-version`).
- Relay limits incompatible with client limits (`--relay-max-*` flags).

## Known-good commands

See [Operational Profiles](profiles.md) for complete settings and rationale.

```bash
# Conservative / Home
resilientdns --listen-host 0.0.0.0 --listen-port 53 --upstream-transport udp --upstream-timeout 2.0 --max-inflight 128

# High-throughput / Lab
resilientdns --listen-host 0.0.0.0 --listen-port 5353 --upstream-transport udp --upstream-timeout 1.5 --max-inflight 1024 --refresh-enabled

# Relay-heavy
resilientdns --listen-host 0.0.0.0 --listen-port 53 --upstream-transport relay --relay-base-url https://relay.example.test --upstream-timeout 4.0 --max-inflight 256
```
