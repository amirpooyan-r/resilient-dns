# ResilientDNS

ResilientDNS is an open-source DNS cache and forwarder optimized for **unreliable, high-latency, and low-quality networks**.

It accepts standard DNS (UDP/TCP) from LAN devices and forwards misses through a **batched HTTPS relay** designed to work reliably without depending on HTTP/2.

## What problem does it solve?

Many environments suffer from:
- Unstable UDP/TCP DNS resolution
- DNS hijacking/tampering risk
- Slow or unreliable HTTPS connectivity
- Legacy devices that cannot use DoH directly
- Upstream DoH setups that generate too many HTTPS requests (aggressive prefetch)

ResilientDNS focuses on correctness and resilience while minimizing upstream HTTPS traffic.

## Implemented

- UDP DNS listener
- TTL-aware caching (positive + negative)
- Bounded cache eviction (expired-first, then LRU)
- Serve-stale behavior for resilience
- Stale-while-revalidate (SWR)
- SingleFlight deduplication
- Lightweight in-process metrics counters

## Planned

- Adaptive, budgeted prefetch for hot domains
- Upstream request batching via HTTP/1.1-friendly relay
- TCP support + truncation handling
- Metrics endpoint

## Status

🚧 Early development (MVP phase)

## Repository

- Source: GitHub repo (see top-right)
- Docs: This MkDocs site (published via GitHub Pages)
