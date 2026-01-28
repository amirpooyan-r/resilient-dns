# ResilientDNS

ResilientDNS is an open-source DNS cache and forwarder optimized for **unreliable, high-latency, and low-quality networks**.

It accepts standard DNS (UDP/TCP) from LAN devices and forwards misses through an explicitly selected upstream transport (direct UDP/TCP or a **batched HTTPS relay**).

## What problem does it solve?

Many environments suffer from:
- Unstable UDP/TCP DNS resolution
- DNS hijacking/tampering risk
- Slow or unreliable HTTPS connectivity
- Legacy devices that cannot use DoH directly
- Upstream DoH setups that generate too many HTTPS requests (aggressive prefetch)

ResilientDNS focuses on correctness and resilience while minimizing upstream HTTPS traffic.

## Implemented

- UDP/TCP DNS listeners
- TTL-aware caching (positive + negative)
- Bounded cache eviction (expired-first, then LRU)
- Serve-stale behavior for resilience
- Stale-while-revalidate (SWR)
- SingleFlight deduplication
- Batch refresh (hybrid TTL + popularity gate)
- Warmup list (startup preload)
- Explicit UDP/TCP/Relay upstream selection
- Relay upstream transport (HTTP batch DNS)
- Relay startup check (/v1/info) and limits compatibility checks
- Metrics endpoint (/metrics, /healthz, /readyz, /cache/stats)

## Planned

- Adaptive, budgeted prefetch for hot domains

## Status

🚧 Early development (MVP phase)

## Repository

- Source: GitHub repo (see top-right)
- Docs: This MkDocs site (published via GitHub Pages)
