# ResilientDNS Roadmap

This roadmap reflects planned technical direction, not guarantees. No dates are
promised. Features are marked completed only when released. Stability and
correctness take priority over feature count.

Legend:
- ⬜ Planned
- 🟡 In progress
- ✅ Completed
- ❌ Dropped (with explanation)

## Core DNS Engine

- ✅ Deterministic UDP DNS server
- ✅ TTL-aware positive caching
- ✅ TTL-aware negative caching
- ✅ Serve-stale (stale-if-error)
- ✅ Stale-while-revalidate (SWR)
- ✅ Single-flight cache miss deduplication
- ✅ Strict upstream timeout enforcement
- ✅ Cache warm-up / preload (static domain list)
- ⬜ Cache namespace isolation (per-view or subnet)

## Upstream & Relay Support

- ✅ Explicit UDP or TCP upstream selection
- ✅ Deterministic upstream concurrency limits (fail-fast)
- ✅ TCP upstream connection pooling with idle eviction
- ✅ Relay client (HTTP batch DNS)
- ✅ Relay startup validation (/v1/info)
- ✅ Relay limits compatibility checks
- ⬜ Multi-relay support (explicit policy, no auto-fallback)

## Observability & Diagnostics

- ✅ Prometheus-style metrics endpoint
- ✅ Clear drop vs error metric semantics
- ✅ Health check endpoint (/healthz)
- ✅ Readiness endpoint (/readyz)
- ⬜ Startup configuration sanity report
- ⬜ Diagnostics bundle export (config + counters)

## Web UI (Admin Dashboard)

- ⬜ Read-only dashboard (status, cache, upstream, relay)
- ⬜ Cache hit/miss and eviction visualization
- ⬜ Manual cache clear action
- ⬜ Relay preflight test trigger
- ⬜ Restart-required configuration editor

UI is optional. Default bind is localhost. Designed for home and small-office
users.

## Tooling & Testing

- ✅ Deterministic pytest suite
- ✅ Network failure pattern tests
- ✅ Fake Relay test server
- ⬜ Relay protocol compliance test tool
- ⬜ Relay benchmarking tool

## Deployment & Operations

- ⬜ Official Docker image (ResilientDNS)
- ⬜ Docker Compose example (ResilientDNS + Relay)
- ⬜ Production hardening guide
- ⬜ Reverse proxy examples (Caddy / Nginx)

## Explicit Non-Goals

These are intentional design decisions.

- DNS-over-HTTPS inside the core resolver
- Automatic UDP ↔ TCP fallback
- Heuristic retries or adaptive behavior
- Content inspection or filtering
- Silent runtime configuration changes
- Protocol-breaking DNS behavior
